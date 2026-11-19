fn main() {
    println!("cargo:rerun-if-changed=capabilities");
    println!("cargo:rerun-if-changed=permissions/s11-accent.toml");

    let attributes = tauri_build::Attributes::new()
        .app_manifest(tauri_build::AppManifest::new().commands(&[
            "selected_spike",
            "selected_case",
            "record_renderer_event",
        ]))
        .plugin(
            "s11-accent",
            tauri_build::InlinedPlugin::new()
                .commands(&[
                    "current_accent",
                    "register_listener",
                    "registerListener",
                    "remove_listener",
                ])
                .permissions_path_pattern("permissions/s11-accent.toml"),
        );

    tauri_build::try_build(attributes).expect("failed to build the mobile command ACL");
}
