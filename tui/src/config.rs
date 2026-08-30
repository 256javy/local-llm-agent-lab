//! Configuración del laboratorio (paridad con `llm_lab.core.Settings`).
//!
//! Carga `.env` del repositorio y resuelve las variables de entorno con la
//! misma precedencia que la CLI en Python: variable de proceso > archivo >
//! valor predeterminado.

use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use color_eyre::Result;
use color_eyre::eyre::{eyre, Context};

#[derive(Debug, Clone)]
pub struct Settings {
    pub repo_dir: PathBuf,
    pub host: String,
    pub port: u16,
    pub data_dir: PathBuf,
    pub default_profile: String,
    pub api_key: String,
    pub start_timeout: u64,
    pub stop_timeout: u64,
}

impl Settings {
    pub fn endpoint(&self) -> String {
        format!("http://{}:{}/v1", self.host, self.port)
    }

    pub fn state_dir(&self) -> PathBuf {
        let base = env::var_os("XDG_STATE_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home_dir().join(".local").join("state"));
        base.join("local-llm-agent-lab")
    }

    pub fn state_file(&self) -> PathBuf {
        self.state_dir().join("state.json")
    }

    pub fn lock_file(&self) -> PathBuf {
        self.state_dir().join("control.lock")
    }

    pub fn compose_file(&self) -> PathBuf {
        self.repo_dir.join("compose.yaml")
    }

    pub fn profiles_dir(&self) -> PathBuf {
        self.repo_dir.join("config").join("profiles")
    }
}

pub fn home_dir() -> PathBuf {
    env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn parse_env_file(path: &Path) -> HashMap<String, String> {
    let mut values = HashMap::new();
    let Ok(content) = fs::read_to_string(path) else {
        return values;
    };
    for raw in content.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') || !line.contains('=') {
            continue;
        }
        let Some((k, v)) = line.split_once('=') else { continue };
        values.insert(k.trim().to_string(), v.trim().trim_matches('"').trim_matches('\'').to_string());
    }
    values
}

fn lookup(name: &str, default: &str, file: &HashMap<String, String>) -> String {
    env::var(name)
        .ok()
        .or_else(|| file.get(name).cloned())
        .unwrap_or_else(|| default.to_string())
}

fn parse_int(name: &str, default: &str, file: &HashMap<String, String>) -> Result<u64> {
    let raw = lookup(name, default, file);
    raw.parse::<u64>().with_context(|| format!("valor numérico inválido para {name}: {raw}"))
}

fn expand_home(path: PathBuf) -> PathBuf {
    if path.as_os_str() == "~" {
        return home_dir();
    }
    if path.starts_with("~/") {
        let suffix = path.strip_prefix("~/").unwrap().to_path_buf();
        return home_dir().join(suffix);
    }
    path
}

fn resolve_dir(path: PathBuf) -> PathBuf {
    std::fs::canonicalize(&path).unwrap_or(path)
}

pub fn load(repo_dir: PathBuf) -> Result<Settings> {
    let file = parse_env_file(&repo_dir.join(".env"));
    let data_raw = lookup("LLM_LAB_DATA_DIR", "", &file);
    let data_dir = if data_raw.is_empty() {
        let base = env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home_dir().join(".local").join("share"));
        base.join("local-llm-agent-lab")
    } else {
        resolve_dir(expand_home(PathBuf::from(data_raw)))
    };
    let port: u16 = parse_int("LLM_LAB_PORT", "18080", &file)?
        .try_into()
        .map_err(|_| eyre!("puerto fuera de rango"))?;
    let start_timeout = parse_int("LLM_LAB_START_TIMEOUT", "900", &file)?;
    let stop_timeout = parse_int("LLM_LAB_STOP_TIMEOUT", "60", &file)?;
    if port == 0 {
        return Err(eyre!("puerto fuera de rango"));
    }
    Ok(Settings {
        repo_dir,
        host: lookup("LLM_LAB_HOST", "127.0.0.1", &file),
        port,
        data_dir,
        default_profile: lookup("LLM_LAB_DEFAULT_PROFILE", "gemma-4-12b-qat-mtp", &file),
        api_key: lookup("LLM_LAB_API_KEY", "", &file),
        start_timeout,
        stop_timeout,
    })
}

pub fn project_name() -> &'static str {
    "local-llm-agent-lab"
}

pub fn server_service() -> &'static str {
    "server"
}

pub fn container_name() -> &'static str {
    "local-llm-agent-lab-server"
}
