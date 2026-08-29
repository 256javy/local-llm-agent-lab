//! Primitivas de sistema: GPU, puertos, HTTP, docker y salud.
//!
//! Reimplementación de las funciones homónimas en `llm_lab.core` para que la
//! TUI no dependa de un subproceso Python externo.

use std::io::{Read, Write};
use std::net::TcpStream;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use color_eyre::Result;
use color_eyre::eyre::{eyre, Context, ContextCompat};
use serde::Deserialize;
use serde_json::Value;

use crate::config::{container_name, Settings};

#[derive(Debug, Clone, Deserialize)]
pub struct GpuInfo {
    pub name: String,
    pub driver_version: String,
    pub vram_used_mib: u64,
    pub vram_total_mib: u64,
    pub compute_capability: String,
}

pub fn gpu_info() -> Option<GpuInfo> {
    let path = which("nvidia-smi")?;
    let output = Command::new(path)
        .args([
            "--query-gpu=name,driver_version,memory.used,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        ])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let line = stdout.lines().next()?;
    let mut parts = line.splitn(5, ',');
    Some(GpuInfo {
        name: parts.next()?.trim().to_string(),
        driver_version: parts.next()?.trim().to_string(),
        vram_used_mib: parts.next()?.trim().parse().ok()?,
        vram_total_mib: parts.next()?.trim().parse().ok()?,
        compute_capability: parts.next()?.trim().to_string(),
    })
}

pub fn port_available(host: &str, port: u16) -> bool {
    TcpStream::connect((host, port)).is_err()
}

pub fn which(bin: &str) -> Option<String> {
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        let candidate = dir.join(bin);
        if candidate.is_file() {
            return Some(candidate.to_string_lossy().to_string());
        }
    }
    None
}

#[derive(Debug)]
pub struct HttpResponse {
    pub status: u16,
    pub body: Value,
}

pub fn http_json(url: &str, api_key: &str, timeout: Duration) -> Result<HttpResponse> {
    // Implementación mínima con stdlib: usa un CONNECT sobre TLS plano cuando
    // el endpoint es HTTPS. Mantenemos sólo HTTP simple en el MVP porque el
    // endpoint de lab es siempre loopback.
    let (host_port, path) = split_url(url)?;
    let (host, port) = split_host_port(&host_port)?;
    let mut stream = TcpStream::connect((host.as_str(), port))
        .with_context(|| format!("no se pudo conectar a {url}"))?;
    stream.set_read_timeout(Some(timeout))?;
    stream.set_write_timeout(Some(timeout))?;
    let mut request = format!(
        "GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nAccept: application/json\r\nConnection: close\r\n",
    );
    if !api_key.is_empty() {
        request.push_str(&format!("Authorization: Bearer {api_key}\r\n"));
    }
    request.push_str("\r\n");
    stream.write_all(request.as_bytes())?;
    let mut raw = String::new();
    stream.read_to_string(&mut raw)?;
    let mut iter = raw.splitn(2, "\r\n\r\n");
    let head = iter.next().context("respuesta HTTP vacía")?;
    let body = iter.next().unwrap_or("");
    let status_line = head.lines().next().context("encabezado HTTP ausente")?;
    let mut parts = status_line.split_whitespace();
    let _ = parts.next();
    let code: u16 = parts
        .next()
        .context("status HTTP inválido")?
        .parse()
        .context("status HTTP no numérico")?;
    let body = if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_str(body).unwrap_or(Value::String(body.to_string()))
    };
    Ok(HttpResponse { status: code, body })
}

fn split_url(url: &str) -> Result<(String, String)> {
    let stripped = url
        .strip_prefix("http://")
        .or_else(|| url.strip_prefix("https://"))
        .context("URL no soporta esquema")?;
    let (host_port, path) = stripped
        .split_once('/')
        .map(|(hp, p)| (hp.to_string(), format!("/{p}")))
        .unwrap_or_else(|| (stripped.to_string(), "/".to_string()));
    Ok((host_port, path))
}

fn split_host_port(host_port: &str) -> Result<(String, u16)> {
    if let Some((h, p)) = host_port.rsplit_once(':') {
        Ok((h.to_string(), p.parse().context("puerto inválido")?))
    } else {
        Ok((host_port.to_string(), 80))
    }
}

pub fn wait_for_health(settings: &Settings) -> Result<Value> {
    let url = format!("http://{}:{}/health", settings.host, settings.port);
    let deadline = Instant::now() + Duration::from_secs(settings.start_timeout);
    let mut last = "sin respuesta".to_string();
    while Instant::now() < deadline {
        match http_json(&url, &settings.api_key, Duration::from_secs(3)) {
            Ok(resp) if resp.status == 200 => {
                return Ok(if let Value::Object(_) = &resp.body {
                    resp.body
                } else {
                    Value::Object(serde_json::Map::from_iter([(
                        "status".to_string(),
                        Value::String("ok".to_string()),
                    )]))
                });
            }
            Ok(resp) => {
                last = format!("HTTP {}: {}", resp.status, resp.body);
            }
            Err(e) => {
                last = format!("{e}");
            }
        }
        std::thread::sleep(Duration::from_secs(2));
    }
    Err(eyre!("El servidor no quedó saludable: {last}"))
}

pub fn docker_container_running() -> bool {
    let Some(docker) = which("docker") else {
        return false;
    };
    let output = Command::new(docker)
        .args(["inspect", "-f", "{{.State.Running}}", container_name()])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output();
    match output {
        Ok(out) => out.status.success() && out.stdout.trim_ascii_end() == b"true",
        Err(_) => false,
    }
}

pub fn state_payload(settings: &Settings) -> Value {
    let state = crate::state::read(settings);
    let running = if which("docker").is_some() {
        docker_container_running()
    } else {
        false
    };
    let gpu = gpu_info().map(|g| {
        serde_json::json!({
            "name": g.name,
            "driverVersion": g.driver_version,
            "vramUsedMiB": g.vram_used_mib,
            "vramTotalMiB": g.vram_total_mib,
            "computeCapability": g.compute_capability,
        })
    });
    let Some(state) = state else {
        return serde_json::json!({
            "state": crate::state::IDLE,
            "endpoint": settings.endpoint(),
            "containerRunning": running,
            "gpu": gpu,
        });
    };
    let mut payload = state.clone();
    if let Value::Object(map) = &mut payload {
        map.insert("containerRunning".into(), Value::Bool(running));
        map.insert("gpu".into(), gpu.clone().unwrap_or(Value::Null));
        if let Some(started) = map.get("startedAt").and_then(|v| v.as_f64()) {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs_f64())
                .unwrap_or(started);
            map.insert("uptimeSeconds".into(), Value::Number((((now - started).max(0.0)) as u64).into()));
        }
        if map.get("state").and_then(|v| v.as_str()) == Some(crate::state::HEALTHY) && !running {
            map.insert("state".into(), Value::String(crate::state::STALE.to_string()));
        }
    }
    payload
}