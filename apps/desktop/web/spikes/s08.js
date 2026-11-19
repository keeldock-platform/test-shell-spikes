// S08 synthetic Settings window fixture. The shared bootstrap injects all
// Tauri invoke and evidence bridges; no product client or external content is used.
import { listen } from "../vendor/@tauri-apps/api/event.js";

const COMMANDS = Object.freeze({
  open: "plugin:s08-settings|s08_open_settings",
  read: "plugin:s08-settings|s08_read_settings",
  write: "plugin:s08-settings|s08_write_setting",
  schema: "plugin:s08-settings|s08_settings_schema",
  search: "plugin:s08-settings|s08_settings_search",
  shortcut: "plugin:s08-settings|s08_update_shortcut",
  stepUp: "plugin:s08-settings|s08_request_step_up",
  importLicense: "plugin:s08-settings|s08_import_license",
  exportData: "plugin:s08-settings|s08_export_data",
  importData: "plugin:s08-settings|s08_import_data",
  passphrase: "plugin:s08-settings|s08_vault_passphrase_action",
  recovery: "plugin:s08-settings|s08_vault_recovery_action",
  project: "plugin:s08-settings|s08_project_settings",
  team: "plugin:s08-settings|s08_team_settings",
  getView: "plugin:s08-settings|s08_get_view_state",
  setView: "plugin:s08-settings|s08_set_view_state",
  geometry: "plugin:s08-settings|s08_window_geometry",
  hide: "plugin:s08-settings|s08_hide_settings",
  destroy: "plugin:s08-settings|s08_test_destroy_settings",
  lock: "plugin:s08-settings|s08_test_lock_vault",
  unlock: "plugin:s08-settings|s08_test_unlock_vault",
});

const element = (tag, text, attributes = {}) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  return node;
};

const button = (label, action, attributes = {}) => {
  const node = element("button", label, { type: "button", "aria-label": label, ...attributes });
  node.addEventListener("click", action);
  return node;
};

const showStatus = (target, message) => { target.textContent = message; };
const rejectionText = (error) => {
  if (typeof error === "string") return error;
  if (error?.message) return String(error.message);
  try { return JSON.stringify(error); } catch { return String(error); }
};
const isPolicyDenial = (error) => /not allowed|forbidden|permission|capability|denied/i.test(rejectionText(error));

export async function registerSpike({ root, caseId, invoke, frame, record }) {
  if (!root || typeof invoke !== "function" || typeof frame !== "function" || typeof record !== "function") {
    throw new Error("S08 requires the shared root and evidence bridges");
  }

  const role = new URLSearchParams(window.location.search).get("window") === "settings" ? "settings" : "main";
  let frameSequence = 1;
  let spikeReady = false;
  let poseMarker;
  const mark = (phase, fields = {}) => {
    if (fields.pose && poseMarker) {
      poseMarker.textContent = `Pose: ${fields.pose}`;
      poseMarker.dataset.s08Pose = fields.pose;
    }
    if (spikeReady) frame(++frameSequence, phase, { caseId, windowRole: role, ...fields });
  };
  const note = (name, fields = {}) => {
    void record(name, { caseId, windowRole: role, ...fields });
  };

  function buildMain() {
    root.replaceChildren();
    const surface = element("main", undefined, { "data-s08-root": "main", "aria-label": "Main mock window" });
    const heading = element("h1", "Main window");
    poseMarker = element("output", "Pose: S08-MAIN", { "data-s08-pose": "S08-MAIN" });
    const activeState = element("p", "Main window active", { "data-s08-active-state": "active" });
    const status = element("output", "Ready", { "aria-live": "polite", "data-s08-status": "" });
    const counter = element("output", "Main actions: 0", { "data-s08-main-counter": "0" });
    const actions = element("section", undefined, { "aria-label": "Main window test controls" });
    const settingsView = element("section", undefined, { hidden: "", "data-s08-tool-settings": "" });
    settingsView.append(element("h2", "Tool settings mock"));
    settingsView.append(element("p", "This view belongs to the main window."));
    let mainActions = 0;

    const openSettings = async () => {
      try {
        await invoke(COMMANDS.open);
        showStatus(status, "Settings opened or focused");
        note("settings-open-request", { accepted: true });
      } catch (error) {
        showStatus(status, "Settings request was refused");
        note("settings-open-request", { accepted: false, reason: rejectionText(error) });
      }
    };

    actions.append(
      button("Open Settings", openSettings),
      button("Increment main action counter", () => {
        mainActions += 1;
        counter.textContent = `Main actions: ${mainActions}`;
        counter.dataset.s08MainCounter = String(mainActions);
        note("main-control-activated", { actionCount: mainActions });
      }),
      button("Destroy Settings window (test)", async () => {
        try {
          await invoke(COMMANDS.destroy);
          showStatus(status, "Settings destroyed for the geometry test");
          note("settings-destroy-request", { accepted: true });
        } catch (error) {
          showStatus(status, "Settings destroy request was refused");
          note("settings-destroy-request", { accepted: false, reason: rejectionText(error) });
        }
      }),
      button("Simulate vault lock (test)", async () => {
        try {
          await invoke(COMMANDS.lock);
          showStatus(status, "Mock lock signal sent; Settings destroyed");
          note("mock-lock-request", { accepted: true });
        } catch (error) {
          showStatus(status, "Mock lock request was refused");
          note("mock-lock-request", { accepted: false, reason: rejectionText(error) });
        }
      }),
      button("Unlock mock state (test)", async () => {
        try {
          await invoke(COMMANDS.unlock);
          showStatus(status, "Mock state unlocked");
          note("mock-unlock-request", { accepted: true });
        } catch (error) {
          showStatus(status, "Mock unlock request was refused");
          note("mock-unlock-request", { accepted: false, reason: rejectionText(error) });
        }
      })
    );

    surface.append(heading, poseMarker, activeState, status, counter, actions, settingsView);
    root.append(surface);

    const setInactive = (inactive) => {
      surface.dataset.windowActive = inactive ? "false" : "true";
      activeState.textContent = inactive ? "Main window inactive" : "Main window active";
      activeState.dataset.s08ActiveState = inactive ? "inactive" : "active";
      mark(inactive ? "inactive" : "active", { pose: inactive ? "S1-12" : "S08-MAIN" });
      note("main-window-activity", { inactive });
    };

    void listen("s08:window-activity", (event) => setInactive(!event.payload)).catch((error) => {
      note("window-activity-listener-failed", { reason: rejectionText(error) });
    });

    document.addEventListener("keydown", async (event) => {
      if ((event.code !== "Comma" && event.key !== ",") || !event.metaKey || event.repeat) return;
      event.preventDefault();
      if (event.altKey) {
        settingsView.hidden = false;
        showStatus(status, "Tool settings opened in the main window");
        mark("ready", { pose: "S08-TOOL-SETTINGS" });
        note("tool-settings-opened", { settingsWindowCreated: false });
        return;
      }
      mark("applying", { action: "open-settings" });
      await openSettings();
    });
  }

  async function buildSettings() {
    root.replaceChildren();
    const surface = element("main", undefined, { id: "s08-settings", "data-s08-root": "settings", "aria-label": "Settings" });
    const heading = element("h1", "Settings");
    poseMarker = element("output", "Pose: S4-14", { "data-s08-pose": "S4-14" });
    const status = element("output", "Ready", { "aria-live": "polite", "data-s08-status": "" });
    const toolbar = element("section", undefined, { "aria-label": "Settings window controls" });
    const layout = element("div", undefined, { "data-s08-layout": "" });
    const nav = element("nav", undefined, { "aria-label": "Settings pages" });
    const panel = element("section", undefined, {
      "aria-label": "Settings page content",
      "data-s08-panel": "",
      tabindex: "0",
    });
    const pageMarker = element("output", "Page: General; scroll: 0", { "data-s08-view-marker": "" });
    const viewSaveMarker = element("output", "View state pending", { "data-s08-view-save": "pending" });
    const geometryMarker = element("output", "Native geometry: pending", { "data-s08-native-geometry": "" });
    const denialOutput = element("output", "Not run", { "data-s08-denial-results": "not-run", "aria-live": "polite" });
    const actionCounter = element("output", "Settings actions: 0", { "data-s08-settings-counter": "0" });
    const settingLabels = ["General", "Appearance", "Security", "Data and storage", "Team"];
    const frameByPage = new Map([
      ["General", "S4-14"],
      ["Security", "S4-16"],
      ["Team", "S4-18"],
      ["Appearance", "S08-APPEARANCE"],
      ["Data and storage", "S08-DATA"],
    ]);
    const denialCommands = [
      "plugin:s08-settings|s08_sentinel_tool_command",
      "plugin:s08-settings|s08_sentinel_pane_command",
      "plugin:s08-settings|s08_sentinel_tab_project_open",
      "plugin:s08-settings|s08_sentinel_mcp_command",
      "plugin:s08-settings|s08_sentinel_marketplace_command",
      "plugin:s08-settings|s08_sentinel_file_grant",
      "plugin:dialog|open",
    ];
    let currentPage = "General";
    let lastSavedScroll = -1;
    let settingsActions = 0;

    const rememberView = async (force = false) => {
      const scrollTop = Math.max(0, Math.round(panel.scrollTop));
      pageMarker.textContent = `Page: ${currentPage}; scroll: ${scrollTop}`;
      pageMarker.dataset.s08Page = currentPage;
      pageMarker.dataset.s08Scroll = String(scrollTop);
      if (!force && Math.abs(scrollTop - lastSavedScroll) < 16) return;
      lastSavedScroll = scrollTop;
      try {
        await invoke(COMMANDS.setView, { page: currentPage, scrollTop });
        viewSaveMarker.textContent = `View state saved: Page: ${currentPage}; scroll: ${scrollTop}`;
        viewSaveMarker.dataset.s08ViewSave = "saved";
        note("view-state-saved", { page: currentPage, scrollTop });
      } catch (error) {
        showStatus(status, "Page state could not be saved");
        viewSaveMarker.textContent = `View state failed: Page: ${currentPage}; scroll: ${scrollTop}`;
        viewSaveMarker.dataset.s08ViewSave = "failed";
        note("view-state-save-failed", { reason: rejectionText(error) });
      }
    };

    const addPanelButton = (label, action) => panel.append(button(label, action));
    const mockAction = async (command, args = {}) => {
      try {
        const result = await invoke(command, args);
        settingsActions += 1;
        actionCounter.textContent = `Settings actions: ${settingsActions}`;
        actionCounter.dataset.s08SettingsCounter = String(settingsActions);
        note("settings-control-activated", { actionCount: settingsActions });
        return result;
      } catch (error) {
        showStatus(status, "Settings action was refused");
        note("settings-control-refused", { reason: rejectionText(error) });
        throw error;
      }
    };

    const requestStepUp = async () => {
      document.body.dataset.frameId = "S4-17";
      mark("applying", { pose: "S4-17" });
      try {
        await mockAction(COMMANDS.stepUp);
        showStatus(status, "Native step-up sheet requested");
      } catch {
        showStatus(status, "Step-up request was refused");
      }
    };

    const renderPage = async (page, scrollTop = 0) => {
      currentPage = settingLabels.includes(page) ? page : "General";
      lastSavedScroll = -1;
      panel.replaceChildren(element("h2", currentPage, { "data-s08-page-heading": currentPage }));
      document.body.dataset.frameId = frameByPage.get(currentPage) ?? "S08-SETTINGS";
      mark("ready", { pose: document.body.dataset.frameId, page: currentPage });

      if (currentPage === "General") {
        panel.append(element("p", "Synthetic Settings content for the native window spike."));
        const content = element("section", undefined, { "aria-label": "General settings actions" });
        content.append(
          button("Request step-up", requestStepUp),
          button("Increment Settings action counter", async () => {
            try {
              await mockAction(COMMANDS.write, { key: "theme", value: "dark" });
              showStatus(status, "Settings mock counter changed");
            } catch {}
          }),
          button("Import licence (host picker)", async () => {
            try { await mockAction(COMMANDS.importLicense); showStatus(status, "Host licence picker opened"); }
            catch { showStatus(status, "Licence picker request was refused"); }
          }),
          button("Export sample data (host picker)", async () => {
            try { await mockAction(COMMANDS.exportData); showStatus(status, "Host export picker opened"); }
            catch { showStatus(status, "Export picker request was refused"); }
          }),
          button("Import sample data (host picker)", async () => {
            try { await mockAction(COMMANDS.importData); showStatus(status, "Host import picker opened"); }
            catch { showStatus(status, "Import picker request was refused"); }
          }),
          button("Mock passphrase action", async () => { try { await mockAction(COMMANDS.passphrase); showStatus(status, "Synthetic passphrase action accepted"); } catch {} }),
          button("Mock recovery action", async () => { try { await mockAction(COMMANDS.recovery); showStatus(status, "Synthetic recovery action accepted"); } catch {} }),
          button("Open synthetic project settings", async () => {
            try { showStatus(status, await mockAction(COMMANDS.project)); }
            catch { showStatus(status, "Project settings request was refused"); }
          }),
          button("Open synthetic team settings", async () => {
            try { await mockAction(COMMANDS.team); await renderPage("Team"); }
            catch { showStatus(status, "Team settings request was refused"); }
          }),
        );
        panel.append(content);
      } else if (currentPage === "Security") {
        panel.append(element("p", "Mock security settings. No credential or vault operation is performed."));
        addPanelButton("Request step-up", requestStepUp);
        addPanelButton("Mock passphrase action", async () => { try { await mockAction(COMMANDS.passphrase); } catch {} });
        addPanelButton("Mock recovery action", async () => { try { await mockAction(COMMANDS.recovery); } catch {} });
      } else if (currentPage === "Team") {
        panel.append(element("p", "Synthetic team settings pose. No team data is loaded."));
        addPanelButton("Mock team setting", async () => { try { await mockAction(COMMANDS.team); } catch {} });
        for (let index = 1; index <= 18; index += 1) {
          const row = element("p", `Synthetic team preference ${index}`, { "data-s08-scroll-row": String(index) });
          row.style.minHeight = "56px";
          panel.append(row);
        }
      } else if (currentPage === "Appearance") {
        panel.append(element("p", "Theme: system. Density: comfortable."));
        addPanelButton("Set mock theme to dark", async () => {
          try { await mockAction(COMMANDS.write, { key: "theme", value: "dark" }); }
          catch {}
        });
        addPanelButton("Save mock shortcut", async () => {
          try { await mockAction(COMMANDS.shortcut, { commandId: "settings.open", chord: "Command+," }); }
          catch {}
        });
      } else {
        panel.append(element("p", "Synthetic export and import settings."));
      }

      panel.scrollTop = scrollTop;
      await rememberView(true);
      note("settings-page-rendered", { page: currentPage, scrollTop: panel.scrollTop });
    };

    panel.style.maxHeight = "340px";
    panel.style.overflowY = "auto";
    for (const page of settingLabels) nav.append(button(page, () => { void renderPage(page); }));

    toolbar.append(
      button("Hide Settings", async () => {
        try { await invoke(COMMANDS.hide); note("settings-hide-request", { accepted: true }); }
        catch (error) { showStatus(status, "Hide request was refused"); note("settings-hide-request", { accepted: false, reason: rejectionText(error) }); }
      }),
      button("Run allowed command checks", async () => {
        const checks = [
          ["settings read", () => invoke(COMMANDS.read)],
          ["settings write", () => invoke(COMMANDS.write, { key: "density", value: "comfortable" })],
          ["settings schema", () => invoke(COMMANDS.schema)],
          ["settings search", () => invoke(COMMANDS.search, { query: "Sec" })],
          ["shortcut editor", () => invoke(COMMANDS.shortcut, { commandId: "settings.open", chord: "Command+," })],
          ["vault passphrase", () => invoke(COMMANDS.passphrase)],
          ["vault recovery", () => invoke(COMMANDS.recovery)],
          ["project settings", () => invoke(COMMANDS.project)],
          ["team settings", () => invoke(COMMANDS.team)],
        ];
        const results = await Promise.all(checks.map(async ([name, call]) => {
          try { await call(); return { name, result: "allowed" }; }
          catch (error) { return { name, result: "rejected", reason: rejectionText(error) }; }
        }));
        const passed = results.every((item) => item.result === "allowed");
        showStatus(status, results.map(({ name, result }) => `${name}:${result}`).join("; "));
        note("allowed-command-checks", { results, passed });
      }),
      button("Run denial probes", async () => {
        const results = await Promise.all(denialCommands.map(async (command) => {
          try {
            await invoke(command, command === "plugin:dialog|open" ? { options: {} } : {});
            return { command, result: "unexpectedly-allowed" };
          } catch (error) {
            return { command, result: isPolicyDenial(error) ? "policy-denied" : "unverified-rejection", reason: rejectionText(error) };
          }
        }));
        const passed = results.every((item) => item.result === "policy-denied");
        denialOutput.textContent = results.map(({ command, result }) => `${command}:${result}`).join("; ");
        denialOutput.dataset.s08DenialResults = passed ? "blocked" : "incomplete";
        showStatus(status, passed ? "All denial probes were policy-denied" : "At least one denial probe was not evidenced");
        note("denial-probes", { results, passed });
      }),
    );

    surface.append(heading, poseMarker, status, toolbar, actionCounter, layout, pageMarker, viewSaveMarker, geometryMarker, denialOutput);
    layout.append(nav, panel);
    root.append(surface);
    panel.addEventListener("scroll", () => { void rememberView(); }, { passive: true });

    document.addEventListener("keydown", (event) => {
      if (event.key === "," && event.metaKey && !event.altKey) event.preventDefault();
    });

    for (const [eventName, message] of [
      ["s08:step-up-result", "Mock confirmation"],
      ["s08:license-picker-result", "Synthetic licence"],
      ["s08:export-picker-result", "Synthetic export location"],
      ["s08:import-picker-result", "Synthetic import"],
    ]) {
      void listen(eventName, (event) => {
        showStatus(status, `${message} ${event.payload ? "accepted" : "cancelled"}`);
        note("native-dialog-result", { eventName, accepted: Boolean(event.payload) });
      }).catch((error) => note("native-dialog-listener-failed", { eventName, reason: rejectionText(error) }));
    }

    try {
      await invoke(COMMANDS.schema);
      await invoke(COMMANDS.search, { query: "General" });
      await invoke(COMMANDS.read);
      const saved = await invoke(COMMANDS.getView);
      const geometry = await invoke(COMMANDS.geometry);
      geometryMarker.textContent = `Native geometry: ${geometry.label} ${geometry.width}×${geometry.height} logical points; scale ${geometry.scaleFactor}; origin ${geometry.x},${geometry.y}`;
      note("native-settings-geometry", geometry);
      await renderPage(saved.page, saved.scrollTop);
    } catch (error) {
      showStatus(status, "Settings mock could not be restored");
      note("settings-restore-failed", { reason: rejectionText(error) });
    }
  }

  if (role === "settings") await buildSettings();
  else buildMain();
  spikeReady = true;

  return () => root.replaceChildren();
}
