//! Overlay modal durante operaciones largas.
//!
//! Muestra la fase actual con un spinner animado y un log streamed en vivo
//! del subproceso. Bloquea la interacción con el dashboard. Al terminar la
//! operación, el overlay permanece con el snapshot final hasta que el
//! usuario lo descarte con `Esc`, `Enter` o `q`.

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
    pub kind: OverlayKind,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OverlayKind {
    Running,
    Finished { ok: bool },
}

const FRAMES: &[&str] = &["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

impl<'a> OverlayView<'a> {
    fn can_cancel(&self) -> bool {
        matches!(self.kind, OverlayKind::Running | OverlayKind::Finished { .. })
    }

    fn dismiss_hint(&self) -> &'static str {
        match self.kind {
            OverlayKind::Running => "Pulsa Esc para cancelar",
            OverlayKind::Finished { .. } => "Pulsa Esc, Enter o q para cerrar",
        }
    }
}

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
    let mut lines: Vec<Line> = Vec::new();
    let mut header: Vec<Span> = Vec::new();
    match view.kind {
        OverlayKind::Running => {
            let spinner = FRAMES[view.frame_idx % FRAMES.len()];
            header.push(Span::styled(spinner, theme.spinner));
            header.push(Span::raw(" "));
            header.push(Span::styled("Operación en curso", theme.accent));
        }
        OverlayKind::Finished { ok } => {
            header.push(Span::styled(
                if ok { "✓" } else { "✗" },
                if ok { theme.healthy } else { theme.failed },
            ));
            header.push(Span::raw(" "));
            header.push(Span::styled(
                if ok { "Operación finalizada" } else { "Operación fallida" },
                theme.accent,
            ));
        }
    }
    header.push(Span::raw("  "));
    header.push(Span::styled(
        format!("{:02}:{:02}", view.elapsed_secs / 60, view.elapsed_secs % 60),
        theme.muted,
    ));
    lines.push(Line::from(header));
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
    if view.can_cancel() {
        lines.push(Line::from(Span::styled(
            view.dismiss_hint(),
            theme.muted,
        )));
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