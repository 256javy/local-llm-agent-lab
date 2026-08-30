//! Modal pequeño para introducir un número (p.ej. tail de logs).
//!
//! Reusa la estética del diálogo de confirmación pero con una línea editable
//! que sólo acepta dígitos. Se muestra como popup centrado con un footer
//! específico (`Enter` confirma, `Esc` cancela, `Backspace` borra).

use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Clear, Paragraph, Wrap};
use ratatui::Frame;

use crate::ui::theme::Theme;

pub fn draw(frame: &mut Frame, area: Rect, theme: &Theme, title: &str, prompt: &str, value: &str) {
    let popup = centered_rect(50, 25, area);
    frame.render_widget(Clear, popup);
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(theme.accent)
        .title(Span::styled(format!(" {title} "), theme.title));
    let inner = block.inner(popup);
    frame.render_widget(block, popup);

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(2),
            Constraint::Length(3),
            Constraint::Min(1),
            Constraint::Length(1),
        ])
        .split(inner);

    let body = Paragraph::new(prompt.to_string()).wrap(Wrap { trim: true });
    frame.render_widget(body, chunks[0]);

    let input_block = Block::default()
        .borders(Borders::ALL)
        .border_style(theme.muted)
        .title(Span::styled(" valor ", theme.muted));
    let input_inner = input_block.inner(chunks[1]);
    frame.render_widget(input_block, chunks[1]);
    let input_line = Line::from(vec![
        Span::styled("> ", theme.accent),
        Span::styled(value.to_string(), theme.base),
        Span::styled("▏", theme.spinner),
    ]);
    frame.render_widget(Paragraph::new(input_line), input_inner);

    let footer = Paragraph::new(Line::from(vec![
        Span::styled("Enter", theme.footer_key),
        Span::raw(" confirmar  "),
        Span::styled("Esc", theme.footer_key),
        Span::raw(" cancelar  "),
        Span::styled("Backspace", theme.footer_key),
        Span::raw(" borrar"),
    ]));
    frame.render_widget(footer, chunks[3]);
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