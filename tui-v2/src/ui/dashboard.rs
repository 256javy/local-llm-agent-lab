//! Panel principal: estado activo, perfil seleccionado y lista de perfiles.

use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, List, ListItem, ListState, Paragraph, Wrap};
use ratatui::Frame;

use crate::ops::status::StatusReport;
use crate::profiles::Profile;
use crate::ui::theme::Theme;

pub struct DashboardView<'a> {
    pub status: &'a StatusReport,
    pub profiles: &'a [Profile],
    pub selected: usize,
    pub data_dir: &'a str,
    pub default_profile: &'a str,
    pub last_event: Option<&'a str>,
}

pub fn draw(frame: &mut Frame, area: Rect, theme: &Theme, view: &DashboardView) {
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(45), Constraint::Percentage(55)])
        .split(area);

    draw_status_panel(frame, chunks[0], theme, view);
    draw_profiles_panel(frame, chunks[1], theme, view);
}

fn draw_status_panel(frame: &mut Frame, area: Rect, theme: &Theme, view: &DashboardView) {
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(theme.muted)
        .title(Span::styled(" Estado ", theme.title));
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let state = view.status.state.as_str();
    let mut lines: Vec<Line> = Vec::new();
    lines.push(Line::from(vec![
        Span::styled("Estado:    ", theme.accent),
        Span::styled(state.to_ascii_uppercase(), theme.state_style(state)),
    ]));
    lines.push(Line::from(vec![
        Span::styled("Perfil:    ", theme.accent),
        Span::raw(view.status.profile.clone().unwrap_or_else(|| "—".into())),
    ]));
    lines.push(Line::from(vec![
        Span::styled("Endpoint:  ", theme.accent),
        Span::raw(view.status.endpoint.clone()),
    ]));
    lines.push(Line::from(vec![
        Span::styled("Contenedor:", theme.accent),
        Span::raw(if view.status.container_running { " sí" } else { " no" }),
    ]));
    if let Some(uptime) = view.status.uptime_seconds {
        lines.push(Line::from(vec![
            Span::styled("Uptime:    ", theme.accent),
            Span::raw(humanize_seconds(uptime)),
        ]));
    }
    lines.push(Line::from(""));
    if let Some(gpu) = &view.status.gpu {
        lines.push(Line::from(Span::styled("GPU", theme.title)));
        lines.push(Line::from(vec![
            Span::styled("  Modelo:   ", theme.accent),
            Span::raw(gpu.name.clone()),
        ]));
        lines.push(Line::from(vec![
            Span::styled("  Driver:   ", theme.accent),
            Span::raw(gpu.driver_version.clone()),
        ]));
        let pct = if gpu.vram_total_mib > 0 {
            (gpu.vram_used_mib as f64 / gpu.vram_total_mib as f64) * 100.0
        } else {
            0.0
        };
        lines.push(Line::from(vec![
            Span::styled("  VRAM:     ", theme.accent),
            Span::styled(
                format!("{} / {} MiB ({:.0}%)", gpu.vram_used_mib, gpu.vram_total_mib, pct),
                if pct >= 90.0 { theme.failed } else { theme.base },
            ),
        ]));
        lines.push(Line::from(vec![
            Span::styled("  Compute:  ", theme.accent),
            Span::raw(gpu.compute_capability.clone()),
        ]));
    } else {
        lines.push(Line::from(Span::styled("GPU: NVIDIA no disponible", theme.muted)));
    }
    lines.push(Line::from(""));
    lines.push(Line::from(vec![
        Span::styled("Datos:     ", theme.accent),
        Span::raw(view.data_dir.to_string()),
    ]));
    lines.push(Line::from(vec![
        Span::styled("Default:   ", theme.accent),
        Span::raw(view.default_profile.to_string()),
    ]));
    if let Some(event) = view.last_event {
        lines.push(Line::from(""));
        lines.push(Line::from(vec![
            Span::styled("Último:    ", theme.accent),
            Span::styled(event.to_string(), theme.info),
        ]));
    }

    let paragraph = Paragraph::new(lines).wrap(Wrap { trim: false });
    frame.render_widget(paragraph, inner);
}

fn draw_profiles_panel(frame: &mut Frame, area: Rect, theme: &Theme, view: &DashboardView) {
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(theme.muted)
        .title(Span::styled(" Perfiles ", theme.title));
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let items: Vec<ListItem> = view
        .profiles
        .iter()
        .enumerate()
        .map(|(idx, profile)| {
            let is_default = profile.id == view.default_profile;
            let is_active = view
                .status
                .profile
                .as_deref()
                .map(|p| p == profile.id)
                .unwrap_or(false);
            let marker = if is_active { "● " } else if is_default { "○ " } else { "  " };
            let status_color = match profile.status.as_str() {
                "stable" => theme.healthy,
                "candidate" => theme.starting,
                "experimental" => theme.failed,
                _ => theme.muted,
            };
            let mut spans = vec![
                Span::styled(marker, theme.accent),
                Span::styled(format!("{:<34}", truncate(&profile.id, 34)), theme.base),
                Span::styled(format!("{:<11}", profile.status), status_color),
                Span::styled(format!("{:>5} ", profile.gpu_label()), theme.muted),
            ];
            spans.push(Span::styled(profile.display_name.clone(), theme.base));
            let mut item = ListItem::new(Line::from(spans));
            if idx == view.selected {
                item = item.style(theme.selected);
            }
            item
        })
        .collect();

    let list = List::new(items).highlight_style(theme.selected);
    let mut state = ListState::default();
    state.select(Some(view.selected));
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