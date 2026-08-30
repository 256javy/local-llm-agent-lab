//! Punto de entrada de la TUI (Rust + ratatui + crossterm).
//!
//! Carga la configuración del laboratorio, abre la terminal alternativa,
//! delega todo el ciclo de vida al `App`, y restaura la terminal al salir.

use std::path::PathBuf;

use color_eyre::Result;

use llm_lab_tui::app;
use llm_lab_tui::config;

const VERSION: &str = env!("CARGO_PKG_VERSION");

fn main() -> Result<()> {
    color_eyre::install()?;
    let repo_dir = detect_repo_dir();
    let settings = config::load(repo_dir)?;
    let terminal = ratatui::init();
    let result = app::App::new(settings, VERSION).and_then(|app| app.run(terminal));
    ratatui::restore();
    if let Err(ref e) = result {
        eprintln!("ERROR: {e:?}");
    }
    result
}

fn detect_repo_dir() -> PathBuf {
    if let Ok(value) = std::env::var("LLM_LAB_REPO_DIR") {
        return PathBuf::from(value);
    }
    let exe = std::env::current_exe().ok();
    if let Some(exe) = exe {
        let mut current = exe.parent().map(|p| p.to_path_buf());
        while let Some(dir) = current.clone() {
            if dir.join("compose.yaml").is_file() && dir.join("config").join("profiles").is_dir() {
                return dir;
            }
            current = dir.parent().map(|p| p.to_path_buf());
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}
