// S02 synthetic Windows system-menu UI. Native entry is owned by the Win32
// adapter; this kit menu exists only as the specified fallback.
import { listen } from "../vendor/@tauri-apps/api/event.js";

const ITEMS = [
  { id: "restore", label: "Restore", enabled: (s) => s.maximized || s.minimized },
  { id: "move", label: "Move", enabled: (s) => !s.maximized && !s.minimized },
  { id: "size", label: "Size", enabled: (s) => s.resizable && !s.maximized && !s.minimized },
  { id: "minimize", label: "Minimize", enabled: (s) => !s.minimized },
  { id: "maximize", label: "Maximize", enabled: (s) => s.resizable && !s.maximized && !s.minimized },
  { id: "close", label: "Close", enabled: () => true },
];

const style = (node, rules) => Object.assign(node.style, rules);

function make(tag, label, attributes = {}) {
  const node = document.createElement(tag);
  if (label !== undefined) node.textContent = label;
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

function button(parent, label, attributes = {}) {
  const node = make("button", label, { type: "button", "aria-label": label, ...attributes });
  parent.append(node);
  return node;
}

export async function registerSpike({ root, caseId, invoke, frame, record }) {
  if (!root || typeof invoke !== "function" || typeof frame !== "function" || typeof record !== "function") {
    throw new Error("S02 requires the shared spike root and evidence bridges");
  }
  const invokeS02 = (command, args = {}) =>
    invoke(`plugin:s02-system-menu|${command}`, args);

  // Own only this lane's surface; leave the shared capture marker in place.
  root.querySelector("[data-s02-surface]")?.remove();
  const surface = make("main", undefined, {
    "data-s02-surface": "true",
    "aria-label": "S02 synthetic system-menu test shell",
  });
  style(surface, { display: "flex", flexDirection: "column", minHeight: "100vh", font: "14px system-ui, sans-serif" });

  const titlebar = make("header", undefined, { "aria-label": "S02 title bar" });
  style(titlebar, { display: "flex", alignItems: "stretch", minHeight: "44px", borderBottom: "1px solid #777" });
  const appIcon = button(titlebar, "■", { "aria-label": "S02 app icon", "data-s02-app-icon": "true" });
  const emptyChrome = make("div", "Empty title-bar space", {
    role: "group", tabindex: "0", "aria-label": "S02 empty title bar", "data-s02-empty-chrome": "true",
  });
  style(emptyChrome, { flex: "1", minWidth: "180px", display: "flex", alignItems: "center", paddingInline: "12px", userSelect: "none" });
  titlebar.append(emptyChrome);
  const tab = button(titlebar, "S02 sample tab", { "data-s02-tab": "true" });
  const maximize = button(titlebar, "S02 maximize button", { "data-s02-maximize": "true" });
  maximize.title = "Maximize window";
  style(maximize, { width: "48px", minWidth: "48px" });

  const controls = make("section", undefined, { "aria-label": "S02 test controls" });
  style(controls, { padding: "20px", display: "grid", gap: "10px", alignContent: "start" });
  const input = make("input", undefined, { type: "text", "aria-label": "S02 sample input" });
  input.value = "Synthetic input";
  const controlRow = make("div");
  style(controlRow, { display: "flex", gap: "8px", flexWrap: "wrap" });
  const restoreControl = button(controlRow, "Restore window");
  const maximizeControl = button(controlRow, "Maximize window");
  const minimizeControl = button(controlRow, "Minimize window");
  const resetAccelerator = button(controlRow, "Reset WebView2 accelerator receipt");
  const modeButton = button(controlRow, "Use kit-drawn fallback", { "data-s02-mode-toggle": "true" });
  controls.append(input, controlRow);

  const status = make("output", "Ready", { "aria-live": "polite", "aria-label": "S02 status", "data-s02-status": "true" });
  const hitTestReceipt = make("output", "", { "aria-live": "polite", "aria-label": "S02 hit-test geometry receipt" });
  hitTestReceipt.hidden = true;
  const acceleratorReceipt = make("output", "", { "aria-live": "polite", "aria-label": "S02 WebView2 accelerator receipt", "data-s02-webview2-accelerator": "false" });
  acceleratorReceipt.hidden = true;
  const guard = make("section", undefined, {
    role: "dialog", "aria-modal": "true", "aria-label": "S02 mock close guard", "data-s02-close-guard": "true",
  });
  guard.hidden = true;
  guard.append(make("p", "Synthetic unsaved work is open."));
  const keepOpen = button(guard, "Keep S02 open");
  const discard = button(guard, "Discard synthetic work and close");
  surface.append(titlebar, controls, status, hitTestReceipt, acceleratorReceipt, guard);
  root.append(surface);

  const params = new URLSearchParams(window.location.search);
  let mode = params.get("s02Menu") === "kit" ? "kit" : "native";
  let state = { maximized: false, minimized: false, resizable: true };
  let menu = null;
  let menuInvoker = null;
  let menuKind = "system";
  let sequence = 0;
  let typeahead = "";
  let typeaheadTimer = 0;

  const note = (name, details = {}) => record(name, { caseId, sequenceId: sequence, ...details });
  const setFrame = (phase, details = {}) => frame(++sequence, phase, { caseId, menuMode: mode, ...details });
  const report = (message) => { status.textContent = message; surface.dataset.s02LastEvent = message; };

  function registerHitTestRegions() {
    const toRect = (element) => {
      const bounds = element.getBoundingClientRect();
      return { x: bounds.left, y: bounds.top, width: bounds.width, height: bounds.height };
    };
    void invokeS02("s02_set_hit_test_regions", {
      emptyChrome: toRect(emptyChrome),
      maximizeButton: toRect(maximize),
      scale: window.devicePixelRatio || 1,
    }).then(() => {
      hitTestReceipt.hidden = false;
      hitTestReceipt.textContent = "S02 hit-test geometry registered";
      hitTestReceipt.setAttribute("aria-label", hitTestReceipt.textContent);
    }).catch((error) => report(`Native hit-test geometry update failed: ${String(error)}`));
  }

  function updateModeControl() {
    modeButton.textContent = mode === "native" ? "Use kit-drawn fallback" : "Use native system menu";
    modeButton.setAttribute("aria-label", modeButton.textContent);
    surface.dataset.s02MenuMode = mode;
  }

  async function refreshState() {
    try {
      state = await invokeS02("s02_get_window_menu_state");
      surface.dataset.s02Maximized = String(Boolean(state.maximized));
      surface.dataset.s02Minimized = String(Boolean(state.minimized));
      if (menu && menuKind === "system") renderSystemMenu();
    } catch (error) {
      report(`Window-state read failed: ${String(error)}`);
    }
  }

  async function setWindowState(next) {
    try {
      await invokeS02("s02_set_window_state", { state: next });
      await refreshState();
      void note("window-state-requested", { state: next });
    } catch (error) {
      report(`Window-state request failed: ${String(error)}`);
    }
  }

  function closeMenu(restoreFocus = true) {
    if (!menu) return;
    menu.remove();
    menu = null;
    if (restoreFocus && menuInvoker instanceof HTMLElement) menuInvoker.focus();
  }

  function openKitMenu(x, y, source, focusFirst = false) {
    closeMenu(false);
    menuKind = "system";
    menuInvoker = document.activeElement instanceof HTMLElement ? document.activeElement : emptyChrome;
    menu = make("div", undefined, { role: "menu", "aria-label": "S02 Windows system menu", "data-s02-system-menu": "kit" });
    style(menu, { position: "fixed", left: `${Math.round(x)}px`, top: `${Math.round(y)}px`, minWidth: "224px", display: "flex", flexDirection: "column", zIndex: "2147483647", background: "white", border: "1px solid #555", boxShadow: "0 2px 8px #0005" });
    renderSystemMenu();
    menu.addEventListener("keydown", onMenuKeyDown);
    document.body.append(menu);
    setFrame("menu-open", { source, x: Math.round(x), y: Math.round(y) });
    void note("kit-menu-opened", { source, x: Math.round(x), y: Math.round(y) });
    report(`Kit system menu opened by ${source} at ${Math.round(x)},${Math.round(y)}.`);
    if (focusFirst) focusMenuItem(0);
  }

  function openTabContextMenu(x, y) {
    closeMenu(false);
    menuKind = "tab";
    menuInvoker = tab;
    menu = make("div", undefined, { role: "menu", "aria-label": "S02 sample tab actions", "data-s02-tab-context-menu": "true" });
    style(menu, { position: "fixed", left: `${Math.round(x)}px`, top: `${Math.round(y)}px`, zIndex: "2147483647", background: "white", border: "1px solid #555" });
    const openTab = button(menu, "Open sample tab", { role: "menuitem" });
    openTab.addEventListener("click", () => closeMenu(true));
    document.body.append(menu);
    void note("tab-context-menu-opened", { x: Math.round(x), y: Math.round(y) });
    report("Tab actions opened; the system menu stayed closed.");
  }

  function renderSystemMenu() {
    if (!menu) return;
    menu.replaceChildren();
    for (const item of ITEMS) {
      const node = button(menu, item.label, { role: "menuitem", "data-s02-command": item.id });
      node.disabled = !item.enabled(state);
      node.setAttribute("aria-disabled", String(node.disabled));
      node.addEventListener("click", () => void activateCommand(item.id));
    }
  }

  function focusMenuItem(index) {
    if (!menu) return;
    const items = [...menu.querySelectorAll('[role="menuitem"]:not(:disabled)')];
    if (!items.length) return;
    items[(index + items.length) % items.length]?.focus();
  }

  function onMenuKeyDown(event) {
    const items = [...menu.querySelectorAll('[role="menuitem"]:not(:disabled)')];
    const current = items.indexOf(document.activeElement);
    if (event.key === "Escape" || event.key === "Tab") {
      event.preventDefault();
      closeMenu(true);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      focusMenuItem(current + (event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      focusMenuItem(event.key === "Home" ? 0 : items.length - 1);
    } else if (event.key.length === 1 && !event.ctrlKey && !event.altKey) {
      typeahead += event.key.toLocaleLowerCase();
      window.clearTimeout(typeaheadTimer);
      typeaheadTimer = window.setTimeout(() => { typeahead = ""; }, 700);
      const index = items.findIndex((item) => item.textContent.toLocaleLowerCase().startsWith(typeahead));
      if (index >= 0) focusMenuItem(index);
    }
  }

  async function activateCommand(command) {
    closeMenu(false);
    report(`Selected ${command} from the ${mode} menu.`);
    void note("system-command-selected", { command, mode });
    try {
      await invokeS02("s02_dispatch_system_command", { command });
      if (command !== "close") await refreshState();
    } catch (error) {
      report(`System command failed: ${String(error)}`);
    }
  }

  appIcon.addEventListener("click", () => {
    if (mode === "native") {
      void invokeS02("s02_open_system_menu_at_origin").catch((error) => report(`Native app-icon menu request failed: ${String(error)}`));
    } else {
      const bounds = titlebar.getBoundingClientRect();
      openKitMenu(bounds.left, bounds.top, "app icon");
    }
  });
  maximize.addEventListener("click", () => void setWindowState("maximized"));
  restoreControl.addEventListener("click", () => void setWindowState("normal"));
  maximizeControl.addEventListener("click", () => void setWindowState("maximized"));
  minimizeControl.addEventListener("click", () => void setWindowState("minimized"));
  resetAccelerator.addEventListener("click", () => {
    acceleratorReceipt.hidden = true;
    acceleratorReceipt.textContent = "";
    acceleratorReceipt.setAttribute("aria-label", "S02 WebView2 accelerator receipt");
    acceleratorReceipt.dataset.s02Webview2Accelerator = "false";
  });
  modeButton.addEventListener("click", async () => {
    mode = mode === "native" ? "kit" : "native";
    updateModeControl();
    try {
      await invokeS02("s02_set_menu_mode", { mode });
    } catch (error) {
      report(`Native menu-mode update failed: ${String(error)}`);
    }
    report(`Menu mode is ${mode}.`);
    void note("menu-mode-selected", { mode });
  });
  keepOpen.addEventListener("click", () => {
    guard.hidden = true;
    report("Close cancelled by the mock guard.");
  });
  discard.addEventListener("click", () => void invokeS02("s02_close_after_guard"));

  document.addEventListener("contextmenu", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (tab.contains(target)) {
      event.preventDefault();
      openTabContextMenu(event.clientX, event.clientY);
    } else if (emptyChrome.contains(target)) {
      event.preventDefault();
      if (mode === "kit") openKitMenu(event.clientX, event.clientY, "right click");
      else {
        report("Native empty-chrome right click reached the WebView; expected WM_NCRBUTTONUP after HTCAPTION.");
        void note("native-right-click-missed-non-client-path", { clientX: event.clientX, clientY: event.clientY });
      }
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.altKey && event.code === "Space" && !event.repeat && mode === "kit") {
      event.preventDefault();
      event.stopPropagation();
      const bounds = titlebar.getBoundingClientRect();
      openKitMenu(bounds.left, bounds.top, "Alt+Space", true);
    } else if ((event.shiftKey && event.key === "F10") || event.key === "ContextMenu") {
      if (document.activeElement === tab) {
        event.preventDefault();
        const bounds = tab.getBoundingClientRect();
        openTabContextMenu(bounds.left, bounds.bottom);
      }
    }
  });

  // The host plugin emits this only after the native close request was
  // cancelled. The test guard is intentionally synthetic and local.
  const closeGuardUnlisten = await listen("s02-close-guard", () => {
      guard.hidden = false;
      keepOpen.focus();
      report("Native Close reached the S02 mock close guard.");
      void note("close-guard-opened", { mode });
    }).catch(() => null);
  const acceleratorUnlisten = await listen("s02-webview2-accelerator", () => {
    acceleratorReceipt.hidden = false;
    acceleratorReceipt.textContent = "WebView2 AcceleratorKeyPressed intercepted Alt+Space";
    acceleratorReceipt.setAttribute("aria-label", acceleratorReceipt.textContent);
    acceleratorReceipt.dataset.s02Webview2Accelerator = "true";
    void note("webview2-accelerator", { key: "Alt+Space", handled: true });
  }).catch(() => null);

  updateModeControl();
  try {
    await invokeS02("s02_set_menu_mode", { mode });
  } catch (error) {
    report(`Native menu-mode initialization failed: ${String(error)}`);
  }
  const regionObserver = new ResizeObserver(registerHitTestRegions);
  regionObserver.observe(surface);
  regionObserver.observe(titlebar);
  regionObserver.observe(emptyChrome);
  regionObserver.observe(maximize);
  window.addEventListener("resize", registerHitTestRegions);
  requestAnimationFrame(registerHitTestRegions);
  await refreshState();
  const refreshTimer = window.setInterval(() => void refreshState(), 500);
  surface.dataset.s02CaseId = caseId ?? "smoke";
  surface.dataset.s02MenuMode = mode;
  setFrame("ready", { mode });
  void note("s02-ready", { mode });

  return () => {
    window.clearInterval(refreshTimer);
    regionObserver.disconnect();
    window.removeEventListener("resize", registerHitTestRegions);
    if (typeof closeGuardUnlisten === "function") closeGuardUnlisten();
    if (typeof acceleratorUnlisten === "function") acceleratorUnlisten();
    closeMenu(false);
    surface.remove();
  };
}
