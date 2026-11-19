use std::{fs::OpenOptions, io::Write};
use tauri::Manager;

#[tauri::command]
fn selected_spike() -> &'static str {
    "mobile"
}

#[tauri::command]
fn selected_case() -> Option<String> {
    None
}

#[tauri::command]
fn record_renderer_event(app: tauri::AppHandle, payload: String) -> Result<(), String> {
    if payload.len() > 64 * 1024 {
        return Err("renderer event exceeds the evidence size limit".to_owned());
    }
    let mut event: serde_json::Value = serde_json::from_str(&payload)
        .map_err(|_| "renderer event payload is not valid JSON".to_owned())?;
    let object = event
        .as_object_mut()
        .ok_or_else(|| "renderer event payload must be a JSON object".to_owned())?;
    let case_id = object
        .get("caseId")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| "renderer event payload must include its case id".to_owned())?;
    let safe_case_id: String = case_id
        .chars()
        .filter(|character| {
            character.is_ascii_alphanumeric() || *character == '-' || *character == '_'
        })
        .collect();
    if safe_case_id.is_empty() || safe_case_id.len() > 96 || safe_case_id != case_id {
        return Err("renderer event case id is not a safe file name".to_owned());
    }
    object.insert(
        "hostMonotonicNanoseconds".to_owned(),
        mobile_monotonic_nanoseconds()?.into(),
    );
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
            object.insert(
                "nativeClockDomain".to_owned(),
                "android-elapsed-realtime".into(),
            );
        }
    }
    let recorder = app
        .path()
        .app_data_dir()
        .map_err(|_| "mobile app data directory is unavailable".to_owned())?
        .join("recorder");
    std::fs::create_dir_all(&recorder)
        .map_err(|_| "mobile event directory could not be created".to_owned())?;
    append_mobile_event(
        &recorder.join(format!("renderer-events-{safe_case_id}.jsonl")),
        &event,
    )?;
    if event.get("type").and_then(serde_json::Value::as_str) == Some("shell-spike:event") {
        append_mobile_s01_event(
            &recorder.join(format!("s01-events-{safe_case_id}.jsonl")),
            &event,
        )?;
    }
    Ok(())
}

fn append_mobile_event(path: &std::path::Path, event: &serde_json::Value) -> Result<(), String> {
    let mut output = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|_| "mobile event evidence could not be opened".to_owned())?;
    serde_json::to_writer(&mut output, event)
        .map_err(|_| "renderer event could not be encoded".to_owned())?;
    output
        .write_all(b"\n")
        .map_err(|_| "renderer event could not be written".to_owned())
}

fn append_mobile_s01_event(
    path: &std::path::Path,
    event: &serde_json::Value,
) -> Result<(), String> {
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
    append_mobile_event(path, &serde_json::Value::Object(normalized))
}

#[cfg(unix)]
fn mobile_monotonic_nanoseconds() -> Result<u64, String> {
    #[repr(C)]
    struct Timespec {
        seconds: i64,
        nanoseconds: i64,
    }
    #[cfg(target_os = "ios")]
    const CLOCK_MONOTONIC: i32 = 6;
    #[cfg(target_os = "android")]
    const CLOCK_MONOTONIC: i32 = 1;
    unsafe extern "C" {
        fn clock_gettime(clock_id: i32, value: *mut Timespec) -> i32;
    }
    let mut value = Timespec {
        seconds: 0,
        nanoseconds: 0,
    };
    let status = unsafe { clock_gettime(CLOCK_MONOTONIC, &mut value) };
    if status != 0 {
        return Err("mobile monotonic clock could not be read".to_owned());
    }
    Ok((value.seconds as u64) * 1_000_000_000 + value.nanoseconds as u64)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() -> tauri::Result<()> {
    let builder = tauri::Builder::default().invoke_handler(tauri::generate_handler![
        selected_spike,
        selected_case,
        record_renderer_event
    ]);
    #[cfg(all(feature = "spike-s11", target_os = "android"))]
    let builder = builder.plugin(s11_android::plugin());
    builder.run(tauri::generate_context!())
}

#[cfg(all(feature = "spike-s11", target_os = "android"))]
mod s11_android;
