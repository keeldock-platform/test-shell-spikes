const MENU_ITEMS = [
  { action: "minimize", label: "Minimize" },
  { action: "maximizeOrRestore", label: (state) => state.maximized ? "Restore" : "Maximize" },
  { action: "move", label: "Move" },
  {
    action: "resize",
    label: "Resize",
    supported: false,
    reason: "Resize is unavailable in the S03 kit-menu fallback.",
  },
  { action: "alwaysOnTop", label: "Always on Top", checkable: true },
  { action: "allWorkspaces", label: "Always on Visible Workspace", checkable: true },
  { action: "close", label: "Close" },
];

function node(tag, attributes = {}, text = null) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value === undefined || value === null) continue;
    element.setAttribute(name, String(value));
  }
  if (text !== null) element.textContent = text;
  return element;
}

function rectFor(element) {
  const rect = element.getBoundingClientRect();
  return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
}

export async function registerSpike({ root, caseId, invoke, frame, record }) {
  const invokeS03 = (command, args = {}) =>
    invoke(`plugin:s03-gnome-menu|${command}`, args);
  let frameSequence = 3000;
  let menu = null;
  let opener = null;
  let geometryUpdate = Promise.resolve();

  const shell = node("div", { "data-s03-shell": "true" });
  shell.style.minHeight = "100vh";
  shell.style.fontFamily = "system-ui, sans-serif";
  shell.style.color = "CanvasText";
  shell.style.backgroundColor = "Canvas";

  const header = node("header", { role: "banner", "aria-label": "Window header" });
  header.style.boxSizing = "border-box";
  header.style.height = "56px";
  header.style.display = "grid";
  header.style.gridTemplateColumns = "minmax(180px, 1fr) auto auto";
  header.style.alignItems = "center";
  header.style.gap = "12px";
  header.style.padding = "0 12px";
  header.style.borderBottom = "1px solid GrayText";

  const emptyHeader = node("div", {
    role: "region",
    "aria-label": "Empty header area",
    "data-s03-empty-header": "true",
    tabindex: "0",
  });
  emptyHeader.style.minWidth = "180px";
  emptyHeader.style.height = "40px";

  const tabs = node("div", { role: "tablist", "aria-label": "Synthetic tabs" });
  tabs.style.display = "flex";
  tabs.style.gap = "4px";
  for (const [index, label] of ["Overview", "Activity"].entries()) {
    const tab = node("button", {
      type: "button",
      role: "tab",
      "aria-label": `${label} tab`,
      "aria-selected": index === 0,
      "data-s03-blocker": "tab",
    }, label);
    tabs.append(tab);
  }

  const controls = node("div", { role: "group", "aria-label": "Window controls" });
  controls.style.display = "flex";
  controls.style.gap = "4px";
  const controlSpecs = [
    ["Minimize window", "−", "minimize"],
    ["Maximize window", "□", "maximizeOrRestore"],
    ["Close window", "×", "close"],
  ];
  for (const [label, glyph, action] of controlSpecs) {
    const button = node("button", {
      type: "button",
      "aria-label": label,
      "data-s03-blocker": "control",
    }, glyph);
    button.addEventListener("click", async () => {
      try {
        await invokeS03("perform_fallback_action", { action });
      } catch (error) {
        status.textContent = `${label} was unavailable: ${String(error)}`;
      }
    });
    controls.append(button);
  }

  header.append(emptyHeader, tabs, controls);
  const main = node("main");
  main.style.padding = "24px";
  const title = node("h1", {}, "Generic application window");
  const description = node("p", {}, "Synthetic content for native window-menu checks.");
  const maximize = node("button", { type: "button", "aria-label": "Maximize for menu state check" }, "Maximize test window");
  const useKitFallback = node("button", { type: "button", "aria-label": "Select kit fallback mode" }, "Select kit fallback mode");
  const useNativeMenu = node("button", { type: "button", "aria-label": "Select native menu mode" }, "Select native menu mode");
  const status = node("output", { role: "status", "aria-live": "polite" });
  maximize.addEventListener("click", async () => {
    await invokeS03("set_test_maximized", { maximized: true });
    status.textContent = "Test window maximized.";
    status.setAttribute("aria-label", "Test window maximized");
  });
  useKitFallback.addEventListener("click", async () => {
    await invokeS03("set_menu_mode", { mode: "kit" });
    status.textContent = "Kit fallback selected for the next header secondary-click.";
    status.setAttribute("aria-label", "Kit fallback mode selected");
  });
  useNativeMenu.addEventListener("click", async () => {
    await invokeS03("set_menu_mode", { mode: "native" });
    status.textContent = "Native GNOME menu selected.";
    status.setAttribute("aria-label", "Native menu mode selected");
  });
  main.append(title, description, maximize, useKitFallback, useNativeMenu, status);
  shell.append(header, main);
  root.replaceChildren(shell);

  function updateRegions() {
    const cssToGdkScale = 1;
    const regions = {
      header: rectFor(header),
      blockers: [...header.querySelectorAll("[data-s03-blocker]")].map(rectFor),
      cssToGdkScale,
    };
    let geometryDescription = root.querySelector("#s03-geometry-description");
    if (!geometryDescription) {
      geometryDescription = node("span", { id: "s03-geometry-description", hidden: "" });
      root.append(geometryDescription);
    }
    geometryDescription.textContent = `CSS header bounds ${JSON.stringify(regions.header)}; devicePixelRatio=${window.devicePixelRatio}; cssToGdkScale=${cssToGdkScale}`;
    emptyHeader.setAttribute("aria-describedby", "s03-geometry-description");
    geometryUpdate = geometryUpdate.then(async () => {
      await invokeS03("set_header_regions", { regions });
      record("s03-header-geometry", {
        caseId,
        regions,
        devicePixelRatio: window.devicePixelRatio,
      });
    }).catch((error) => {
      status.textContent = `Header geometry is unavailable: ${String(error)}`;
      record("s03-header-geometry-error", { caseId, message: String(error) });
    });
    return geometryUpdate;
  }

  function closeFallbackMenu(restoreFocus = true) {
    if (!menu) return;
    menu.remove();
    menu = null;
    if (restoreFocus) opener?.focus();
  }

  async function openFallbackAt(x, y, reason) {
    closeFallbackMenu(false);
    opener = document.activeElement instanceof HTMLElement ? document.activeElement : emptyHeader;
    const state = await invokeS03("fallback_window_state");
    const panel = node("div", { role: "menu", "aria-label": "Window actions" });
    panel.tabIndex = -1;
    panel.style.position = "fixed";
    panel.style.left = `${Math.max(0, Math.min(x, window.innerWidth - 260))}px`;
    panel.style.top = `${Math.max(0, Math.min(y, window.innerHeight - 300))}px`;
    panel.style.zIndex = "2147483647";
    panel.style.minWidth = "240px";
    panel.style.padding = "6px";
    panel.style.border = "1px solid GrayText";
    panel.style.backgroundColor = "Canvas";
    panel.style.color = "CanvasText";

    for (const item of MENU_ITEMS) {
      const label = typeof item.label === "function" ? item.label(state) : item.label;
      const button = node("button", {
        type: "button",
        role: item.checkable ? "menuitemcheckbox" : "menuitem",
        "aria-label": label,
        "aria-checked": item.action === "alwaysOnTop" ? state.alwaysOnTop :
          item.action === "allWorkspaces" ? state.allWorkspaces : undefined,
        "aria-disabled": item.supported === false || undefined,
      }, label);
      button.style.display = "block";
      button.style.boxSizing = "border-box";
      button.style.width = "100%";
      button.style.minHeight = "30px";
      button.style.textAlign = "start";
      if (item.supported === false) {
        button.disabled = true;
        button.title = item.reason;
      } else {
        button.addEventListener("click", async () => {
          closeFallbackMenu(false);
          try {
            await invokeS03("perform_fallback_action", { action: item.action });
            status.textContent = `${label} requested.`;
          } catch (error) {
            status.textContent = `${label} was unavailable: ${String(error)}`;
          }
        });
      }
      panel.append(button);
    }

    const limitation = node("p", {}, "Resize is unavailable in this synthetic test shell.");
    limitation.style.fontSize = "12px";
    panel.append(limitation);
    menu = panel;
    root.append(menu);
    menu.focus();
    status.textContent = `Kit fallback menu shown (${reason}).`;
    record("s03-kit-fallback-open", { caseId, x, y, reason });
    frame(frameSequence++, "s03-kit-fallback-open", { caseId, x, y });
  }

  function recordNativeRequest(details) {
    record("s03-native-menu-request", { caseId, ...details });
    frame(frameSequence++, "s03-native-menu-request", { caseId, ...details });
  }

  root.addEventListener("contextmenu", (event) => event.preventDefault(), true);
  root.addEventListener("keydown", (event) => {
    if (!menu) return;
    const items = [...menu.querySelectorAll('[role="menuitem"], [role="menuitemcheckbox"]')]
      .filter((item) => !item.disabled);
    const current = items.indexOf(document.activeElement);
    if (event.key === "Escape") {
      event.preventDefault();
      closeFallbackMenu();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      items[(current + direction + items.length) % items.length]?.focus();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      (event.key === "Home" ? items[0] : items.at(-1))?.focus();
    }
  });

  await invokeS03("set_menu_mode", { mode: "native" });
  await updateRegions();
  new ResizeObserver(updateRegions).observe(header);

  window.s03 = {
    async setMode(mode) { return invokeS03("set_menu_mode", { mode }); },
    async maximize(value) { return invokeS03("set_test_maximized", { maximized: value }); },
    openFallbackAt,
    recordNativeRequest,
  };
  frame(frameSequence++, "s03-ready", { caseId });
  record("s03-ready", { caseId, devicePixelRatio: window.devicePixelRatio });
}
