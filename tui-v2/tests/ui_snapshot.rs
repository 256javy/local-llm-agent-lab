//! Snapshot no-interactivo del dashboard.
//!
//! Renderiza la vista con un backend `TestBackend` para verificar que la
//! estructura visual no rompe (sin entrar al loop de eventos).

use std::path::PathBuf;

use ratatui::backend::TestBackend;
use ratatui::Terminal;

#[test]
fn dashboard_renders_without_panic() {
    let repo = repo_dir();
    let settings = tui_v2::config::load(repo).expect("settings");
    let profiles = tui_v2::profiles::load(&settings).expect("profiles");
    let profiles: Vec<tui_v2::profiles::Profile> = profiles.into_values().collect();

    let backend = TestBackend::new(120, 30);
    let mut terminal = Terminal::new(backend).expect("terminal");

    let status = tui_v2::ops::status::StatusOp::new(settings.clone())
        .run(&dummy_sink())
        .expect("status");
    let data_dir = settings.data_dir.display().to_string();

    terminal
        .draw(|frame| {
            let view = tui_v2::ui::dashboard::DashboardView {
                status: &status,
                profiles: &profiles,
                selected: 0,
                data_dir: &data_dir,
                default_profile: &settings.default_profile,
                last_event: Some("snapshot"),
            };
            let area = frame.area();
            let chunks = ratatui::layout::Layout::default()
                .direction(ratatui::layout::Direction::Vertical)
                .constraints([
                    ratatui::layout::Constraint::Length(4),
                    ratatui::layout::Constraint::Min(8),
                    ratatui::layout::Constraint::Length(2),
                ])
                .split(area);
            tui_v2::ui::header::draw(
                frame,
                chunks[0],
                &Default::default(),
                "0.1.0",
                &status.state,
                &format!("endpoint {}", settings.endpoint()),
            );
            tui_v2::ui::dashboard::draw(frame, chunks[1], &Default::default(), &view);
            tui_v2::ui::footer::draw(
                frame,
                chunks[2],
                &Default::default(),
                tui_v2::ui::footer::Mode::Dashboard,
            );
        })
        .expect("draw");

    let buffer = terminal.backend().buffer().clone();
    let text = buffer
        .content
        .iter()
        .map(|c| c.symbol())
        .collect::<Vec<_>>()
        .join("");
    assert!(text.contains("Local LLM Agent Lab"));
    assert!(text.contains("Perfiles") || text.contains("PERFILES"));
    assert!(text.contains("Estado"));
}

fn dummy_sink() -> std::sync::mpsc::Sender<tui_v2::ops::OpEvent> {
    let (tx, _rx) = std::sync::mpsc::channel();
    tx
}

fn repo_dir() -> PathBuf {
    if let Ok(value) = std::env::var("LLM_LAB_REPO_DIR") {
        return PathBuf::from(value);
    }
    let exe = std::env::current_exe().unwrap();
    let mut current = exe.parent().map(|p| p.to_path_buf());
    while let Some(dir) = current.clone() {
        if dir.join("compose.yaml").is_file() && dir.join("config").join("profiles").is_dir() {
            return dir;
        }
        current = dir.parent().map(|p| p.to_path_buf());
    }
    std::env::current_dir().unwrap()
}