//! SuryaDhana desktop shell entry point (see lib.rs).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    suryadhana_desktop_lib::run()
}
