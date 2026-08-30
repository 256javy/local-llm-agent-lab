//! Comando `profiles` — lista perfiles disponibles.

#![allow(dead_code)]

use std::sync::mpsc::Sender;

use color_eyre::Result;

use crate::config::Settings;
use crate::ops::{emit, OpEvent, Operation, Phase};
use crate::profiles;

pub struct ProfilesOp {
    pub settings: Settings,
}

impl ProfilesOp {
    pub fn new(settings: Settings) -> Self {
        Self { settings }
    }

    pub fn run(self, sink: &Sender<OpEvent>) -> Result<Vec<profiles::Profile>> {
        let _ = emit(sink, OpEvent::Phase(Phase::Init));
        let list = profiles::load(&self.settings)?
            .into_values()
            .collect::<Vec<_>>();
        let _ = sink.send(OpEvent::Done {
            summary: format!("{} perfiles disponibles", list.len()),
        });
        let _ = emit(
            sink,
            OpEvent::Phase(Phase::Done {
                summary: format!("{} perfiles disponibles", list.len()),
            }),
        );
        Ok(list)
    }
}

impl Operation for ProfilesOp {
    fn describe(&self) -> String {
        "profiles".into()
    }
}