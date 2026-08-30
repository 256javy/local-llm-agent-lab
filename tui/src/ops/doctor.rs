//! Comando `doctor` — diagnóstico de requisitos sin modificar el host.

#![allow(dead_code)]

use std::collections::BTreeMap;
use std::sync::mpsc::Sender;

use color_eyre::Result;
use nix::sys::statvfs::statvfs;

use crate::compose;
use crate::config::Settings;
use crate::ops::{emit, OpEvent, Operation, Phase};
use crate::profiles;
use crate::state;
use crate::system::{self, gpu_info};

#[derive(Debug, Clone)]
pub struct DoctorReport {
    pub checks: BTreeMap<String, CheckResult>,
    pub all_ok: bool,
}

#[derive(Debug, Clone)]
pub struct CheckResult {
    pub ok: bool,
    pub detail: String,
}

pub struct DoctorOp {
    pub settings: Settings,
}

impl DoctorOp {
    pub fn new(settings: Settings) -> Self {
        Self { settings }
    }

    pub fn run(self, sink: &Sender<OpEvent>) -> Result<DoctorReport> {
        let _ = emit(sink, OpEvent::Phase(Phase::Init));
        let mut checks: BTreeMap<String, CheckResult> = BTreeMap::new();

        let profile_count = profiles::load(&self.settings).map(|p| p.len()).unwrap_or(0);
        checks.insert(
            "profiles".into(),
            CheckResult { ok: true, detail: format!("{} perfiles válidos", profile_count) },
        );

        for binary in ["docker", "nvidia-smi", "curl", "jq"] {
            let path = system::which(binary);
            checks.insert(
                binary.into(),
                CheckResult {
                    ok: path.is_some(),
                    detail: path.clone().unwrap_or_else(|| "no encontrado".into()),
                },
            );
        }

        let env = std::env::vars().collect();
        if system::which("docker").is_some() {
            let info = compose::run_raw(&self.settings, &env, &["docker", "info"]).ok();
            let ok = info.as_ref().map(|o| o.status == 0).unwrap_or(false);
            let detail = info
                .as_ref()
                .map(|o| if ok { "disponible".to_string() } else { fallback(&o.stderr, "no disponible") })
                .unwrap_or_else(|| "no disponible".into());
            checks.insert("docker-daemon".into(), CheckResult { ok, detail });
            let version = compose::run_raw(
                &self.settings,
                &env,
                &["docker", "compose", "version", "--short"],
            )
            .ok();
            let ok = version.as_ref().map(|o| o.status == 0).unwrap_or(false);
            let detail = version
                .as_ref()
                .map(|o| fallback(&o.stdout, &o.stderr))
                .unwrap_or_else(|| "no disponible".into());
            checks.insert("docker-compose".into(), CheckResult { ok, detail });
        }

        let gpu = gpu_info();
        checks.insert(
            "gpu".into(),
            CheckResult {
                ok: gpu.is_some(),
                detail: gpu
                    .as_ref()
                    .map(|g| format!("{} — {}/{} MiB", g.name, g.vram_used_mib, g.vram_total_mib))
                    .unwrap_or_else(|| "NVIDIA no disponible".into()),
            },
        );

        let state = state::read(&self.settings);
        let running = system::docker_container_running();
        let port_ok = system::port_available(&self.settings.host, self.settings.port);
        if state.is_some() && running {
            checks.insert(
                "port".into(),
                CheckResult {
                    ok: true,
                    detail: format!("{}:{} pertenece al perfil administrado", self.settings.host, self.settings.port),
                },
            );
        } else {
            checks.insert(
                "port".into(),
                CheckResult {
                    ok: port_ok,
                    detail: format!(
                        "{}:{} {}",
                        self.settings.host,
                        self.settings.port,
                        if port_ok { "libre" } else { "ocupado" }
                    ),
                },
            );
        }

        let usage = disk_free(&self.settings.data_dir);
        checks.insert(
            "storage".into(),
            CheckResult {
                ok: usage.as_ref().map(|u| *u >= 20 * 1024u64.pow(3)).unwrap_or(false),
                detail: usage
                    .map(|u| format!("{:.1} GiB libres en {}", u as f64 / 1024.0_f64.powi(3), self.settings.data_dir.display()))
                    .unwrap_or_else(|e| format!("{e}")),
            },
        );

        let failed: Vec<&str> = checks
            .iter()
            .filter(|(_, c)| !c.ok)
            .map(|(name, _)| name.as_str())
            .collect();
        for (name, check) in &checks {
            let mark = if check.ok { "OK" } else { "FAIL" };
            let _ = sink.send(OpEvent::Stream(crate::compose::StreamChunk {
                channel: if check.ok {
                    crate::compose::StreamChannel::Stdout
                } else {
                    crate::compose::StreamChannel::Stderr
                },
                line: format!("[{mark}] {name}: {}", check.detail),
            }));
        }
        let all_ok = failed.is_empty();
        let summary = if all_ok {
            "Diagnóstico: todos los requisitos en verde".to_string()
        } else {
            format!(
                "Diagnóstico: {} requisito(s) pendiente(s) — {}",
                failed.len(),
                failed.join(", ")
            )
        };
        let _ = sink.send(OpEvent::Done { summary: summary.clone() });
        let _ = emit(
            sink,
            OpEvent::Phase(if all_ok {
                Phase::Done { summary }
            } else {
                Phase::Failed { summary }
            }),
        );
        Ok(DoctorReport { checks, all_ok })
    }
}

fn fallback(primary: &str, secondary: &str) -> String {
    if primary.trim().is_empty() { secondary.to_string() } else { primary.to_string() }
}

/// Bytes libres en la partición que aloja `path`.
fn disk_free(path: &std::path::Path) -> std::io::Result<u64> {
    let mut target = path;
    while !target.exists() {
        if let Some(parent) = target.parent() {
            target = parent;
        } else {
            break;
        }
    }
    let stats = statvfs(target).map_err(|e| std::io::Error::from_raw_os_error(e as i32))?;
    Ok(stats.blocks_available() * stats.fragment_size())
}

impl Operation for DoctorOp {
    fn describe(&self) -> String {
        "doctor".into()
    }
}