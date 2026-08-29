//! Estado persistente y cerrojo de control.
//!
//! Equivalente a `read_state`, `write_state`, `clear_state` y `control_lock`
//! de la CLI. Mantiene compatibilidad JSON con `state.json` para que la TUI
//! y la CLI puedan alternar sin corromper el archivo.

use std::fs::{self, File, OpenOptions};
use std::io::Write;

use color_eyre::Result;
use color_eyre::eyre::eyre;
use fd_lock::{RwLock, RwLockWriteGuard};
use serde_json::{json, Value};

use crate::config::Settings;

pub const HEALTHY: &str = "healthy";
pub const STARTING: &str = "starting";
pub const FAILED: &str = "failed";
pub const IDLE: &str = "idle";
pub const STALE: &str = "stale";
pub const UNKNOWN: &str = "unknown";

pub fn read(settings: &Settings) -> Option<Value> {
    let path = settings.state_file();
    if !path.exists() {
        return None;
    }
    let Ok(content) = fs::read_to_string(&path) else {
        return Some(json!({ "state": UNKNOWN, "reason": "state-file-invalid" }));
    };
    serde_json::from_str(&content).ok()
}

pub fn write(settings: &Settings, value: &Value) -> Result<()> {
    let dir = settings.state_dir();
    fs::create_dir_all(&dir)?;
    let final_path = settings.state_file();
    let tmp = final_path.with_extension("tmp");
    let serialized = serde_json::to_string_pretty(value)?;
    {
        let mut file = File::create(&tmp)?;
        file.write_all(serialized.as_bytes())?;
        file.write_all(b"\n")?;
        file.sync_all()?;
    }
    fs::rename(&tmp, &final_path)?;
    Ok(())
}

pub fn clear(settings: &Settings) -> Result<()> {
    let path = settings.state_file();
    if path.exists() {
        fs::remove_file(&path)?;
    }
    Ok(())
}

/// Cerrojo exclusivo de control.
///
/// Conserva el `RwLockWriteGuard` (que libera el flock en `Drop`) y la
/// referencia al `RwLock` para garantizar que el archivo subyacente no
/// se cierre prematuramente. El lock se leakea a `'static` para desligar
/// su vida del RwLock y poder almacenarlo en una struct auto-referencial.
pub struct ControlLock {
    _guard: RwLockWriteGuard<'static, File>,
    _lock: Box<RwLock<File>>,
}

impl ControlLock {
    pub fn acquire(settings: &Settings) -> Result<Self> {
        let dir = settings.state_dir();
        fs::create_dir_all(&dir)?;
        let path = settings.lock_file();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .append(true)
            .open(&path)?;
        let mut lock: Box<RwLock<File>> = Box::new(RwLock::new(file));
        // Tomamos el guard antes de mover el `Box` para asegurarnos de que
        // el RwLock viva mientras el guard esté vivo. Luego reconstruimos
        // la referencia estática por reborrow.
        let guard: RwLockWriteGuard<'_, File> = lock
            .try_write()
            .map_err(|e| eyre!("Otra operación de control está en curso ({})", e))?;
        // SAFETY: el RwLock vive dentro de `Box<RwLock<File>>` propiedad de
        // la struct, así que no se moverá mientras el guard esté vivo. Como
        // Rust no puede probar el aliasing a través de self-referential
        // structs, lo aseguramos manualmente.
        let guard_static: RwLockWriteGuard<'static, File> =
            unsafe { std::mem::transmute(guard) };
        Ok(Self {
            _guard: guard_static,
            _lock: lock,
        })
    }
}