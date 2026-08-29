//! Footer con atajos de teclado contextuales al modo actual.
//!
//! La barra inferior muestra pares `tecla descripción` agrupados por modo
//! para mantener descubribles las acciones sin saturar la pantalla.

use ratatui::layout::Rect;
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use ratatui::Frame;

use crate::ui::theme::Theme;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Dashboard,
    Operation,
    Help,
}

pub struct Hint {
    pub key: &'static str,
    pub desc: &'static str,
}

pub fn hints_for(mode: Mode) -> Vec<Vec<Hint>> {
    match mode {
        Mode::Dashboard => vec![
            vec![
                Hint { key: "↑↓", desc: "perfil" },
                Hint { key: "Enter", desc: "arrancar" },
                Hint { key: "s", desc: "switch" },
                Hint { key: "x", desc: "stop" },
                Hint { key: "d", desc: "default" },
            ],
            vec![
                Hint { key: "p", desc: "perfiles" },
                Hint { key: "h", desc: "health" },
                Hint { key: "l", desc: "logs" },
                Hint { key: "D", desc: "doctor" },
                Hint { key: "?", desc: "ayuda" },
                Hint { key: "q", desc: "salir" },
            ],
        ],
        Mode::Operation => vec![vec![
            Hint { key: "Esc", desc: "cancelar" },
            Hint { key: "q", desc: "abortar y salir" },
        ]],
        Mode::Help => vec![vec![
            Hint { key: "Esc/?", desc: "cerrar" },
            Hint { key: "q", desc: "salir" },
        ]],
    }
}

pub fn draw(frame: &mut Frame, area: Rect, theme: &Theme, mode: Mode) {
    let groups = hints_for(mode);
    let mut spans: Vec<Span> = Vec::new();
    for (i, group) in groups.iter().enumerate() {
        if i > 0 {
            spans.push(Span::styled("  │  ", theme.muted));
        }
        for (j, hint) in group.iter().enumerate() {
            if j > 0 {
                spans.push(Span::raw(" "));
            }
            spans.push(Span::styled(hint.key, theme.footer_key));
            spans.push(Span::styled(" ", theme.footer_desc));
            spans.push(Span::styled(hint.desc, theme.footer_desc));
        }
    }
    let line = Line::from(spans);
    let paragraph = Paragraph::new(line);
    frame.render_widget(paragraph, area);
}