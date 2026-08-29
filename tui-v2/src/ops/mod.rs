//! Operaciones de control expuestas en la TUI.
//!
//! Cada función devuelve un `Operation` que la TUI puede ejecutar en un
//! hilo de fondo mientras muestra al usuario un overlay con spinner y el
//! log en vivo del subproceso. La semántica replica `command_*` de la CLI.

pub mod doctor;
pub mod health;
pub mod logs;
pub mod profiles;
pub mod start;
pub mod status;
pub mod stop;
pub mod switch;

use serde::Serialize;

use crate::compose::StreamChunk;

/// Pasos que la TUI puede mostrar durante una operación.
#[derive(Debug, Clone, Serialize)]
#[allow(dead_code)]
pub enum Phase {
    Init,
    Building { service: String },
    WaitingHealth { endpoint: String },
    Stopping { container: String },
    WaitingVram { baseline_mib: u64, current_mib: u64 },
    Done { summary: String },
    Failed { summary: String },
    Info { summary: String },
}

#[derive(Debug, Clone, Serialize)]
#[allow(dead_code)]
pub enum OpEvent {
    Phase(Phase),
    Stream(StreamChunk),
    Done { summary: String },
    Failed { summary: String },
}

/// Contrato común de toda operación que la TUI ejecuta.
#[allow(dead_code)]
pub trait Operation: Send {
    fn describe(&self) -> String;
    fn cancel(&mut self) {}
}

/// Resultado inmutable de una operación, mostrado en el dashboard cuando
/// termina.
#[derive(Debug, Clone, Serialize)]
#[allow(dead_code)]
pub struct OpResult {
    pub summary: String,
    pub ok: bool,
    pub elapsed: Duration,
}

use std::time::Duration;

/// Alias para eventos de operación.
pub type OpEventSink = std::sync::mpsc::Sender<OpEvent>;

/// Helper para que las operaciones envíen eventos sin propagar errores.
pub fn emit(sink: &OpEventSink, event: OpEvent) -> color_eyre::Result<()> {
    let _ = sink.send(event);
    Ok(())
}