//! Comando `start` — inicia un perfil y espera a que esté saludable.

use std::sync::mpsc::Sender;
use std::time::Instant;

use color_eyre::Result;
use color_eyre::eyre::eyre;
use serde::Serialize;
use serde_json::{json, Value};

use crate::compose::{self};
use crate::config::Settings;
use crate::ops::{emit, OpEvent, Operation, Phase};
use crate::profiles::Profile;
use crate::state;
use crate::system::{self, gpu_info};

pub struct StartOp {
    pub settings: Settings,
    pub profile: Profile,
}

#[derive(Debug, Clone, Serialize)]
pub struct StartResult {
    pub profile_id: String,
    pub endpoint: String,
}

impl StartOp {
    pub fn new(settings: Settings, profile: Profile) -> Self {
        Self { settings, profile }
    }

    pub fn run(self, sink: &Sender<OpEvent>) -> Result<()> {
        let started = Instant::now();
        let result = self.run_inner(sink);
        let _ = started.elapsed();
        let summary = match &result {
            Ok(r) => format!("Perfil activo: {} en {}", r.profile_id, r.endpoint),
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
        result.map(|_| ()).map_err(|e| eyre!("{e}"))?;
        Ok(())
    }

    fn run_inner(&self, sink: &Sender<OpEvent>) -> Result<StartResult> {
        let _ = emit(sink, OpEvent::Phase(Phase::Init));
        let _guard = state::ControlLock::acquire(&self.settings)?;
        let state = state::read(&self.settings);
        let running = system::docker_container_running();
        if let Some(s) = &state {
            if s.get("state").and_then(|v| v.as_str()) != Some(state::HEALTHY)
                && s.get("profile").and_then(|v| v.as_str()) == Some(self.profile.id.as_str())
                && running
            {
                let _ = emit(
                    sink,
                    OpEvent::Phase(Phase::Info {
                        summary: "Reconciliando perfil existente…".into(),
                    }),
                );
                let payload = system::wait_for_health(&self.settings)?;
                let _ = emit(sink, OpEvent::Phase(Phase::WaitingHealth { endpoint: self.settings.endpoint() }));
                let mut new_state = s.clone();
                new_state.as_object_mut().ok_or_else(|| eyre!("state no es objeto"))?.insert("state".into(), Value::String(state::HEALTHY.into()));
                state::write(&self.settings, &new_state)?;
                let _ = emit(sink, OpEvent::Phase(Phase::WaitingHealth { endpoint: self.settings.endpoint() }));
                let _ = payload;
                return Ok(StartResult {
                    profile_id: self.profile.id.clone(),
                    endpoint: self.settings.endpoint(),
                });
            }
            if s.get("state").and_then(|v| v.as_str()) == Some(state::HEALTHY) && running {
                if s.get("profile").and_then(|v| v.as_str()) == Some(self.profile.id.as_str()) {
                    let _ = emit(sink, OpEvent::Phase(Phase::Info {
                        summary: format!("El perfil {} ya está activo", self.profile.id),
                    }));
                    return Ok(StartResult {
                        profile_id: self.profile.id.clone(),
                        endpoint: self.settings.endpoint(),
                    });
                }
                return Err(eyre!(
                    "Ya está activo {}; usa `switch {}`",
                    s.get("profile").and_then(|v| v.as_str()).unwrap_or("?"),
                    self.profile.id
                ));
            }
        }
        if !system::port_available(&self.settings.host, self.settings.port) {
            return Err(eyre!(
                "El puerto {}:{} está ocupado",
                self.settings.host,
                self.settings.port
            ));
        }
        let env = compose::compose_env(&self.settings, &self.profile);
        let baseline = gpu_info().map(|g| g.vram_used_mib);
        let mut state_base = json!({
            "profile": self.profile.id,
            "endpoint": self.settings.endpoint(),
            "runtime": self.profile.runtime.adapter,
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
        system::wait_for_health(&self.settings)?;
        if let Value::Object(map) = &mut state_base {
            map.insert("state".into(), Value::String(state::HEALTHY.into()));
        }
        state::write(&self.settings, &state_base)?;
        Ok(StartResult {
            profile_id: self.profile.id.clone(),
            endpoint: self.settings.endpoint(),
        })
    }
}

impl Operation for StartOp {
    fn describe(&self) -> String {
        format!("start {}", self.profile.id)
    }
}

fn forward_streams(proc: &mut compose::Subprocess, sink: &Sender<OpEvent>) {
    let mut readers = Vec::new();
    if let Some(rx) = proc.stdout.take() {
        let sink = sink.clone();
        readers.push(std::thread::spawn(move || {
            for chunk in rx {
                let _ = sink.send(OpEvent::Stream(chunk));
            }
        }));
    }
    if let Some(rx) = proc.stderr.take() {
        let sink = sink.clone();
        readers.push(std::thread::spawn(move || {
            for chunk in rx {
                let _ = sink.send(OpEvent::Stream(chunk));
            }
        }));
    }
    for reader in readers {
        let _ = reader.join();
    }
}
