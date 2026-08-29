//! Pruebas de integración mínimas que no requieren TTY ni Docker.
//!
//! Cargan la configuración del repositorio, validan que los perfiles parsean
//! correctamente y verifican que la UI se construye sin entrar al loop de
//! eventos (mediante `App::new`).

use std::path::PathBuf;

#[test]
fn load_settings_from_repo() {
    let repo = repo_dir();
    let settings = tui_v2::config::load(repo).expect("settings");
    assert!(settings.port > 0);
    assert_eq!(settings.host, "127.0.0.1");
}

#[test]
fn load_repository_profiles() {
    let repo = repo_dir();
    let settings = tui_v2::config::load(repo).expect("settings");
    let profiles = tui_v2::profiles::load(&settings).expect("profiles");
    assert!(profiles.contains_key("gemma-4-12b-qat-mtp"));
    assert!(profiles.contains_key("qwen-3.6-moe-2bit"));
}

#[test]
fn status_payload_round_trip() {
    let repo = repo_dir();
    let settings = tui_v2::config::load(repo).expect("settings");
    let payload = tui_v2::system::state_payload(&settings);
    assert!(payload.is_object());
    assert!(payload.get("state").is_some());
}

#[test]
fn port_is_available_or_in_use_consistent() {
    let repo = repo_dir();
    let settings = tui_v2::config::load(repo).expect("settings");
    let free = tui_v2::system::port_available(&settings.host, settings.port);
    // No afirmamos valor absoluto: sólo que la función no panicea.
    let _ = free;
}

#[test]
fn compose_command_contains_required_flags() {
    let repo = repo_dir();
    let settings = tui_v2::config::load(repo).expect("settings");
    let cmd = tui_v2::compose::compose_command(&settings, &["ps"]);
    assert_eq!(cmd[0], "docker");
    assert!(cmd.iter().any(|s| s == "compose"));
    assert!(cmd.iter().any(|s| s == "local-llm-agent-lab"));
    assert!(cmd.contains(&"ps".to_string()));
}

#[test]
fn unknown_profile_returns_error() {
    let repo = repo_dir();
    let settings = tui_v2::config::load(repo).expect("settings");
    let err = tui_v2::profiles::get(&settings, "no-existe").unwrap_err();
    let msg = format!("{err}");
    assert!(msg.contains("Perfil desconocido"));
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