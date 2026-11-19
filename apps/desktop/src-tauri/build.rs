fn main() {
    println!("cargo:rerun-if-changed=capabilities");
    println!("cargo:rerun-if-changed=permissions/s08.toml");

    let attributes = tauri_build::Attributes::new()
        .app_manifest(tauri_build::AppManifest::new().commands(&[
            "selected_spike",
            "selected_case",
            "record_renderer_event",
            "mock_settings_read",
            "sentinel_tool_command",
            "sentinel_project_open",
            "sentinel_mcp_command",
            "sentinel_marketplace_command",
            "sentinel_file_access",
        ]))
        .plugin(
            "s01-traffic-lights",
            tauri_build::InlinedPlugin::new().commands(&[
                "s01_reposition_traffic_lights",
                "s01_inspect_traffic_lights",
                "s01_set_fullscreen",
            ]),
        )
        .plugin(
            "s02-system-menu",
            tauri_build::InlinedPlugin::new().commands(&[
                "s02_open_system_menu_at_origin",
                "s02_set_hit_test_regions",
                "s02_set_menu_mode",
                "s02_dispatch_system_command",
                "s02_set_window_state",
                "s02_close_after_guard",
                "s02_get_window_menu_state",
            ]),
        )
        .plugin(
            "s03-gnome-menu",
            tauri_build::InlinedPlugin::new().commands(&[
                "set_header_regions",
                "set_menu_mode",
                "set_test_maximized",
                "fallback_window_state",
                "perform_fallback_action",
            ]),
        )
        .plugin(
            "s08-settings",
            tauri_build::InlinedPlugin::new()
                .permissions_path_pattern("permissions/s08.toml"),
        )
        .plugin("s10-colour-input", tauri_build::InlinedPlugin::new())
        .plugin(
            "s11-accent",
            tauri_build::InlinedPlugin::new().commands(&["current_accent"]),
        );

    tauri_build::try_build(attributes).expect("failed to build the synthetic command ACL");
}
