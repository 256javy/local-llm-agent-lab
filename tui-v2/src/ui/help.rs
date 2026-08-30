//! Pantalla de ayuda con el mapa completo de teclas y comandos.

use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Clear, Paragraph, Wrap};
use ratatui::Frame;

use crate::ui::theme::Theme;

pub fn draw(frame: &mut Frame, area: Rect, theme: &Theme) {
    let popup = centered_rect(70, 75, area);
    frame.render_widget(Clear, popup);
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(theme.accent)
        .title(Span::styled(" Ayuda ", theme.title));
    let inner = block.inner(popup);
    frame.render_widget(block, popup);

    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(inner);

    let left = vec![
        Line::from(Span::styled("Teclas", theme.title)),
        Line::from(""),
        Line::from(vec![Span::styled("↑/↓", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("navegar perfiles")]),
        Line::from(vec![Span::styled("Enter", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("arrancar perfil seleccionado")]),
        Line::from(vec![Span::styled("s", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("switch al perfil seleccionado (apaga el actual y libera VRAM)")]),
        Line::from(vec![Span::styled("x", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("detener el contenedor administrado (preserva modelos y caches)")]),
        Line::from(vec![Span::styled("d", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("marcar perfil como default")]),
        Line::from(vec![Span::styled("r", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("refrescar estado del lab y GPU")]),
        Line::from(vec![Span::styled("p", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("recargar lista de perfiles desde disco")]),
        Line::from(vec![Span::styled("h", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("sondear /health del endpoint")]),
        Line::from(vec![Span::styled("l", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("ver logs · tail 200 (sin follow)")]),
        Line::from(vec![Span::styled("L", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("seguir logs · tail 200 con --follow")]),
        Line::from(vec![Span::styled("t", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("ver logs · tail N (sin follow)")]),
        Line::from(vec![Span::styled("T", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("seguir logs · tail N con --follow")]),
        Line::from(vec![Span::styled("D", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("diagnóstico (doctor)")]),
        Line::from(vec![Span::styled("F1/?", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("ayuda")]),
        Line::from(vec![Span::styled("q", theme.footer_key), Span::styled(" · ", theme.muted), Span::raw("salir")]),
    ];
    let right = vec![
        Line::from(Span::styled("Estados del lab", theme.title)),
        Line::from(""),
        Line::from(vec![Span::styled("HEALTHY ", theme.healthy), Span::raw(" perfil activo y respondiendo /health")]),
        Line::from(vec![Span::styled("STARTING ", theme.starting), Span::raw(" arrancando contenedor")]),
        Line::from(vec![Span::styled("STOPPING ", theme.stopping), Span::raw(" apagando contenedor")]),
        Line::from(vec![Span::styled("FAILED ", theme.failed), Span::raw(" última operación fallida")]),
        Line::from(vec![Span::styled("IDLE ", theme.idle), Span::raw(" sin perfil administrado")]),
        Line::from(vec![Span::styled("STALE ", theme.stale), Span::raw(" estado inconsistente con docker")]),
        Line::from(""),
        Line::from(Span::styled("Reglas operativas", theme.title)),
        Line::from(""),
        Line::from("• Sólo un perfil GPU activo a la vez."),
        Line::from("• `stop` y `switch` preservan modelos y caches en disco."),
        Line::from("• Antes de levantar otro perfil se espera a que la VRAM vuelva a la línea base (con margen de 512 MiB)."),
        Line::from("• El lock de control previene operaciones concurrentes."),
    ];
    let left_para = Paragraph::new(left).wrap(Wrap { trim: false });
    let right_para = Paragraph::new(right).wrap(Wrap { trim: false });
    frame.render_widget(left_para, chunks[0]);
    frame.render_widget(right_para, chunks[1]);
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