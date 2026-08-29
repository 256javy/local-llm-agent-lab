//! Overlay modal durante operaciones largas.
//!
//! Muestra la fase actual con un spinner animado y un log streamed en vivo
//! del subproceso. Bloquea la interacción con el dashboard y se cierra
//! automáticamente al finalizar.

use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Clear, Paragraph, Wrap};
use ratatui::Frame;

use crate::ops::Phase;
use crate::ui::theme::Theme;

pub struct OverlayView<'a> {
    pub title: &'a str,
    pub phase: Option<&'a Phase>,
    pub log_lines: &'a [String],
    pub frame_idx: usize,
    pub elapsed_secs: u64,
    pub can_cancel: bool,
}

const FRAMES: &[&str] = &["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

pub fn draw(frame: &mut Frame, area: Rect, theme: &Theme, view: &OverlayView) {
    let popup = centered_rect(75, 75, area);
    frame.render_widget(Clear, popup);
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(theme.accent)
        .title(Span::styled(format!(" {} ", view.title), theme.title));
    let inner = block.inner(popup);
    frame.render_widget(block, popup);

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(5), Constraint::Min(5)])
        .split(inner);

    draw_phase(frame, chunks[0], theme, view);
    draw_log(frame, chunks[1], theme, view.log_lines);
}

fn centered_rect(percent_x: u16, percent_y: u16, area: Rect) -> Rect {
    let popup_y = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Percentage((100 - percent_y) / 2),
            Constraint::Percentage(percent_y),
            Constraint::Percentage((100 - percent_y) / 2),
        ])
        .split(area);
    Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage((100 - percent_x) / 2),
            Constraint::Percentage(percent_x),
            Constraint::Percentage((100 - percent_x) / 2),
        ])
        .split(popup_y[1])[1]
}

fn draw_phase(frame: &mut Frame, area: Rect, theme: &Theme, view: &OverlayView) {
    let spinner = FRAMES[view.frame_idx % FRAMES.len()];
    let mut lines: Vec<Line> = Vec::new();
    lines.push(Line::from(vec![
        Span::styled(spinner, theme.spinner),
        Span::raw(" "),
        Span::styled("Operación en curso", theme.accent),
        Span::raw("  "),
        Span::styled(format!("{:02}:{:02}", view.elapsed_secs / 60, view.elapsed_secs % 60), theme.muted),
    ]));
    if let Some(phase) = view.phase {
        lines.push(Line::from(vec![
            Span::styled("Fase:      ", theme.accent),
            Span::styled(phase_label(phase), theme.info),
        ]));
        lines.push(Line::from(vec![
            Span::styled("Detalle:   ", theme.accent),
            Span::styled(phase_detail(phase), theme.base),
        ]));
    }
    if view.can_cancel {
        lines.push(Line::from(Span::styled("Pulsa Esc para cancelar", theme.muted)));
    }
    let paragraph = Paragraph::new(lines).wrap(Wrap { trim: false });
    frame.render_widget(paragraph, area);
}

fn draw_log(frame: &mut Frame, area: Rect, theme: &Theme, lines: &[String]) {
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(theme.muted)
        .title(Span::styled(" Log ", theme.muted));
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let visible = lines
        .iter()
        .rev()
        .take(inner.height as usize)
        .rev()
        .map(|line| Line::from(Span::styled(line.clone(), theme.log_stdout)))
        .collect::<Vec<_>>();
    let paragraph = Paragraph::new(visible).wrap(Wrap { trim: false });
    frame.render_widget(paragraph, inner);
}

pub fn phase_label(phase: &Phase) -> &'static str {
    match phase {
        Phase::Init => "Inicializando",
        Phase::Building { .. } => "Construyendo contenedor",
        Phase::WaitingHealth { .. } => "Esperando /health",
        Phase::Stopping { .. } => "Deteniendo contenedor",
        Phase::WaitingVram { .. } => "Liberando VRAM",
        Phase::Done { .. } => "Completado",
        Phase::Failed { .. } => "Fallido",
        Phase::Info { .. } => "Información",
    }
}

pub fn phase_detail(phase: &Phase) -> String {
    match phase {
        Phase::Init => "Preparando entorno…".into(),
        Phase::Building { service } => format!("docker compose up --build {service}"),
        Phase::WaitingHealth { endpoint } => format!("sondeando {endpoint}"),
        Phase::Stopping { container } => format!("docker compose down ({container})"),
        Phase::WaitingVram { baseline_mib, current_mib } => format!(
            "baseline {baseline_mib} MiB · actual {current_mib} MiB"
        ),
        Phase::Done { summary } | Phase::Failed { summary } | Phase::Info { summary } => summary.clone(),
    }
}