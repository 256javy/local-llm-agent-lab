//! Estado de la aplicación y bucle de eventos.
//!
//! Coordina el render con las operaciones en background. Cada operación se
//! ejecuta en su propio hilo, enviando `OpEvent` por un canal que la TUI
//! consume en su tick principal. Los eventos `Stream` alimentan el log del
//! panel derecho; los eventos `Phase` actualizan el estado mostrado.

use std::sync::mpsc::{self, Receiver, Sender};
use std::time::{Duration, Instant};

use color_eyre::Result;
use crossterm::event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers};
use ratatui::DefaultTerminal;

use crate::compose::StreamChunk;
use crate::config::Settings;
use crate::ops::status::{StatusOp, StatusReport};
use crate::ops::{OpEvent, Phase};
use crate::profiles::Profile;
use crate::system;
use crate::ui::footer::Mode as FooterMode;
use crate::ui::overlay::{OverlayKind, OverlayView};

const DEFAULT_LOG_TAIL: u32 = 200;
const MAX_LOG_TAIL: u32 = 100_000;

pub struct App {
    pub settings: Settings,
    pub theme: crate::ui::theme::Theme,
    pub version: &'static str,
    pub profiles: Vec<Profile>,
    pub selected: usize,
    pub status: StatusReport,
    pub last_event: Option<String>,
    pub mode: Mode,
    pub confirm: Option<ConfirmKind>,
    pub tail_prompt: Option<TailPrompt>,
    pub running_op: Option<RunningOp>,
    pub finished_op: Option<FinishedOp>,
    pub help_visible: bool,
    pub spinner_frame: usize,
    pub op_started: Option<Instant>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Dashboard,
    Operation,
    TailPrompt,
}

#[derive(Debug, Clone)]
pub struct TailPrompt {
    pub input: String,
    pub follow: bool,
}

pub struct RunningOp {
    pub title: String,
    pub rx: Receiver<OpEvent>,
    pub log: Vec<String>,
    pub phase: Option<Phase>,
    pub elapsed_secs: u64,
    pub persistent: bool,
}

pub struct FinishedOp {
    pub title: String,
    pub log: Vec<String>,
    pub phase: Option<Phase>,
    pub elapsed_secs: u64,
    pub ok: bool,
    pub persistent: bool,
}

#[derive(Debug, Clone)]
pub enum ConfirmKind {
    Stop { profile_id: Option<String> },
    Switch { target_id: String },
    Start { target_id: String },
}

impl App {
    pub fn new(settings: Settings, version: &'static str) -> Result<Self> {
        let profiles = crate::profiles::load(&settings)?;
        let profiles: Vec<Profile> = profiles.into_values().collect();
        let status = StatusOp::new(settings.clone()).run(&dummy_sink())?;
        let selected = profiles
            .iter()
            .position(|p| p.id == settings.default_profile)
            .unwrap_or(0);
        Ok(Self {
            settings,
            theme: Default::default(),
            version,
            profiles,
            selected,
            status,
            last_event: None,
            mode: Mode::Dashboard,
            confirm: None,
            tail_prompt: None,
            running_op: None,
            finished_op: None,
            help_visible: false,
            spinner_frame: 0,
            op_started: None,
        })
    }

    pub fn selected_profile(&self) -> Option<&Profile> {
        self.profiles.get(self.selected)
    }

    pub fn run(mut self, mut terminal: DefaultTerminal) -> Result<()> {
        let tick = Duration::from_millis(150);
        loop {
            self.tick();
            self.drain_op_events();
            self.draw(&mut terminal)?;
            self.refresh_if_needed();
            if event::poll(tick)? {
                if let Event::Key(key) = event::read()? {
                    if key.kind != KeyEventKind::Press {
                        continue;
                    }
                    if self.handle_key(key)? {
                        return Ok(());
                    }
                }
            } else {
                self.spinner_frame = self.spinner_frame.wrapping_add(1);
            }
        }
    }

    fn tick(&mut self) {
        if let Some(start) = self.op_started {
            if let Some(op) = self.running_op.as_mut() {
                op.elapsed_secs = start.elapsed().as_secs();
            }
        }
    }

    fn drain_op_events(&mut self) {
        let Some(op) = self.running_op.as_mut() else {
            return;
        };
        while let Ok(event) = op.rx.try_recv() {
            match event {
                OpEvent::Stream(chunk) => {
                    let StreamChunk { channel, line } = chunk;
                    let prefix = match channel {
                        crate::compose::StreamChannel::Stderr => "• ",
                        crate::compose::StreamChannel::Stdout => "  ",
                    };
                    let line = format!("{prefix}{line}");
                    op.log.push(line);
                    if op.log.len() > DEFAULT_LOG_TAIL as usize {
                        let drop = op.log.len() - DEFAULT_LOG_TAIL as usize;
                        op.log.drain(0..drop);
                    }
                }
                OpEvent::Phase(phase) => op.phase = Some(phase),
                OpEvent::Done { summary } => {
                    self.last_event = Some(summary);
                    self.finish_op(true);
                    return;
                }
                OpEvent::Failed { summary } => {
                    self.last_event = Some(summary);
                    self.finish_op(false);
                    return;
                }
            }
        }
    }

    fn refresh_if_needed(&mut self) {
        if self.running_op.is_some() {
            return;
        }
        if let Err(e) = self.refresh_status_now() {
            self.last_event = Some(format!("Error refrescando estado: {e}"));
        }
    }

    pub fn refresh_status_now(&mut self) -> Result<()> {
        let sink = dummy_sink();
        let report = StatusOp::new(self.settings.clone()).run(&sink)?;
        self.status = report;
        Ok(())
    }

    fn finish_op(&mut self, ok: bool) {
        self.drain_remaining_phase();
        let snapshot = self.running_op.take().map(|op| FinishedOp {
            title: op.title,
            log: op.log,
            phase: op.phase,
            elapsed_secs: op.elapsed_secs,
            persistent: op.persistent,
            ok,
        });
        self.op_started = None;
        self.mode = Mode::Dashboard;
        match snapshot {
            Some(finished) if finished.persistent => {
                self.finished_op = Some(finished);
            }
            _ => {
                self.finished_op = None;
                if let Err(e) = self.refresh_status_now() {
                    self.last_event = Some(format!("Error refrescando estado: {e}"));
                }
            }
        }
    }

    fn drain_remaining_phase(&mut self) {
        let Some(op) = self.running_op.as_mut() else {
            return;
        };
        while let Ok(event) = op.rx.try_recv() {
            if let OpEvent::Phase(phase) = event {
                op.phase = Some(phase);
            }
        }
    }

    fn handle_key(&mut self, key: KeyEvent) -> Result<bool> {
        if self.help_visible {
            if matches!(key.code, KeyCode::Esc | KeyCode::Char('?') | KeyCode::Char('q')) {
                self.help_visible = false;
            }
            return Ok(false);
        }
        if self.tail_prompt.is_some() {
            return self.handle_tail_prompt_key(key);
        }
        if self.finished_op.is_some() {
            return self.handle_finished_key(key);
        }
        if self.confirm.is_some() {
            return self.handle_confirm_key(key);
        }
        if self.running_op.is_some() {
            return self.handle_op_key(key);
        }
        match key.code {
            KeyCode::Char('q') => return Ok(true),
            KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => return Ok(true),
            KeyCode::Char('?') | KeyCode::F(1) => self.help_visible = !self.help_visible,
            KeyCode::Char('r') => self.refresh_status_now()?,
            KeyCode::Char('p') => self.reload_profiles()?,
            KeyCode::Char('h') => self.start_health(),
            KeyCode::Char('l') => self.start_logs(false, DEFAULT_LOG_TAIL),
            KeyCode::Char('L') => self.start_logs(true, DEFAULT_LOG_TAIL),
            KeyCode::Char('t') => self.open_tail_prompt(false),
            KeyCode::Char('T') => self.open_tail_prompt(true),
            KeyCode::Char('d') => self.mark_default()?,
            KeyCode::Char('D') => self.start_doctor(),
            KeyCode::Char('x') => self.confirm_stop(),
            KeyCode::Char('s') => self.confirm_switch(),
            KeyCode::Up => self.move_selection(-1),
            KeyCode::Down => self.move_selection(1),
            KeyCode::Enter => self.confirm_start(),
            _ => {}
        }
        Ok(false)
    }

    fn handle_tail_prompt_key(&mut self, key: KeyEvent) -> Result<bool> {
        match key.code {
            KeyCode::Esc => {
                self.tail_prompt = None;
                self.mode = Mode::Dashboard;
            }
            KeyCode::Char('q') => {
                self.tail_prompt = None;
                self.mode = Mode::Dashboard;
                return Ok(true);
            }
            KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                self.tail_prompt = None;
                self.mode = Mode::Dashboard;
                return Ok(true);
            }
            KeyCode::Enter => {
                let prompt = self.tail_prompt.take().unwrap_or(TailPrompt {
                    input: DEFAULT_LOG_TAIL.to_string(),
                    follow: false,
                });
                self.mode = Mode::Dashboard;
                let tail = prompt.input.trim().parse::<u32>().unwrap_or(DEFAULT_LOG_TAIL);
                let tail = tail.clamp(1, MAX_LOG_TAIL);
                self.start_logs(prompt.follow, tail);
            }
            KeyCode::Backspace => {
                if let Some(prompt) = self.tail_prompt.as_mut() {
                    prompt.input.pop();
                }
            }
            KeyCode::Char(c) if c.is_ascii_digit() => {
                if let Some(prompt) = self.tail_prompt.as_mut() {
                    if prompt.input.len() < 6 {
                        prompt.input.push(c);
                    }
                }
            }
            _ => {}
        }
        Ok(false)
    }

    fn open_tail_prompt(&mut self, follow: bool) {
        self.tail_prompt = Some(TailPrompt {
            input: DEFAULT_LOG_TAIL.to_string(),
            follow,
        });
        self.mode = Mode::TailPrompt;
    }

    fn handle_confirm_key(&mut self, key: KeyEvent) -> Result<bool> {
        let confirm = self.confirm.clone();
        match key.code {
            KeyCode::Enter => {
                self.confirm = None;
                match confirm {
                    Some(ConfirmKind::Start { target_id }) => self.start_profile(&target_id)?,
                    Some(ConfirmKind::Stop { profile_id }) => self.stop_profile(profile_id.as_deref())?,
                    Some(ConfirmKind::Switch { target_id }) => self.switch_profile(&target_id)?,
                    None => {}
                }
            }
            KeyCode::Esc => self.confirm = None,
            _ => {}
        }
        Ok(false)
    }

    fn handle_op_key(&mut self, key: KeyEvent) -> Result<bool> {
        match key.code {
            KeyCode::Esc => {
                self.running_op = None;
                self.op_started = None;
                self.last_event = Some("Operación cancelada (subproceso aún en curso)".into());
                self.mode = Mode::Dashboard;
            }
            KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                self.running_op = None;
                self.op_started = None;
                self.last_event = Some("Operación cancelada (Ctrl+C)".into());
                self.mode = Mode::Dashboard;
            }
            _ => {}
        }
        Ok(false)
    }

    fn handle_finished_key(&mut self, key: KeyEvent) -> Result<bool> {
        match key.code {
            KeyCode::Char('q') => return Ok(true),
            KeyCode::Esc | KeyCode::Enter | KeyCode::Char('p') => {
                self.finished_op = None;
                if let Err(e) = self.refresh_status_now() {
                    self.last_event = Some(format!("Error refrescando estado: {e}"));
                }
            }
            _ => {}
        }
        Ok(false)
    }

    fn move_selection(&mut self, delta: i32) {
        if self.profiles.is_empty() {
            return;
        }
        let len = self.profiles.len() as i32;
        let current = self.selected as i32;
        let next = (current + delta).rem_euclid(len);
        self.selected = next as usize;
    }

    fn confirm_start(&mut self) {
        let Some(profile) = self.selected_profile().cloned() else {
            self.last_event = Some("No hay perfil seleccionado".into());
            return;
        };
        if Some(&profile.id) == self.status.profile.as_ref() {
            self.last_event = Some(format!("El perfil {} ya está activo", profile.id));
            return;
        }
        self.confirm = Some(ConfirmKind::Start { target_id: profile.id });
    }

    fn confirm_switch(&mut self) {
        let Some(profile) = self.selected_profile().cloned() else {
            self.last_event = Some("No hay perfil seleccionado".into());
            return;
        };
        if Some(profile.id.as_str()) == self.status.profile.as_deref() {
            self.last_event = Some(format!("El perfil {} ya está activo", profile.id));
            return;
        }
        self.confirm = Some(ConfirmKind::Switch { target_id: profile.id });
    }

    fn confirm_stop(&mut self) {
        if !system::docker_container_running() && self.status.profile.is_none() {
            self.last_event = Some("No hay un contenedor administrado en ejecución".into());
            return;
        }
        self.confirm = Some(ConfirmKind::Stop { profile_id: self.status.profile.clone() });
    }

    fn mark_default(&mut self) -> Result<()> {
        let Some(profile) = self.selected_profile().cloned() else {
            return Ok(());
        };
        if self.settings.default_profile == profile.id {
            self.last_event = Some(format!("{} ya es el perfil predeterminado", profile.id));
            return Ok(());
        }
        let env_path = self.settings.repo_dir.join(".env");
        update_env_default(&env_path, &profile.id)?;
        self.settings.default_profile = profile.id.clone();
        self.last_event = Some(format!("Perfil predeterminado: {}", profile.id));
        Ok(())
    }

    fn reload_profiles(&mut self) -> Result<()> {
        let list = crate::profiles::load(&self.settings)?;
        self.profiles = list.into_values().collect();
        if self.selected >= self.profiles.len() {
            self.selected = 0;
        }
        self.last_event = Some(format!("{} perfiles cargados", self.profiles.len()));
        Ok(())
    }

    fn start_profile(&mut self, id: &str) -> Result<()> {
        let profile = crate::profiles::get(&self.settings, id)?;
        let settings = self.settings.clone();
        let title = format!("start {id}");
        self.launch_op(title, false, move |sink| {
            crate::ops::start::StartOp::new(settings, profile).run(&sink)?;
            Ok(())
        })
    }

    fn switch_profile(&mut self, id: &str) -> Result<()> {
        let target = crate::profiles::get(&self.settings, id)?;
        let settings = self.settings.clone();
        let title = format!("switch {id}");
        self.launch_op(title, false, move |sink| {
            crate::ops::switch::SwitchOp::new(settings, target).run(&sink)?;
            Ok(())
        })
    }

    fn stop_profile(&mut self, id: Option<&str>) -> Result<()> {
        let profile = match id {
            Some(pid) => crate::profiles::get(&self.settings, pid).ok(),
            None => None,
        };
        let settings = self.settings.clone();
        let title = "stop".into();
        self.launch_op(title, false, move |sink| {
            crate::ops::stop::StopOp::new(settings, profile).run(&sink)?;
            Ok(())
        })
    }

    fn start_health(&mut self) {
        let settings = self.settings.clone();
        if let Err(e) = self.launch_op("health".into(), true, move |sink| {
            crate::ops::health::HealthOp::new(settings).run(&sink)?;
            Ok(())
        }) {
            self.last_event = Some(format!("No se pudo iniciar health: {e}"));
        }
    }

    fn start_doctor(&mut self) {
        let settings = self.settings.clone();
        if let Err(e) = self.launch_op("doctor".into(), true, move |sink| {
            crate::ops::doctor::DoctorOp::new(settings).run(&sink)?;
            Ok(())
        }) {
            self.last_event = Some(format!("No se pudo iniciar doctor: {e}"));
        }
    }

    fn start_logs(&mut self, follow: bool, tail: u32) {
        let settings = self.settings.clone();
        let (tx, rx) = mpsc::channel();
        let title = if follow {
            format!("logs · follow · tail {tail}")
        } else {
            format!("logs · tail {tail}")
        };
        self.running_op = Some(RunningOp {
            title,
            rx,
            log: Vec::new(),
            phase: Some(Phase::Init),
            elapsed_secs: 0,
            persistent: true,
        });
        self.op_started = Some(Instant::now());
        self.mode = Mode::Operation;
        std::thread::spawn(move || {
            let _ = crate::ops::logs::LogsOp::new(settings, tail, follow, tx).run();
        });
    }

    fn launch_op<F>(&mut self, title: String, persistent: bool, op: F) -> Result<()>
    where
        F: FnOnce(Sender<OpEvent>) -> Result<()> + Send + 'static,
    {
        let (tx, rx) = mpsc::channel();
        self.running_op = Some(RunningOp {
            title,
            rx,
            log: Vec::new(),
            phase: Some(Phase::Init),
            elapsed_secs: 0,
            persistent,
        });
        self.op_started = Some(Instant::now());
        self.mode = Mode::Operation;
        std::thread::spawn(move || {
            let _ = op(tx);
        });
        Ok(())
    }

    fn draw(&self, terminal: &mut DefaultTerminal) -> Result<()> {
        let footer_mode = match self.mode {
            Mode::Dashboard if self.help_visible => FooterMode::Help,
            Mode::Dashboard => FooterMode::Dashboard,
            Mode::Operation => FooterMode::Operation,
            Mode::TailPrompt => FooterMode::TailPrompt,
        };
        let last_event = self.last_event.as_deref();
        let version = self.version;
        let theme = &self.theme;
        let settings = &self.settings;
        let status = &self.status;
        let profiles = &self.profiles;
        let selected = self.selected;
        let data_dir = settings.data_dir.display().to_string();
        let default_profile = settings.default_profile.as_str();
        let running_op = self.running_op.as_ref();
        let help_visible = self.help_visible;
        let confirm = self.confirm.as_ref();
        let spinner_frame = self.spinner_frame;
        terminal.draw(|frame| {
            use ratatui::layout::{Constraint, Direction, Layout};
            let area = frame.area();
            let header_height = crate::ui::header::preferred_height(area);
            let chunks = Layout::default()
                .direction(Direction::Vertical)
                .constraints([
                    Constraint::Length(header_height),
                    Constraint::Min(8),
                    Constraint::Length(footer_height(self.mode, self.help_visible)),
                ])
                .split(area);
            crate::ui::header::draw(
                frame,
                chunks[0],
                theme,
                version,
                &status.state,
                &settings.endpoint(),
                status.profile.as_deref(),
            );
            let right_panel = if let Some(op) = running_op {
                crate::ui::dashboard::RightPanel::Operation(OverlayView {
                    title: &op.title,
                    phase: op.phase.as_ref(),
                    log_lines: &op.log,
                    frame_idx: spinner_frame,
                    elapsed_secs: op.elapsed_secs,
                    kind: OverlayKind::Running,
                })
            } else if let Some(finished) = &self.finished_op {
                crate::ui::dashboard::RightPanel::Operation(OverlayView {
                    title: &finished.title,
                    phase: finished.phase.as_ref(),
                    log_lines: &finished.log,
                    frame_idx: spinner_frame,
                    elapsed_secs: finished.elapsed_secs,
                    kind: OverlayKind::Finished { ok: finished.ok },
                })
            } else {
                crate::ui::dashboard::RightPanel::Profiles
            };
            let dash_view = crate::ui::dashboard::DashboardView {
                status,
                profiles,
                selected,
                data_dir: &data_dir,
                default_profile,
                last_event,
                right_panel,
            };
            crate::ui::dashboard::draw(frame, chunks[1], theme, &dash_view);
            crate::ui::footer::draw(frame, chunks[2], theme, footer_mode);
            if help_visible {
                crate::ui::help::draw(frame, area, theme);
            }
            if let Some(prompt) = &self.tail_prompt {
                let title = if prompt.follow {
                    "Logs · follow · número de líneas"
                } else {
                    "Logs · número de líneas"
                };
                let description = format!(
                    "Cantidad de líneas a mostrar del contenedor. Por defecto {}; máximo {}. Sin follow se cierra al agotar el buffer.",
                    DEFAULT_LOG_TAIL, MAX_LOG_TAIL
                );
                crate::ui::input::draw(frame, area, theme, title, &description, &prompt.input);
            }
            if let Some(kind) = confirm {
                let (title, message) = match kind {
                    ConfirmKind::Start { target_id } => (
                        "Confirmar inicio",
                        format!(
                            "Vas a iniciar {target_id}. Esto descargará el runtime si no está cacheado y arrancará el contenedor.",
                        ),
                    ),
                    ConfirmKind::Switch { target_id } => (
                        "Confirmar switch",
                        format!(
                            "Vas a cambiar a {target_id}. El perfil activo se apagará y se liberará la VRAM antes de levantar el nuevo.",
                        ),
                    ),
                    ConfirmKind::Stop { profile_id } => (
                        "Confirmar stop del contenedor",
                        format!(
                            "Vas a detener el contenedor administrado{}. El perfil, los modelos y caches en disco se conservan; la VRAM se libera antes de cerrar.",
                            profile_id
                                .as_deref()
                                .map(|p| format!(" {p}"))
                                .unwrap_or_default(),
                        ),
                    ),
                };
                crate::ui::confirm::draw(frame, area, theme, title, &message);
            }
        })?;
        Ok(())
    }
}

fn footer_height(mode: Mode, help_visible: bool) -> u16 {
    if help_visible {
        return 2;
    }
    match mode {
        Mode::Dashboard => 3,
        Mode::TailPrompt => 2,
        _ => 2,
    }
}

pub fn dummy_sink() -> Sender<OpEvent> {
    let (tx, _rx) = mpsc::channel();
    tx
}

fn update_env_default(path: &std::path::Path, value: &str) -> Result<()> {
    let mut lines: Vec<String> = if path.exists() {
        std::fs::read_to_string(path)?
            .lines()
            .map(str::to_string)
            .collect()
    } else {
        Vec::new()
    };
    let new_line = format!("LLM_LAB_DEFAULT_PROFILE={value}");
    let mut found = false;
    for line in lines.iter_mut() {
        if line.starts_with("LLM_LAB_DEFAULT_PROFILE=") {
            *line = new_line.clone();
            found = true;
        }
    }
    if !found {
        lines.push(new_line);
    }
    let mut joined = lines.join("\n");
    if !joined.ends_with('\n') {
        joined.push('\n');
    }
    std::fs::write(path, joined)?;
    Ok(())
}
