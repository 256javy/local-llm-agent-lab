//! Header con branding, reloj y estado resumido.

use chrono::Local;
use ratatui::layout::Rect;
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use ratatui::Frame;

use crate::ui::theme::Theme;

pub fn draw(frame: &mut Frame, area: Rect, theme: &Theme, version: &str, state_label: &str, summary: &str) {
    let now = Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
    let left = Line::from(vec![
        Span::styled("⚙ Local LLM Agent Lab", theme.title),
        Span::raw("  "),
        Span::styled(format!("v{version}"), theme.muted),
    ]);
    let right = Line::from(vec![
        Span::styled(state_label, theme.state_style(state_label)),
        Span::raw("  "),
        Span::styled(now, theme.muted),
    ]);
    let lines = vec![
        left,
        Line::from(Span::styled(summary, theme.muted)),
        Line::from(""),
        right,
    ];
    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, area);
}