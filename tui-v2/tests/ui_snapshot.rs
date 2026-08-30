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
                right_panel: tui_v2::ui::dashboard::RightPanel::Profiles,
            };
            let area = frame.area();
            let header_height = tui_v2::ui::header::preferred_height(area);
            let chunks = ratatui::layout::Layout::default()
                .direction(ratatui::layout::Direction::Vertical)
                .constraints([
                    ratatui::layout::Constraint::Length(header_height),
                    ratatui::layout::Constraint::Min(8),
                    ratatui::layout::Constraint::Length(3),
                ])
                .split(area);
            tui_v2::ui::header::draw(
                frame,
                chunks[0],
                &Default::default(),
                "0.1.0",
                &status.state,
                &settings.endpoint(),
                status.profile.as_deref(),
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
    assert!(text.contains("Local LLM Agent Lab") || text.contains("████"));
    assert!(text.contains("Perfiles disponibles") || text.contains("PERFILES DISPONIBLES"));
    assert!(text.contains("Estado del lab"));
    assert!(text.contains("Perfil activo"));
    assert!(text.contains("Endpoint OpenAI"));
    assert!(text.contains("Contenedor Docker"));
    assert!(text.contains("VRAM usada"));
    assert!(text.contains("VRAM MIN"));
    assert!(text.contains("MADUREZ"));
}

fn render_header_text(width: u16, height: u16) -> String {
    let backend = TestBackend::new(width, height);
    let mut terminal = Terminal::new(backend).expect("terminal");
    terminal
        .draw(|frame| {
            let area = frame.area();
            let header_area = ratatui::layout::Rect::new(
                0,
                0,
                width,
                tui_v2::ui::header::preferred_height(area),
            );
            tui_v2::ui::header::draw(
                frame,
                header_area,
                &Default::default(),
                "0.1.0",
                "healthy",
                "http://127.0.0.1:18080/v1",
                Some("gemma"),
            );
        })
        .expect("draw");
    terminal
        .backend()
        .buffer()
        .content
        .iter()
        .map(|cell| cell.symbol())
        .collect::<Vec<_>>()
        .join("")
}

#[test]
fn header_wide_uses_ascii_banner_and_operational_metadata() {
    let out = render_header_text(140, 32);
    assert!(out.contains("████"));
    assert!(out.contains("http://127.0.0.1:18080/v1"));
    assert!(out.contains("HEALTHY"));
}

#[test]
fn header_narrow_keeps_compact_branding() {
    let out = render_header_text(80, 24);
    assert!(out.contains("Local LLM Agent Lab"));
    assert!(out.contains("healthy"));
    assert!(!out.contains("████"));
}

#[test]
fn dashboard_can_keep_operation_in_right_panel() {
    use tui_v2::ops::Phase;
    use tui_v2::ui::overlay::{OverlayKind, OverlayView};

    let backend = TestBackend::new(100, 24);
    let mut terminal = Terminal::new(backend).expect("terminal");
    let operation = OverlayView {
        title: "logs · follow",
        phase: Some(&Phase::Streaming {
            tail: 200,
            follow: true,
        }),
        log_lines: &["  llama-server listo".to_string()],
        frame_idx: 0,
        elapsed_secs: 12,
        kind: OverlayKind::Running,
    };

    terminal
        .draw(|frame| {
            tui_v2::ui::overlay::draw_panel(
                frame,
                frame.area(),
                &Default::default(),
                &operation,
            );
        })
        .expect("draw");

    let text = terminal
        .backend()
        .buffer()
        .content
        .iter()
        .map(|cell| cell.symbol())
        .collect::<Vec<_>>()
        .join("");
    assert!(text.contains("logs · follow"));
    assert!(text.contains("Leyendo logs del contenedor"));
    assert!(text.contains("llama-server listo"));
}

#[test]
fn tail_prompt_modal_renders() {
    use ratatui::backend::TestBackend;
    use ratatui::Terminal;

    let backend = TestBackend::new(120, 40);
    let mut terminal = Terminal::new(backend).expect("terminal");

    terminal
        .draw(|frame| {
            let area = frame.area();
            tui_v2::ui::input::draw(
                frame,
                area,
                &Default::default(),
                "Logs · número de líneas",
                "Cantidad de líneas a mostrar del contenedor.",
                "500",
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
    assert!(text.contains("Logs"));
    assert!(text.contains("número de líneas"));
    assert!(text.contains("500"));
    assert!(text.contains("confirmar"));
}

#[test]
fn footer_groups_have_labels() {
    use ratatui::backend::TestBackend;
    use ratatui::Terminal;

    let backend = TestBackend::new(200, 4);
    let mut terminal = Terminal::new(backend).expect("terminal");

    terminal
        .draw(|frame| {
            let area = frame.area();
            tui_v2::ui::footer::draw(
                frame,
                area,
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
    assert!(text.contains("Perfil"));
    assert!(text.contains("Logs"));
    assert!(text.contains("Sistema"));
    assert!(text.contains("│"));
    assert!(text.contains("arrancar"));
    assert!(text.contains("stop"));
    assert!(text.contains("follow"));
}

fn render_footer_text(width: u16, height: u16) -> String {
    use ratatui::backend::TestBackend;
    use ratatui::Terminal;

    let backend = TestBackend::new(width, height);
    let mut terminal = Terminal::new(backend).expect("terminal");
    terminal
        .draw(|frame| {
            tui_v2::ui::footer::draw(
                frame,
                ratatui::layout::Rect::new(0, 0, width, height),
                &Default::default(),
                tui_v2::ui::footer::Mode::Dashboard,
            );
        })
        .expect("draw");
    let buffer = terminal.backend().buffer().clone();
    let mut out = String::new();
    for y in 0..buffer.area.height {
        let mut line = String::new();
        for x in 0..buffer.area.width {
            line.push_str(buffer[(x, y)].symbol());
        }
        out.push_str(line.trim_end());
        out.push('\n');
    }
    out
}

#[test]
fn footer_wide_fits_in_three_lines() {
    let out = render_footer_text(140, 6);
    let non_empty: Vec<&str> = out
        .lines()
        .filter(|l| !l.trim().is_empty())
        .collect();
    assert!(
        non_empty.len() <= 3,
        "esperado <=3 líneas en ancho 140, obtuve {}: {non_empty:?}",
        non_empty.len()
    );
    assert!(
        non_empty.len() >= 2,
        "esperado al menos 2 líneas en ancho 140, obtuve {}: {non_empty:?}",
        non_empty.len()
    );
}

#[test]
fn footer_narrow_wraps_without_orphan_separators() {
    let out = render_footer_text(60, 8);
    let non_empty: Vec<&str> = out
        .lines()
        .filter(|l| !l.trim().is_empty())
        .collect();
    assert!(
        non_empty.len() >= 3,
        "esperado envolver a >=3 líneas en ancho 60, obtuve {}",
        non_empty.len()
    );
    for line in &non_empty {
        assert!(
            !line.trim().starts_with("│") || line.trim().starts_with("│  "),
            "línea no debe empezar con `│` aislado: {line:?}"
        );
    }
}

#[test]
fn footer_very_narrow_uses_cont_marker() {
    let out = render_footer_text(40, 10);
    assert!(
        out.contains("(cont.)"),
        "esperado marcador de continuación con ancho 40"
    );
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
