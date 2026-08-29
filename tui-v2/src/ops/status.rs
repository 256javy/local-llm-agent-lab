//! Comando `status` — consulta inmediata del estado del laboratorio.

use std::sync::mpsc::Sender;

use color_eyre::Result;
use serde::Serialize;

use crate::config::Settings;
use crate::ops::{emit, OpEvent, Operation, Phase};
use crate::system;

#[derive(Debug, Clone, Serialize)]
pub struct StatusReport {
    pub state: String,
    pub profile: Option<String>,
    pub endpoint: String,
    pub container_running: bool,
    pub uptime_seconds: Option<u64>,
    pub gpu: Option<GpuSnapshot>,
}

#[derive(Debug, Clone, Serialize)]
pub struct GpuSnapshot {
    pub name: String,
    pub driver_version: String,
    pub vram_used_mib: u64,
    pub vram_total_mib: u64,
    pub compute_capability: String,
}

pub struct StatusOp {
    pub settings: Settings,
}

impl StatusOp {
    pub fn new(settings: Settings) -> Self {
        Self { settings }
    }

    pub fn run(self, sink: &Sender<OpEvent>) -> Result<StatusReport> {
        let _ = emit(sink, OpEvent::Phase(Phase::Init));
        let payload = system::state_payload(&self.settings);
        let state = payload
            .get("state")
            .and_then(|v| v.as_str())
            .unwrap_or(crate::state::IDLE)
            .to_string();
        let profile = payload.get("profile").and_then(|v| v.as_str()).map(str::to_string);
        let endpoint = payload
            .get("endpoint")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .unwrap_or_else(|| self.settings.endpoint());
        let container_running = payload
            .get("containerRunning")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        let uptime_seconds = payload.get("uptimeSeconds").and_then(|v| v.as_u64());
        let gpu = payload
            .get("gpu")
            .and_then(|v| v.as_object())
            .and_then(|obj| {
                Some(GpuSnapshot {
                    name: obj.get("name")?.as_str()?.to_string(),
                    driver_version: obj.get("driverVersion")?.as_str()?.to_string(),
                    vram_used_mib: obj.get("vramUsedMiB")?.as_u64()?,
                    vram_total_mib: obj.get("vramTotalMiB")?.as_u64()?,
                    compute_capability: obj.get("computeCapability")?.as_str()?.to_string(),
                })
            });
        let report = StatusReport {
            state,
            profile,
            endpoint,
            container_running,
            uptime_seconds,
            gpu,
        };
        let _ = sink.send(OpEvent::Done {
            summary: format!("Estado: {}", report.state),
        });
        let _ = emit(
            sink,
            OpEvent::Phase(Phase::Done {
                summary: format!(
                    "Estado: {} · endpoint: {}",
                    report.state, report.endpoint
                ),
            }),
        );
        Ok(report)
    }
}

impl Operation for StatusOp {
    fn describe(&self) -> String {
        "status".into()
    }
}