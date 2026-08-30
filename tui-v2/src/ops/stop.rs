//! Comando `stop` — detiene el perfil administrado y libera VRAM.

use std::sync::mpsc::Sender;
use std::time::{Duration, Instant};

use color_eyre::Result;
use color_eyre::eyre::{eyre, ContextCompat};

use crate::compose::{self};
use crate::config::Settings;
use crate::ops::{emit, OpEvent, Operation, Phase};
use crate::profiles::Profile;
use crate::state;
use crate::system::{self, gpu_info};

pub struct StopOp {
    pub settings: Settings,
    pub profile: Option<Profile>,
}

impl StopOp {
    pub fn new(settings: Settings, profile: Option<Profile>) -> Self {
        Self { settings, profile }
    }

    pub fn run(self, sink: &Sender<OpEvent>) -> Result<()> {
        let result = self.run_inner(sink);
        let summary = match &result {
            Ok(_) => "Servidor detenido; modelos y caches fueron preservados".to_string(),
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
        if state.is_none() && !running {
            let _ = emit(sink, OpEvent::Phase(Phase::Info {
                summary: "No hay un perfil administrado activo".into(),
            }));
            return Ok(());
        }
        let env = compose::compose_env(&self.settings, self.profile.as_ref().context("perfil no resuelto")?);
        let _ = emit(sink, OpEvent::Phase(Phase::Stopping {
            container: crate::config::container_name().into(),
        }));
        let mut proc = compose::run_streamed(
            &self.settings,
            &env,
            &["down", "--remove-orphans", "--timeout", &self.settings.stop_timeout.to_string()],
        )?;
        forward_streams(&mut proc, sink);
        let status = proc.wait()?;
        if status != 0 {
            return Err(eyre!("docker compose down salió con código {status}"));
        }
        let deadline = Instant::now() + Duration::from_secs(self.settings.stop_timeout);
        while system::docker_container_running() && Instant::now() < deadline {
            std::thread::sleep(Duration::from_secs(1));
        }
        if system::docker_container_running() {
            return Err(eyre!("El contenedor administrado no se detuvo; no se iniciará otro perfil"));
        }
        if let Some(s) = &state {
            if let Some(baseline) = s.get("vramBaselineMiB").and_then(|v| v.as_u64()) {
                let deadline = Instant::now() + Duration::from_secs(self.settings.stop_timeout);
                loop {
                        let current = gpu_info().map(|g| g.vram_used_mib).unwrap_or(0);
                        let _ = emit(sink, OpEvent::Phase(Phase::WaitingVram {
                            baseline_mib: baseline,
                            current_mib: current,
                        }));
                        if current <= baseline + 512 {
                            break;
                        }
                        if Instant::now() >= deadline {
                            return Err(eyre!(
                                "La VRAM no volvió al nivel previo: se esperaban como máximo {} MiB",
                                baseline + 512
                            ));
                        }
                        std::thread::sleep(Duration::from_secs(1));
                    }
            }
        }
        state::clear(&self.settings)?;
        Ok(())
    }
}

impl Operation for StopOp {
    fn describe(&self) -> String {
        format!("stop{}", self.profile.as_ref().map(|p| format!(" {}", p.id)).unwrap_or_default())
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
