//! Comando `health` — sondea `/health` del endpoint local.

use std::sync::mpsc::Sender;
use std::time::Duration;

use color_eyre::Result;
use color_eyre::eyre::eyre;

use crate::config::Settings;
use crate::ops::{emit, OpEvent, Operation, Phase};
use crate::system::{self, HttpResponse};

pub struct HealthOp {
    pub settings: Settings,
}

#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct HealthReport {
    pub ok: bool,
    pub status_code: u16,
    pub body: serde_json::Value,
    pub endpoint: String,
}

impl HealthOp {
    pub fn new(settings: Settings) -> Self {
        Self { settings }
    }

    pub fn run(self, sink: &Sender<OpEvent>) -> Result<HealthReport> {
        let _ = emit(sink, OpEvent::Phase(Phase::Init));
        let url = format!("http://{}:{}/health", self.settings.host, self.settings.port);
        let result = system::http_json(&url, &self.settings.api_key, Duration::from_secs(5));
        let report = match result {
            Ok(HttpResponse { status, body }) => {
                let ok = status == 200;
                HealthReport { ok, status_code: status, body, endpoint: self.settings.endpoint() }
            }
            Err(e) => {
                let _ = sink.send(OpEvent::Failed {
                    summary: format!("Endpoint no disponible: {e}"),
                });
                let _ = emit(
                    sink,
                    OpEvent::Phase(Phase::Failed {
                        summary: format!("Endpoint no disponible: {e}"),
                    }),
                );
                return Err(eyre!("Servidor no saludable"));
            }
        };
        let _ = sink.send(OpEvent::Done {
            summary: if report.ok {
                format!("OK: HTTP {}: {}", report.status_code, report.body)
            } else {
                format!("ERROR: HTTP {}: {}", report.status_code, report.body)
            },
        });
        let _ = emit(
            sink,
            OpEvent::Phase(if report.ok {
                Phase::Done {
                    summary: format!("OK: HTTP {}", report.status_code),
                }
            } else {
                Phase::Failed {
                    summary: format!("ERROR: HTTP {}", report.status_code),
                }
            }),
        );
        if !report.ok {
            return Err(eyre!("Servidor no saludable"));
        }
        Ok(report)
    }
}

impl Operation for HealthOp {
    fn describe(&self) -> String {
        "health".into()
    }
}