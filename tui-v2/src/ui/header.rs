//! Header con branding adaptable, reloj y estado resumido.

use chrono::Local;
use ratatui::layout::{Alignment, Rect};
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use ratatui::Frame;

use crate::ui::theme::Theme;

const BANNER_MIN_WIDTH: u16 = 102;
const BANNER_MIN_TERMINAL_HEIGHT: u16 = 28;
const BANNER_HEIGHT: u16 = 6;
const COMPACT_HEIGHT: u16 = 4;

const PROJECT_NAME: &str = "LOCAL LLM AGENT LAB";

/// Altura apropiada para el encabezado según el espacio total disponible.
pub fn preferred_height(area: Rect) -> u16 {
    if area.width >= BANNER_MIN_WIDTH && area.height >= BANNER_MIN_TERMINAL_HEIGHT {
        BANNER_HEIGHT
    } else {
        COMPACT_HEIGHT
    }
}

pub fn draw(
    frame: &mut Frame,
    area: Rect,
    theme: &Theme,
    version: &str,
    state_label: &str,
    endpoint: &str,
    active_profile: Option<&str>,
) {
    if area.width >= BANNER_MIN_WIDTH && area.height >= BANNER_HEIGHT {
        draw_banner(
            frame,
            area,
            theme,
            version,
            state_label,
            endpoint,
            active_profile,
        );
    } else {
        draw_compact(
            frame,
            area,
            theme,
            version,
            state_label,
            endpoint,
            active_profile,
        );
    }
}

fn draw_banner(
    frame: &mut Frame,
    area: Rect,
    theme: &Theme,
    version: &str,
    state_label: &str,
    endpoint: &str,
    active_profile: Option<&str>,
) {
    let now = Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
    let mut lines = vec![Line::from("")];
    lines.extend(
        solid_banner(PROJECT_NAME)
            .into_iter()
            .map(|line| Line::from(Span::styled(line, theme.title)).alignment(Alignment::Center)),
    );
    lines.push(metadata_line(theme, version, endpoint, active_profile));
    lines.push(Line::from(vec![
        Span::styled(
            state_label.to_ascii_uppercase(),
            theme.state_style(state_label),
        ),
        Span::styled("  ·  ", theme.muted),
        Span::styled(now, theme.muted),
    ]));
    frame.render_widget(Paragraph::new(lines).alignment(Alignment::Center), area);
}

fn draw_compact(
    frame: &mut Frame,
    area: Rect,
    theme: &Theme,
    version: &str,
    state_label: &str,
    endpoint: &str,
    active_profile: Option<&str>,
) {
    let now = Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
    let lines = vec![
        Line::from(vec![
            Span::styled("Local LLM Agent Lab", theme.title),
            Span::raw("  "),
            Span::styled(format!("v{version}"), theme.muted),
        ]),
        metadata_line(theme, version, endpoint, active_profile),
        Line::from(""),
        Line::from(vec![
            Span::styled(state_label, theme.state_style(state_label)),
            Span::raw("  "),
            Span::styled(now, theme.muted),
        ]),
    ];
    frame.render_widget(Paragraph::new(lines), area);
}

fn metadata_line<'a>(
    theme: &Theme,
    version: &str,
    endpoint: &str,
    active_profile: Option<&str>,
) -> Line<'a> {
    let mut spans = vec![
        Span::styled(format!("v{version}"), theme.muted),
        Span::styled("  ·  endpoint ", theme.muted),
        Span::styled(endpoint.to_string(), theme.info),
        Span::styled("  ·  perfil activo: ", theme.muted),
    ];
    match active_profile {
        Some(profile) => spans.push(Span::styled(profile.to_string(), theme.accent)),
        None => spans.push(Span::styled("ninguno", theme.starting)),
    }
    Line::from(spans)
}

fn solid_banner(text: &str) -> Vec<String> {
    let mut rows = vec![String::new(); 3];
    for character in text.chars() {
        let glyph = compressed_glyph(character);
        for (row, segment) in rows.iter_mut().zip(glyph) {
            if !row.is_empty() {
                row.push(' ');
            }
            row.push_str(&segment);
        }
    }
    rows
}

fn compressed_glyph(character: char) -> [String; 3] {
    let source = solid_glyph(character);
    [
        merge_pixel_rows(source[0], source[1]),
        merge_pixel_rows(source[2], source[3]),
        merge_pixel_rows(source[4], "    "),
    ]
}

fn merge_pixel_rows(upper: &str, lower: &str) -> String {
    upper
        .chars()
        .zip(lower.chars())
        .map(|(top, bottom)| match (top == '█', bottom == '█') {
            (true, true) => '█',
            (true, false) => '▀',
            (false, true) => '▄',
            (false, false) => ' ',
        })
        .collect()
}

fn solid_glyph(character: char) -> [&'static str; 5] {
    match character {
        'A' => [" ██ ", "█  █", "████", "█  █", "█  █"],
        'B' => ["███ ", "█  █", "███ ", "█  █", "███ "],
        'C' => [" ███", "█   ", "█   ", "█   ", " ███"],
        'E' => ["████", "█   ", "███ ", "█   ", "████"],
        'G' => [" ███", "█   ", "█ ██", "█  █", " ███"],
        'L' => ["█   ", "█   ", "█   ", "█   ", "████"],
        'M' => ["█  █", "████", "█ ██", "█  █", "█  █"],
        'N' => ["█  █", "██ █", "████", "█ ██", "█  █"],
        'O' => [" ██ ", "█  █", "█  █", "█  █", " ██ "],
        'T' => ["████", " ██ ", " ██ ", " ██ ", " ██ "],
        ' ' => [" ", " ", " ", " ", " "],
        _ => ["????", "????", "????", "????", "????"],
    }
}
