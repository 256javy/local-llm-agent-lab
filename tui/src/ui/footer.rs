//! Footer con atajos de teclado contextuales al modo actual.
//!
//! La barra inferior muestra pares `tecla · descripción` agrupados por
//! intención y separados por una cabecera corta. Si la línea es más
//! ancha que el terminal, los hints se recolocan uno por uno en líneas
//! consecutivas — un hint nunca se parte a la mitad. La estrategia es
//! "un grupo por línea": si un grupo no cabe entero en la línea
//! actual, baja completo a la siguiente y se omite el `│` que lo
//! precedía, evitando separadores huérfanos.

use ratatui::layout::Rect;
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use ratatui::Frame;

use unicode_width::UnicodeWidthStr;

use crate::ui::theme::Theme;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Dashboard,
    Operation,
    Help,
    TailPrompt,
}

pub struct Hint {
    pub key: &'static str,
    pub desc: &'static str,
}

pub struct HintGroup {
    pub label: &'static str,
    pub hints: Vec<Hint>,
}

const GROUP_SEP: &str = "  │  ";
const HINT_SEP: &str = "  ";
const KEY_DESC_SEP: &str = " · ";

pub fn hints_for(mode: Mode) -> Vec<HintGroup> {
    match mode {
        Mode::Dashboard => vec![
            HintGroup {
                label: "Perfil",
                hints: vec![
                    Hint { key: "↑↓", desc: "navegar" },
                    Hint { key: "Enter", desc: "arrancar" },
                    Hint { key: "s", desc: "switch" },
                    Hint { key: "x", desc: "stop" },
                    Hint { key: "d", desc: "default" },
                ],
            },
            HintGroup {
                label: "Logs",
                hints: vec![
                    Hint { key: "l", desc: "tail 200" },
                    Hint { key: "L", desc: "follow" },
                    Hint { key: "t", desc: "tail N" },
                    Hint { key: "T", desc: "follow N" },
                ],
            },
            HintGroup {
                label: "Sistema",
                hints: vec![
                    Hint { key: "p", desc: "perfiles" },
                    Hint { key: "h", desc: "health" },
                    Hint { key: "D", desc: "doctor" },
                    Hint { key: "r", desc: "refrescar" },
                    Hint { key: "?", desc: "ayuda" },
                    Hint { key: "q", desc: "salir" },
                ],
            },
        ],
        Mode::Operation => vec![HintGroup {
            label: "Panel derecho",
            hints: vec![
                Hint { key: "Esc", desc: "cancelar" },
                Hint { key: "q", desc: "abortar y salir" },
            ],
        }],
        Mode::Help => vec![HintGroup {
            label: "Ayuda",
            hints: vec![
                Hint { key: "Esc/?", desc: "cerrar" },
                Hint { key: "q", desc: "salir" },
            ],
        }],
        Mode::TailPrompt => vec![HintGroup {
            label: "Tail N",
            hints: vec![
                Hint { key: "0-9", desc: "número" },
                Hint { key: "Enter", desc: "mostrar" },
                Hint { key: "Esc", desc: "cancelar" },
            ],
        }],
    }
}

fn hint_width(hint: &Hint) -> usize {
    hint.key.width() + " ".width() + hint.desc.width() + KEY_DESC_SEP.width()
}

/// Coste horizontal del `Label` de un grupo (incluye el `·`).
fn label_width(label: &str) -> usize {
    label.width() + " · ".width()
}

/// Coste horizontal del bloque "Label + todos los hints" del grupo.
fn group_block_width(group: &HintGroup) -> usize {
    label_width(group.label)
        + group
            .hints
            .iter()
            .enumerate()
            .map(|(i, h)| if i == 0 { hint_width(h) } else { HINT_SEP.width() + hint_width(h) })
            .sum::<usize>()
}

/// Construye los spans del bloque "Label · hints…" de un grupo.
fn render_group(theme: &Theme, group: &HintGroup) -> Vec<Span<'static>> {
    let mut spans: Vec<Span> = Vec::new();
    spans.push(Span::styled(group.label.to_string(), theme.title));
    spans.push(Span::styled(" · ".to_string(), theme.muted));
    for (j, hint) in group.hints.iter().enumerate() {
        if j > 0 {
            spans.push(Span::raw(HINT_SEP.to_string()));
        }
        spans.push(Span::styled(hint.key.to_string(), theme.footer_key));
        spans.push(Span::styled(" ".to_string(), theme.muted));
        spans.push(Span::styled(hint.desc.to_string(), theme.footer_desc));
        spans.push(Span::styled(KEY_DESC_SEP.to_string(), theme.muted));
    }
    spans
}

/// Estrategia de layout:
/// - Si un grupo entero (label + hints) cabe en la línea actual, va entero.
/// - Si no cabe, baja a la siguiente línea. Si aun así no cabe, se parte
///   por hints y se usa una etiqueta de continuación (`Perfil · (cont.)`)
///   para mantener identificable cada fragmento.
pub fn draw(frame: &mut Frame, area: Rect, theme: &Theme, mode: Mode) {
    let width = area.width as usize;
    if width == 0 {
        return;
    }
    let groups = hints_for(mode);
    let mut lines: Vec<Line> = Vec::new();
    let mut first_in_line = true;

    for (i, group) in groups.iter().enumerate() {
        let needs_sep = i > 0;
        let gw = group_block_width(group);
        let sep_w = if needs_sep { GROUP_SEP.width() } else { 0 };
        let full_w = sep_w + gw;

        if full_w <= width {
            let last_w = lines.last().map(line_width).unwrap_or(0);
            let fits_inline = !first_in_line && last_w + full_w <= width;
            if fits_inline {
                append_group(lines.last_mut().unwrap(), theme, group, needs_sep);
            } else {
                let mut spans = Vec::new();
                if needs_sep {
                    spans.push(Span::styled(GROUP_SEP.to_string(), theme.muted));
                }
                spans.extend(render_group(theme, group));
                lines.push(Line::from(spans));
            }
            first_in_line = false;
        } else {
            // No cabe ni en una línea vacía: partirlo por hints.
            split_group_into(&mut lines, theme, group, needs_sep, width);
            first_in_line = true;
        }
    }

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, area);
}

/// Estima el ancho en columnas de una `Line` sumando el contenido de
/// sus spans. Usa `UnicodeWidthStr` para contar correctamente `↑↓`,
/// `│` y otros glifos.
fn line_width(line: &Line) -> usize {
    line.iter().map(|s| s.width()).sum()
}

fn append_group(line: &mut Line, theme: &Theme, group: &HintGroup, needs_sep: bool) {
    if needs_sep {
        line.push_span(Span::styled(GROUP_SEP.to_string(), theme.muted));
    }
    for sp in render_group(theme, group) {
        line.push_span(sp);
    }
}

fn split_group_into(
    lines: &mut Vec<Line>,
    theme: &Theme,
    group: &HintGroup,
    needs_sep: bool,
    width: usize,
) {
    // Caso terminal: la línea está vacía y el grupo sigue sin caber;
    // partimos por hints repitiendo la etiqueta como "continuación".
    let label_w = label_width(group.label);
    let hint_sep_w = HINT_SEP.width();

    let mut current: Vec<Span> = Vec::new();
    let mut used = 0usize;
    if needs_sep && !lines.is_empty() {
        current.push(Span::styled(GROUP_SEP.to_string(), theme.muted));
        used += GROUP_SEP.width();
    }
    // Primera "página": con etiqueta completa.
    current.push(Span::styled(group.label.to_string(), theme.title));
    current.push(Span::styled(" · ".to_string(), theme.muted));
    used += label_w;

    let mut first = true;
    for hint in &group.hints {
        let hw = hint_width(hint);
        let sep_w = if first { 0 } else { hint_sep_w };
        let need = sep_w + hw;
        if used + need > width && !current.is_empty() {
            lines.push(Line::from(std::mem::take(&mut current)));
            used = 0;
            // Línea de continuación: repetimos la etiqueta para que cada
            // hint siga identificable.
            current.push(Span::styled(
                format!("{} · (cont.) ", group.label),
                theme.muted,
            ));
            used += group.label.width() + " · (cont.) ".width();
            first = true;
        }
if !first {
            current.push(Span::raw(HINT_SEP.to_string()));
            used += hint_sep_w;
        }
        current.push(Span::styled(hint.key.to_string(), theme.footer_key));
        current.push(Span::styled(" ".to_string(), theme.muted));
        current.push(Span::styled(hint.desc.to_string(), theme.footer_desc));
        current.push(Span::styled(KEY_DESC_SEP.to_string(), theme.muted));
        used += hw;
        first = false;
    }
    if !current.is_empty() {
        lines.push(Line::from(current));
    }
}
