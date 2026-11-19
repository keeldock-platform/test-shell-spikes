#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Err(error) = shell_spike_mobile_lib::run() {
        eprintln!("mobile test shell failed to start: {error}");
        std::process::exit(1);
    }
}
