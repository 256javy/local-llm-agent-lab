//! Composición de comandos Docker y entorno para `docker compose`.
//!
//! Equivalente a `compose_command`, `compose_env` y `run` de `llm_lab.core`.
//! Mantiene el mismo contrato: las imágenes se construyen con el tag
//! `local/<perfil>` y el proyecto compose es `local-llm-agent-lab`.

#![allow(dead_code)]

use std::collections::HashMap;
use std::ffi::OsString;
use std::io::{BufRead, BufReader, Read};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::thread;

use color_eyre::Result;
use color_eyre::eyre::{Context, ContextCompat};
use serde_json::Value;

use crate::config::{project_name, server_service, Settings};
use crate::profiles::Profile;

pub fn compose_command(settings: &Settings, args: &[&str]) -> Vec<String> {
    let mut cmd = vec![
        "docker".to_string(),
        "compose".to_string(),
        "-p".to_string(),
        project_name().to_string(),
        "-f".to_string(),
        settings.compose_file().to_string_lossy().to_string(),
    ];
    cmd.extend(args.iter().map(|s| s.to_string()));
    cmd
}

pub fn compose_env(settings: &Settings, profile: &Profile) -> HashMap<String, String> {
    let mut env: HashMap<String, String> = std::env::vars().collect();
    let cmake_args = profile.runtime.cmake_args.join(" ");
    env.insert("LLM_LAB_HOST".into(), settings.host.clone());
    env.insert("LLM_LAB_PORT".into(), settings.port.to_string());
    env.insert("LLM_LAB_DATA_DIR".into(), settings.data_dir.to_string_lossy().to_string());
    env.insert("LLM_LAB_PROFILE_FILE".into(), profile.path.to_string_lossy().to_string());
    env.insert("LLM_LAB_RUNTIME_REPOSITORY".into(), profile.runtime.repository.clone());
    env.insert("LLM_LAB_RUNTIME_REVISION".into(), profile.runtime.revision.clone());
    env.insert("LLM_LAB_RUNTIME_CMAKE_ARGS".into(), cmake_args);
    env.insert("LLM_LAB_RUNTIME_IMAGE".into(), format!("local/local-llm-agent-lab:{}", profile.id));
    env.insert("LLM_LAB_API_KEY".into(), settings.api_key.clone());
    env
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StreamChannel {
    Stdout,
    Stderr,
}

/// Resultado de un subproceso, con la posibilidad de leer sus streams en vivo.
pub struct Subprocess {
    child: Option<Child>,
    pub stdout: Option<Receiver<StreamChunk>>,
    pub stderr: Option<Receiver<StreamChunk>>,
    pub args: Vec<String>,
}

pub struct StreamChunk {
    pub channel: StreamChannel,
    pub line: String,
}

impl std::fmt::Debug for StreamChunk {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("StreamChunk")
            .field("channel", &self.channel)
            .field("line", &self.line)
            .finish()
    }
}

impl Clone for StreamChunk {
    fn clone(&self) -> Self {
        Self {
            channel: self.channel,
            line: self.line.clone(),
        }
    }
}

impl serde::Serialize for StreamChunk {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeStruct;
        let mut s = serializer.serialize_struct("StreamChunk", 2)?;
        s.serialize_field("channel", match self.channel {
            StreamChannel::Stdout => "stdout",
            StreamChannel::Stderr => "stderr",
        })?;
        s.serialize_field("line", &self.line)?;
        s.end()
    }
}

impl Subprocess {
    pub fn wait(&mut self) -> Result<i32> {
        let child = self.child.as_mut().context("subproceso ya finalizado")?;
        let status = child.wait()?;
        Ok(status.code().unwrap_or(-1))
    }

    pub fn wait_with_output(&mut self) -> Result<CommandOutput> {
        let child = self.child.as_mut().context("subproceso ya finalizado")?;
        let status = child.wait()?;
        let mut stdout = String::new();
        let mut stderr = String::new();
        if let Some(rx) = self.stdout.take() {
            for chunk in rx {
                if chunk.channel == StreamChannel::Stdout {
                    stdout.push_str(&chunk.line);
                    stdout.push('\n');
                }
            }
        }
        if let Some(rx) = self.stderr.take() {
            for chunk in rx {
                if chunk.channel == StreamChannel::Stderr {
                    stderr.push_str(&chunk.line);
                    stderr.push('\n');
                }
            }
        }
        Ok(CommandOutput { status: status.code().unwrap_or(-1), stdout, stderr })
    }
}

impl Drop for Subprocess {
    fn drop(&mut self) {
        if let Some(child) = self.child.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

pub struct CommandOutput {
    pub status: i32,
    pub stdout: String,
    pub stderr: String,
}

pub fn spawn(
    settings: &Settings,
    env: &HashMap<String, String>,
    args: &[&str],
    stream: bool,
) -> Result<Subprocess> {
    let args_vec = compose_command(settings, args);
    let mut cmd = Command::new(&args_vec[0]);
    cmd.args(&args_vec[1..])
        .current_dir(&settings.repo_dir)
        .stdin(Stdio::null());
    for (k, v) in env {
        cmd.env(OsString::from(k), OsString::from(v));
    }
    if stream {
        let (out_tx, out_rx) = mpsc::channel();
        let (err_tx, err_rx) = mpsc::channel();
        cmd.stdout(Stdio::piped()).stderr(Stdio::piped());
        let mut child = cmd.spawn().with_context(|| format!("no se pudo iniciar: {}", args_vec.join(" ")))?;
        if let Some(stdout) = child.stdout.take() {
            spawn_reader(BufReader::new(stdout), StreamChannel::Stdout, out_tx);
        }
        if let Some(stderr) = child.stderr.take() {
            spawn_reader(BufReader::new(stderr), StreamChannel::Stderr, err_tx);
        }
        Ok(Subprocess {
            child: Some(child),
            stdout: Some(out_rx),
            stderr: Some(err_rx),
            args: args_vec,
        })
    } else {
        cmd.stdout(Stdio::piped()).stderr(Stdio::piped());
        let mut child = cmd.spawn().with_context(|| format!("no se pudo iniciar: {}", args_vec.join(" ")))?;
        let _ = child.stdout.take();
        let _ = child.stderr.take();
        Ok(Subprocess {
            child: Some(child),
            stdout: None,
            stderr: None,
            args: args_vec,
        })
    }
}

fn spawn_reader<R: Read + Send + 'static>(
    reader: R,
    channel: StreamChannel,
    tx: mpsc::Sender<StreamChunk>,
) {
    thread::spawn(move || {
        let buf = BufReader::new(reader);
        for line in buf.lines().map_while(Result::ok) {
            if tx.send(StreamChunk { channel, line }).is_err() {
                break;
            }
        }
    });
}

/// Variante simplificada: ejecuta y devuelve el output acumulado.
pub fn run(
    settings: &Settings,
    env: &HashMap<String, String>,
    args: &[&str],
) -> Result<CommandOutput> {
    let mut proc = spawn(settings, env, args, false)?;
    proc.wait_with_output()
}

/// Ejecuta un comando arbitrario (no necesariamente `docker compose`) en el
/// directorio del repo, devolviendo su salida. Pensado para utilidades de
/// diagnóstico como `docker info` o `docker compose version --short`.
pub fn run_raw(
    settings: &Settings,
    env: &HashMap<String, String>,
    argv: &[&str],
) -> Result<CommandOutput> {
    if argv.is_empty() {
        return Err(color_eyre::eyre::eyre!("argv vacío"));
    }
    let mut cmd = Command::new(argv[0]);
    cmd.args(&argv[1..])
        .current_dir(&settings.repo_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (k, v) in env {
        cmd.env(OsString::from(k), OsString::from(v));
    }
    let output = cmd.output()?;
    Ok(CommandOutput {
        status: output.status.code().unwrap_or(-1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    })
}

pub fn run_streamed(
    settings: &Settings,
    env: &HashMap<String, String>,
    args: &[&str],
) -> Result<Subprocess> {
    spawn(settings, env, args, true)
}

pub fn run_inherit(
    settings: &Settings,
    env: &HashMap<String, String>,
    args: &[&str],
) -> Result<i32> {
    let mut proc = spawn(settings, env, args, false)?;
    proc.wait()
}

pub fn service_name() -> &'static str {
    server_service()
}

pub fn value_or_null(value: Option<Value>) -> Value {
    value.unwrap_or(Value::Null)
}