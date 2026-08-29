//! Comando `switch` — cambia de perfil de forma exclusiva.

use std::sync::mpsc::Sender;

use color_eyre::Result;
use color_eyre::eyre::eyre;
use serde_json::{json, Value};

use crate::compose::{self};
use crate::config::Settings;
use crate::ops::{emit, OpEvent, Operation, Phase};
use crate::profiles::{self, Profile};
use crate::state;
use crate::system::{self, gpu_info};

pub struct SwitchOp {
    pub settings: Settings,
    pub target: Profile,
}

impl SwitchOp {
    pub fn new(settings: Settings, target: Profile) -> Self {
        Self { settings, target }
    }

    pub fn run(self, sink: &Sender<OpEvent>) -> Result<()> {
        let result = self.run_inner(sink);
        let summary = match &result {
            Ok(_) => format!("Perfil activo: {} en {}", self.target.id, self.settings.endpoint()),
            Err(e) => format!("ERROR: {e}"),
        };
        let _ = sink.send(if result.is_ok() {
            OpEvent::Done { summary: summary.clone() }
        } else {
            OpEvent::Failed { summary: summary.clone() }
        });
        let _ = emit(sink, OpEvent::Phase(if result.is_ok() {
            Phase::Done { summary }
        } else {
            Phase::Failed { summary }
        }));
        result
    }

    fn run_inner(&self, sink: &Sender<OpEvent>) -> Result<()> {
        let _ = emit(sink, OpEvent::Phase(Phase::Init));
        let _guard = state::ControlLock::acquire(&self.settings)?;
        let state = state::read(&self.settings);
        let running = system::docker_container_running();
        if let Some(s) = &state {
            if s.get("profile").and_then(|v| v.as_str()) == Some(self.target.id.as_str()) && running {
                let _ = emit(sink, OpEvent::Phase(Phase::Info {
                    summary: format!("El perfil {} ya está activo", self.target.id),
                }));
                return Ok(());
            }
        }
        let current = if let Some(s) = &state {
            if let Some(id) = s.get("profile").and_then(|v| v.as_str()) {
                profiles::get(&self.settings, id).ok()
            } else {
                None
            }
        } else {
            None
        };
        if state.is_some() || running {
            let _ = emit(sink, OpEvent::Phase(Phase::Stopping {
                container: crate::config::container_name().into(),
            }));
            let env = match &current {
                Some(p) => compose::compose_env(&self.settings, p),
                None => std::env::vars().collect(),
            };
            let mut proc = compose::run_streamed(
                &self.settings,
                &env,
                &["down", "--remove-orphans"],
            )?;
            forward_streams(&mut proc, sink);
            let status = proc.wait()?;
            if status != 0 {
                return Err(eyre!("docker compose down salió con código {status}"));
            }
        }
        if !system::port_available(&self.settings.host, self.settings.port) {
            return Err(eyre!(
                "El puerto {}:{} sigue ocupado por un proceso externo",
                self.settings.host,
                self.settings.port
            ));
        }
        let env = compose::compose_env(&self.settings, &self.target);
        let baseline = gpu_info().map(|g| g.vram_used_mib);
        let mut state_base = json!({
            "profile": self.target.id,
            "endpoint": self.settings.endpoint(),
            "runtime": self.target.runtime.adapter,
            "startedAt": std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs_f64())
                .unwrap_or(0.0),
            "vramBaselineMiB": baseline,
        });
        if let Value::Object(map) = &mut state_base {
            map.insert("state".into(), Value::String(state::STARTING.into()));
        }
        state::write(&self.settings, &state_base)?;
        let _ = emit(sink, OpEvent::Phase(Phase::Building { service: compose::service_name().into() }));
        let mut proc = compose::run_streamed(
            &self.settings,
            &env,
            &["up", "-d", "--build", compose::service_name()],
        )?;
        forward_streams(&mut proc, sink);
        let status = proc.wait()?;
        if status != 0 {
            if let Value::Object(map) = &mut state_base {
                map.insert("state".into(), Value::String(state::FAILED.into()));
            }
            state::write(&self.settings, &state_base)?;
            return Err(eyre!("docker compose up salió con código {status}"));
        }
        let _ = emit(sink, OpEvent::Phase(Phase::WaitingHealth { endpoint: self.settings.endpoint() }));
        system::wait_for_health(&self.settings).map_err(|e| eyre!("el servidor no quedó saludable: {e}"))?;
        if let Value::Object(map) = &mut state_base {
            map.insert("state".into(), Value::String(state::HEALTHY.into()));
        }
        state::write(&self.settings, &state_base)?;
        Ok(())
    }
}

impl Operation for SwitchOp {
    fn describe(&self) -> String {
        format!("switch {}", self.target.id)
    }
}

fn forward_streams(proc: &mut compose::Subprocess, sink: &Sender<OpEvent>) {
    if let Some(rx) = proc.stdout.take() {
        for chunk in rx {
            let _ = sink.send(OpEvent::Stream(chunk));
        }
    }
    if let Some(rx) = proc.stderr.take() {
        for chunk in rx {
            let _ = sink.send(OpEvent::Stream(chunk));
        }
    }
}