//! Tema visual y constantes de estilo.
//!
//! Mantener los estilos centralizados permite ajustar el aspecto desde un
//! solo punto y respetar las convenciones semánticas del estado
//! (`healthy`/`starting`/`failed`/etc.).

use ratatui::style::{Color, Modifier, Style};

#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct Theme {
    pub base: Style,
    pub muted: Style,
    pub accent: Style,
    pub title: Style,
    pub healthy: Style,
    pub starting: Style,
    pub stopping: Style,
    pub failed: Style,
    pub idle: Style,
    pub stale: Style,
    pub info: Style,
    pub log_stdout: Style,
    pub log_stderr: Style,
    pub selected: Style,
    pub focus: Style,
    pub footer_key: Style,
    pub footer_desc: Style,
    pub spinner: Style,
}

impl Default for Theme {
    fn default() -> Self {
        Self {
            base: Style::default().fg(Color::Reset),
            muted: Style::default().fg(Color::DarkGray),
            accent: Style::default().fg(Color::Magenta).add_modifier(Modifier::BOLD),
            title: Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
            healthy: Style::default().fg(Color::Green).add_modifier(Modifier::BOLD),
            starting: Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD),
            stopping: Style::default().fg(Color::Yellow),
            failed: Style::default().fg(Color::Red).add_modifier(Modifier::BOLD),
            idle: Style::default().fg(Color::Blue),
            stale: Style::default().fg(Color::LightRed),
            info: Style::default().fg(Color::Cyan),
            log_stdout: Style::default().fg(Color::Reset),
            log_stderr: Style::default().fg(Color::LightRed),
            selected: Style::default().bg(Color::Indexed(237)).fg(Color::White),
            focus: Style::default().fg(Color::Magenta).add_modifier(Modifier::BOLD),
            footer_key: Style::default().fg(Color::Magenta).add_modifier(Modifier::BOLD),
            footer_desc: Style::default().fg(Color::Gray),
            spinner: Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
        }
    }
}

impl Theme {
    pub fn state_style(&self, state: &str) -> Style {
        match state.to_ascii_lowercase().as_str() {
            "healthy" | "running" => self.healthy,
            "starting" => self.starting,
            "stopping" => self.stopping,
            "failed" | "error" | "stopped" => self.failed,
            "stale" => self.stale,
            "idle" => self.idle,
            _ => self.info,
        }
    }
}