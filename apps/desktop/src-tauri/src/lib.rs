mod spikes;

use std::{fs::OpenOptions, io::Write, path::PathBuf};

#[tauri::command]
fn selected_spike() -> Result<String, String> {
    spikes::validate_selection()?;
    Ok(spikes::selected_id()
        .map(str::to_owned)
        .unwrap_or_else(|| "smoke".to_owned()))
}

#[tauri::command]
fn selected_case() -> Option<String> {
    std::env::var("SHELL_CASE_ID").ok()
}

#[tauri::command]
fn record_renderer_event(payload: String) -> Result<(), String> {
    if payload.len() > 64 * 1024 {
        return Err("renderer event exceeds the evidence size limit".to_owned());
    }
    let mut event: serde_json::Value = serde_json::from_str(&payload)
        .map_err(|_| "renderer event payload is not valid JSON".to_owned())?;
    let object = event
        .as_object_mut()
        .ok_or_else(|| "renderer event payload must be a JSON object".to_owned())?;
    let timestamp = monotonic_nanoseconds()
        .ok_or_else(|| "host monotonic clock could not be read".to_owned())?;
    object.insert("hostMonotonicNanoseconds".to_owned(), timestamp.into());
    object.insert("hostPid".to_owned(), std::process::id().into());
    if let Some(fields) = object.get("detail").and_then(|v| v.get("fields")) {
        let receipt = fields
            .get("nativeEventNs")
            .and_then(serde_json::Value::as_u64);
        let update = fields
            .get("hostUpdateNs")
            .and_then(serde_json::Value::as_u64);
        if let (Some(receipt), Some(update)) = (receipt, update) {
            object.insert("hostReceiptMonotonicNanoseconds".to_owned(), receipt.into());
            object.insert("hostUpdateMonotonicNanoseconds".to_owned(), update.into());
        }
    }

    let evidence = std::env::var_os("SHELL_EVIDENCE_DIR")
        .map(PathBuf::from)
        .ok_or_else(|| "case evidence directory is unavailable".to_owned())?;
    append_event(&evidence.join("recorder/renderer-events.jsonl"), &event)?;
    if event.get("type").and_then(serde_json::Value::as_str) == Some("shell-spike:shutdown-flushed")
    {
        std::fs::write(evidence.join("recorder/shutdown-flushed"), b"flushed")
            .map_err(|error| error.to_string())?;
    }
    if event.get("type").and_then(serde_json::Value::as_str) == Some("shell-spike:event") {
        append_s01_event(&evidence.join("recorder/s01-events.jsonl"), &event)?;
        append_s01_event(&evidence.join("events.jsonl"), &event)?;
    }
    Ok(())
}

fn append_event(path: &std::path::Path, event: &serde_json::Value) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|_| "event evidence directory could not be created".to_owned())?;
    }
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|_| "renderer event evidence could not be opened".to_owned())?;
    serde_json::to_writer(&mut file, event)
        .map_err(|_| "renderer event could not be encoded".to_owned())?;
    file.write_all(b"\n")
        .map_err(|_| "renderer event could not be written".to_owned())
}

fn append_s01_event(path: &std::path::Path, event: &serde_json::Value) -> Result<(), String> {
    let detail = event
        .get("detail")
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| "renderer event detail is unavailable".to_owned())?;
    let fields = detail
        .get("fields")
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| "renderer event fields are unavailable".to_owned())?;
    let mut normalized = fields.clone();
    if !normalized.contains_key("sequenceId") {
        if let Some(sequence) = fields.get("sequence") {
            normalized.insert("sequenceId".to_owned(), sequence.clone());
        }
    }
    normalized.insert(
        "name".to_owned(),
        detail.get("name").cloned().unwrap_or_default(),
    );
    normalized.insert("hostPid".to_owned(), std::process::id().into());
    normalized.insert(
        "kind".to_owned(),
        detail
            .get("name")
            .cloned()
            .unwrap_or_else(|| "renderer-event".into()),
    );
    normalized.insert(
        "rendererMonotonicTime".to_owned(),
        detail
            .get("monotonicTime")
            .cloned()
            .unwrap_or(serde_json::Value::Null),
    );
    normalized.insert(
        "monotonicNanoseconds".to_owned(),
        event
            .get("hostMonotonicNanoseconds")
            .cloned()
            .unwrap_or(serde_json::Value::Null),
    );
    normalized.insert(
        "utc".to_owned(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_millis().to_string())
            .unwrap_or_default()
            .into(),
    );
    append_event(path, &serde_json::Value::Object(normalized))
}

#[cfg(unix)]
fn monotonic_nanoseconds() -> Option<u64> {
    #[repr(C)]
    struct Timespec {
        seconds: i64,
        nanoseconds: i64,
    }
    #[cfg(any(target_os = "macos", target_os = "ios"))]
    const CLOCK_MONOTONIC: i32 = 6;
    #[cfg(not(any(target_os = "macos", target_os = "ios")))]
    const CLOCK_MONOTONIC: i32 = 1;
    unsafe extern "C" {
        fn clock_gettime(clock_id: i32, value: *mut Timespec) -> i32;
    }
    let mut value = Timespec {
        seconds: 0,
        nanoseconds: 0,
    };
    let result = unsafe { clock_gettime(CLOCK_MONOTONIC, &mut value) };
    (result == 0).then_some((value.seconds as u64) * 1_000_000_000 + value.nanoseconds as u64)
}

#[cfg(windows)]
fn monotonic_nanoseconds() -> Option<u64> {
    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn QueryPerformanceCounter(value: *mut i64) -> i32;
        fn QueryPerformanceFrequency(value: *mut i64) -> i32;
    }
    let mut counter = 0_i64;
    let mut frequency = 0_i64;
    let ok = unsafe {
        QueryPerformanceCounter(&mut counter) != 0 && QueryPerformanceFrequency(&mut frequency) != 0
    };
    (ok && frequency > 0).then_some((counter as u128 * 1_000_000_000 / frequency as u128) as u64)
}

#[tauri::command]
fn mock_settings_read() -> &'static str {
    r#"{"theme":"system","density":"comfortable","mockCounter":0}"#
}

fn denied_sentinel() -> Result<(), String> {
    Err("operation denied by the synthetic test shell".to_owned())
}

#[tauri::command]
fn sentinel_tool_command() -> Result<(), String> {
    denied_sentinel()
}

#[tauri::command]
fn sentinel_project_open() -> Result<(), String> {
    denied_sentinel()
}

#[tauri::command]
fn sentinel_mcp_command() -> Result<(), String> {
    denied_sentinel()
}

#[tauri::command]
fn sentinel_marketplace_command() -> Result<(), String> {
    denied_sentinel()
}

#[tauri::command]
fn sentinel_file_access() -> Result<(), String> {
    denied_sentinel()
}

pub fn run() -> tauri::Result<()> {
    spikes::validate_selection().map_err(std::io::Error::other)?;
    let builder = tauri::Builder::default().invoke_handler(tauri::generate_handler![
        selected_spike,
        selected_case,
        record_renderer_event,
        mock_settings_read,
        sentinel_tool_command,
        sentinel_project_open,
        sentinel_mcp_command,
        sentinel_marketplace_command,
        sentinel_file_access
    ]);
    use tauri::{Emitter, Manager};
    let app = spikes::register(builder).on_page_load(|webview, _| {
        let handle = webview.app_handle().clone();
        if let Some(evidence) = std::env::var_os("SHELL_EVIDENCE_DIR") {
            std::thread::spawn(move || {
                let request = PathBuf::from(evidence).join("recorder/shutdown-request");
                for _ in 0..36_000 {
                    if request.is_file() {
                        let _ = handle.emit("shell-spike:shutdown", ());
                        break;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(100));
                }
            });
        }
    });
    app.run(tauri::generate_context!())
}
