use serde::{Deserialize, Serialize};
use tauri::{
    Manager, State, Wry,
    plugin::{Builder, PluginHandle, TauriPlugin},
};

struct AndroidAccentHandle(PluginHandle<Wry>);

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct AccentSnapshot {
    available: bool,
    reason: Option<String>,
    rgb: Option<Vec<f64>>,
    sequence: u64,
    source: String,
    portal_interface_version: Option<u32>,
}

#[tauri::command]
async fn current_accent(handle: State<'_, AndroidAccentHandle>) -> Result<AccentSnapshot, String> {
    handle
        .0
        .run_mobile_plugin("currentAccent", ())
        .map_err(|error| error.to_string())
}

pub fn plugin() -> TauriPlugin<Wry> {
    Builder::new("s11-accent")
        .invoke_handler(tauri::generate_handler![current_accent])
        .setup(|app, api| {
            let handle =
                api.register_android_plugin("org.example.shellspikes.accent", "S11AccentPlugin")?;
            let _ = app.manage(AndroidAccentHandle(handle));
            Ok(())
        })
        .build()
}
