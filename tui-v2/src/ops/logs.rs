//! Comando `logs` — muestra los logs del contenedor administrado.
//!
//! Esta operación no requiere lock porque sólo lee; sigue al `docker compose
//! logs` con `--tail N` y `--follow` opcional.

use std::io::Read;
use std::process::{Command, Stdio};
use std::sync::mpsc::Sender;

use color_eyre::Result;

use crate::compose;
use crate::config::Settings;
use crate::ops::{emit, OpEvent, Operation, Phase};

pub struct LogsOp {
    pub settings: Settings,
    pub tail: u32,
    pub follow: bool,
    pub sink: Sender<OpEvent>,
}

impl LogsOp {
    pub fn new(settings: Settings, tail: u32, follow: bool, sink: Sender<OpEvent>) -> Self {
        Self { settings, tail, follow, sink }
    }

    pub fn run(self) -> Result<()> {
        let _ = emit(&self.sink, OpEvent::Phase(Phase::Init));
        let args = compose::compose_command(&self.settings, &["logs", "--tail", &self.tail.to_string()]);
        let full_args: Vec<String> = if self.follow {
            let mut v = args;
            v.push("--follow".into());
            v.push(compose::service_name().into());
            v
        } else {
            let mut v = args;
            v.push(compose::service_name().into());
            v
        };
        let mut cmd = Command::new(&full_args[0]);
        cmd.args(&full_args[1..])
            .current_dir(&self.settings.repo_dir)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .stdin(Stdio::null());
        let mut child = cmd.spawn()?;
        let stdout = child.stdout.take().unwrap();
        let stderr = child.stderr.take().unwrap();
        let _ = emit(
            &self.sink,
            OpEvent::Phase(Phase::Streaming {
                tail: self.tail,
                follow: self.follow,
            }),
        );
        let (tx, rx) = std::sync::mpsc::channel::<crate::compose::StreamChunk>();
        forward(stdout, tx.clone(), crate::compose::StreamChannel::Stdout);
        forward(stderr, tx, crate::compose::StreamChannel::Stderr);
        let sink = self.sink.clone();
        std::thread::spawn(move || {
            for chunk in rx {
                let _ = sink.send(OpEvent::Stream(chunk));
            }
        });
        let status = child.wait()?;
        let ok = status.success();
        let summary = if ok {
            format!("Logs mostrados (tail={})", self.tail)
        } else {
            format!("`docker compose logs` salió con código {}", status.code().unwrap_or(-1))
        };
        let _ = self.sink.send(OpEvent::Done { summary: summary.clone() });
        let _ = emit(
            &self.sink,
            if ok {
                OpEvent::Phase(Phase::Done { summary })
            } else {
                OpEvent::Phase(Phase::Failed { summary })
            },
        );
        Ok(())
    }
}

fn forward<R: Read + Send + 'static>(
    reader: R,
    sink: Sender<crate::compose::StreamChunk>,
    channel: crate::compose::StreamChannel,
) {
    std::thread::spawn(move || {
        use std::io::{BufRead, BufReader};
        let buf = BufReader::new(reader);
        for line in buf.lines().map_while(Result::ok) {
            let _ = sink.send(crate::compose::StreamChunk { channel, line });
        }
    });
}

impl Operation for LogsOp {
    fn describe(&self) -> String {
        format!("logs --tail {}", self.tail)
    }
}