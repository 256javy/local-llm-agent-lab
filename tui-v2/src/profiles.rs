//! Carga y validación de perfiles declarativos.
//!
//! Refleja `llm_lab.core.load_profiles` y `validate_profile` para mantener
//! el mismo contrato: el directorio `config/profiles/*.json` contiene un
//! perfil por archivo, validado contra un esquema mínimo obligatorio.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use color_eyre::Result;
use color_eyre::eyre::eyre;
use serde::Deserialize;

use crate::config::Settings;

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeSpec {
    pub adapter: String,
    pub repository: String,
    #[allow(dead_code)]
    pub revision: String,
    #[serde(default)]
    pub cmake_args: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ArtifactSpec {
    pub repository: String,
    pub file: String,
    #[serde(default)]
    pub sha256: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ServerSpec {
    pub context_size: u64,
    pub parallel: u64,
    pub arguments: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Requirements {
    #[serde(alias = "recommendedVramGiB")]
    pub recommended_vram_gib: u32,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Profile {
    pub id: String,
    pub display_name: String,
    pub runtime: RuntimeSpec,
    pub model: ArtifactSpec,
    #[serde(default)]
    pub draft_model: Option<ArtifactSpec>,
    pub server: ServerSpec,
    pub requirements: Requirements,
    pub status: String,
    #[serde(skip)]
    pub path: PathBuf,
}

impl Profile {
    pub fn gpu_label(&self) -> String {
        format!("{} GiB", self.requirements.recommended_vram_gib)
    }
}

pub fn load(settings: &Settings) -> Result<BTreeMap<String, Profile>> {
    let dir = settings.profiles_dir();
    if !dir.exists() {
        return Err(eyre!("directorio de perfiles inexistente: {}", dir.display()));
    }
    let mut profiles = BTreeMap::new();
    let mut errors = Vec::new();
    let entries = collect_files(&dir)?;
    for path in entries {
        let source = path.display().to_string();
        let raw = match fs::read_to_string(&path) {
            Ok(v) => v,
            Err(e) => {
                errors.push(format!("{source}: {e}"));
                continue;
            }
        };
        let mut profile: Profile = match serde_json::from_str(&raw) {
            Ok(v) => v,
            Err(e) => {
                errors.push(format!("{source}: {e}"));
                continue;
            }
        };
        if let Err(msgs) = validate(&profile) {
            for msg in msgs {
                errors.push(format!("{source}: {msg}"));
            }
            continue;
        }
        profile.path = path.clone();
        if profiles.insert(profile.id.clone(), profile).is_some() {
            errors.push(format!("ID de perfil duplicado: {}", source));
        }
    }
    if !errors.is_empty() {
        return Err(eyre!("Perfiles inválidos:\n- {}", errors.join("\n- ")));
    }
    if profiles.is_empty() {
        return Err(eyre!("No se encontraron perfiles en {}", dir.display()));
    }
    Ok(profiles)
}

pub fn get(settings: &Settings, id: &str) -> Result<Profile> {
    let profiles = load(settings)?;
    profiles
        .get(id)
        .cloned()
        .context_eyre_or(format!("Perfil desconocido: {id}"))
}

fn collect_files(dir: &Path) -> Result<Vec<PathBuf>> {
    let mut files: Vec<PathBuf> = fs::read_dir(dir)?
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| path.extension().and_then(|s| s.to_str()) == Some("json"))
        .collect();
    files.sort();
    Ok(files)
}

fn validate(profile: &Profile) -> Result<(), Vec<String>> {
    let mut errors = Vec::new();
    match profile.status.as_str() {
        "stable" | "candidate" | "experimental" => {}
        _ => errors.push("status inválido".to_string()),
    }
    if profile.runtime.adapter != "llama-cpp" {
        errors.push(format!("adaptador no soportado: {}", profile.runtime.adapter));
    }
    if profile.runtime.repository.is_empty() {
        errors.push("runtime.repository es obligatorio".to_string());
    }
    if profile.runtime.revision.is_empty() {
        errors.push("runtime.revision es obligatorio".to_string());
    }
    validate_artifact(&profile.model, "model", &mut errors);
    if let Some(ref draft) = profile.draft_model {
        validate_artifact(draft, "draftModel", &mut errors);
    }
    if profile.server.context_size < 1024 {
        errors.push("server.contextSize inválido".to_string());
    }
    if profile.server.parallel < 1 {
        errors.push("server.parallel inválido".to_string());
    }
    if profile.server.arguments.is_empty() {
        errors.push("server.arguments debe ser una lista de strings".to_string());
    }
    if errors.is_empty() { Ok(()) } else { Err(errors) }
}

fn validate_artifact(artifact: &ArtifactSpec, label: &str, errors: &mut Vec<String>) {
    if artifact.repository.is_empty() || !artifact.repository.contains('/') {
        errors.push(format!("{label}.repository inválido"));
    }
    if artifact.file.is_empty() {
        errors.push(format!("{label}.file es obligatorio"));
    }
    if let Some(ref sha) = artifact.sha256 {
        if sha.len() != 64 || !sha.chars().all(|c| c.is_ascii_hexdigit()) {
            errors.push(format!("{label}.sha256 inválido"));
        }
    }
}

trait OptionExt<T> {
    fn context_eyre_or(self, msg: impl Into<String>) -> Result<T>;
}

impl<T> OptionExt<T> for Option<T> {
    fn context_eyre_or(self, msg: impl Into<String>) -> Result<T> {
        self.ok_or_else(|| eyre!(msg.into()))
    }
}
