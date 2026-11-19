#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Err(error) = shell_spike_desktop_lib::run() {
        eprintln!("test shell failed to start: {error}");
        std::process::exit(1);
    }
}
