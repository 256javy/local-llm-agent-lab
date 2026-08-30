//! Panel principal: estado activo, perfil seleccionado y lista de perfiles.

use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, List, ListItem, ListState, Paragraph, Wrap};
use ratatui::Frame;

use crate::ops::status::StatusReport;
use crate::profiles::Profile;
use crate::ui::overlay::OverlayView;
use crate::ui::theme::Theme;

pub enum RightPanel<'a> {
    Profiles,
    Operation(OverlayView<'a>),
}

pub struct DashboardView<'a> {
    pub status: &'a StatusReport,
    pub profiles: &'a [Profile],
    pub selected: usize,
    pub data_dir: &'a str,
    pub default_profile: &'a str,
    pub last_event: Option<&'a str>,
    pub right_panel: RightPanel<'a>,
}

pub fn draw(frame: &mut Frame, area: Rect, theme: &Theme, view: &DashboardView) {
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(45), Constraint::Percentage(55)])
        .split(area);

    draw_status_panel(frame, chunks[0], theme, view);
    match &view.right_panel {
        RightPanel::Profiles => draw_profiles_panel(frame, chunks[1], theme, view),
        RightPanel::Operation(operation) => {
            crate::ui::overlay::draw_panel(frame, chunks[1], theme, operation)
        }
    }
}

fn draw_status_panel(frame: &mut Frame, area: Rect, theme: &Theme, view: &DashboardView) {
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(theme.muted)
        .title(Span::styled(" Estado del lab ", theme.title));
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let state = view.status.state.as_str();
    let mut lines: Vec<Line> = Vec::new();
    lines.push(Line::from(vec![
        Span::styled("Estado del lab:    ", theme.accent),
        Span::styled(state.to_ascii_uppercase(), theme.state_style(state)),
    ]));
    lines.push(Line::from(vec![
        Span::styled("Perfil activo:      ", theme.accent),
        Span::styled(
            view.status.profile.clone().unwrap_or_else(|| "—".into()),
            theme.base,
        ),
    ]));
    lines.push(Line::from(vec![
        Span::styled("Endpoint OpenAI:    ", theme.accent),
        Span::styled(view.status.endpoint.clone(), theme.base),
    ]));
    lines.push(Line::from(vec![
        Span::styled("Contenedor Docker:  ", theme.accent),
        Span::styled(
            if view.status.container_running {
                "en ejecución"
            } else {
                "detenido"
            },
            if view.status.container_running {
                theme.healthy
            } else {
                theme.muted
            },
        ),
    ]));
    if let Some(uptime) = view.status.uptime_seconds {
        lines.push(Line::from(vec![
            Span::styled("Uptime:             ", theme.accent),
            Span::styled(humanize_seconds(uptime), theme.base),
        ]));
    }
    if let Some(event) = view.last_event {
        lines.push(Line::from(vec![
            Span::styled("Último evento:      ", theme.accent),
            Span::styled(event.to_string(), theme.info),
        ]));
    }
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled("GPU NVIDIA", theme.title)));
    if let Some(gpu) = &view.status.gpu {
        lines.push(Line::from(vec![
            Span::styled("  Tarjeta:          ", theme.accent),
            Span::styled(gpu.name.clone(), theme.base),
        ]));
        lines.push(Line::from(vec![
            Span::styled("  Driver:           ", theme.accent),
            Span::styled(gpu.driver_version.clone(), theme.base),
        ]));
        let pct = if gpu.vram_total_mib > 0 {
            (gpu.vram_used_mib as f64 / gpu.vram_total_mib as f64) * 100.0
        } else {
            0.0
        };
        lines.push(Line::from(vec![
            Span::styled("  VRAM usada:       ", theme.accent),
            Span::styled(
                format!("{} / {} MiB ({:.0}%)", gpu.vram_used_mib, gpu.vram_total_mib, pct),
                if pct >= 90.0 { theme.failed } else { theme.base },
            ),
        ]));
        lines.push(Line::from(vec![
            Span::styled("  Compute:          ", theme.accent),
            Span::styled(gpu.compute_capability.clone(), theme.base),
        ]));
    } else {
        lines.push(Line::from(Span::styled(
            "  NVIDIA no disponible",
            theme.muted,
        )));
    }
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled("Almacenamiento", theme.title)));
    lines.push(Line::from(vec![
        Span::styled("Datos persistentes: ", theme.accent),
        Span::styled(view.data_dir.to_string(), theme.base),
    ]));
    lines.push(Line::from(vec![
        Span::styled("Perfil default:     ", theme.accent),
        Span::styled(view.default_profile.to_string(), theme.base),
    ]));

    let paragraph = Paragraph::new(lines).wrap(Wrap { trim: false });
    frame.render_widget(paragraph, inner);
}

fn draw_profiles_panel(frame: &mut Frame, area: Rect, theme: &Theme, view: &DashboardView) {
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(theme.muted)
        .title(Span::styled(" Perfiles disponibles ", theme.title));
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let header = Line::from(vec![
        Span::styled("  ", theme.muted),
        Span::styled(format!("{:<10}", "MADUREZ"), theme.title),
        Span::styled(format!("{:<32}", "ID"), theme.title),
        Span::styled(format!("{:>10}", "VRAM MIN"), theme.title),
        Span::styled("  NOMBRE", theme.title),
    ]);
    let mut items: Vec<ListItem> = Vec::new();
    items.push(ListItem::new(header));
    items.extend(view.profiles.iter().enumerate().map(|(idx, profile)| {
        let is_default = profile.id == view.default_profile;
        let is_active = view
            .status
            .profile
            .as_deref()
            .map(|p| p == profile.id)
            .unwrap_or(false);
        let marker = if is_active {
            "● "
        } else if is_default {
            "○ "
        } else {
            "  "
        };
        let status_color = match profile.status.as_str() {
            "stable" => theme.healthy,
            "candidate" => theme.starting,
            "experimental" => theme.failed,
            _ => theme.muted,
        };
        let status_label = match profile.status.as_str() {
            "stable" => "stable",
            "candidate" => "candidate",
            "experimental" => "experim.",
            _ => "?",
        };
        let spans = vec![
            Span::styled(marker, theme.accent),
            Span::styled(format!("{:<10}", status_label), status_color),
            Span::styled(format!("{:<32}", truncate(&profile.id, 32)), theme.base),
            Span::styled(format!("{:>10} ", profile.gpu_label()), theme.muted),
            Span::styled(profile.display_name.clone(), theme.base),
        ];
        let mut item = ListItem::new(Line::from(spans));
        if idx == view.selected {
            item = item.style(theme.selected);
        }
        item
    }));

    let list = List::new(items).highlight_style(theme.selected);
    let mut state = ListState::default();
    state.select(Some(view.selected + 1));
    frame.render_stateful_widget(list, inner, &mut state);
}

fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let mut out: String = s.chars().take(max.saturating_sub(1)).collect();
        out.push('…');
        out
    }
}

fn humanize_seconds(s: u64) -> String {
    let h = s / 3600;
    let m = (s % 3600) / 60;
    let sec = s % 60;
    if h > 0 {
        format!("{}h {}m {}s", h, m, sec)
    } else if m > 0 {
        format!("{}m {}s", m, sec)
    } else {
        format!("{}s", sec)
    }
}
