//! Diálogo modal de confirmación para acciones destructivas.

use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Clear, Paragraph, Wrap};
use ratatui::Frame;

use crate::ui::theme::Theme;

pub fn draw(frame: &mut Frame, area: Rect, theme: &Theme, title: &str, message: &str) {
    let popup = centered_rect(60, 30, area);
    frame.render_widget(Clear, popup);
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(theme.accent)
        .title(Span::styled(format!(" {title} "), theme.title));
    let inner = block.inner(popup);
    frame.render_widget(block, popup);

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Min(3), Constraint::Length(2)])
        .split(inner);

    let body = Paragraph::new(message.to_string()).wrap(Wrap { trim: true });
    let footer = Paragraph::new(Line::from(vec![
        Span::styled("Enter", theme.footer_key),
        Span::raw(" confirmar  "),
        Span::styled("Esc", theme.footer_key),
        Span::raw(" cancelar"),
    ]));
    frame.render_widget(body, chunks[0]);
    frame.render_widget(footer, chunks[1]);
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