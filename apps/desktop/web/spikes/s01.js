// SHELL-SPIKE-01 synthetic controls and neutral capture marker.
// The shared bootstrap supplies `invoke`, `emitEvent`, and `frame`; no product
// client, styles, assets, or network requests are used here.

const COLORS = Object.freeze({ ink: "#333333", muted: "#777777", line: "#b8b8b8", paper: "#f4f4f4" });

function element(tag, attributes = {}, text = undefined) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "style") Object.assign(node.style, value);
    else if (key === "className") node.className = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, String(value));
  }
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(label, onClick) {
  return element("button", {
    type: "button",
    "aria-label": label,
    style: {
      color: COLORS.ink,
      background: "white",
      border: `1px solid ${COLORS.line}`,
      borderRadius: "4px",
      font: "14px system-ui, sans-serif",
      padding: "7px 10px",
      cursor: "default",
    },
    onClick,
  }, label);
}

export function mountS01(root, { invoke, emitEvent, frame, caseId, loadAssetModule }) {
  if (!root || typeof invoke !== "function" || typeof emitEvent !== "function" || typeof frame !== "function") {
    throw new Error("S01 needs the shared invoke, frame, and event-artifact bridges");
  }
  void loadAssetModule;

  const state = { compact: false, capsules: false, fullscreen: false, sequence: 0, visibleSequence: 0, busy: false, nativeEventNs: null, hostUpdateNs: null };
  const invokeS01 = (command, args = {}) => invoke(`plugin:s01-traffic-lights|${command}`, args);
  const surface = element("main", {
    "aria-label": "S01 traffic light positioning probe",
    style: { color: COLORS.ink, background: COLORS.paper, minHeight: "100vh", fontFamily: "system-ui, sans-serif" },
  });
  const titlebar = element("header", {
    "aria-label": "Synthetic two-row title bar",
    style: { position: "fixed", inset: "0 0 auto 0", background: "#fafafa", zIndex: "10", borderBottom: `1px solid ${COLORS.line}` },
  });
  const row1 = element("div", {
    "aria-label": "Row one, traffic light reference",
    style: { height: "34px", boxSizing: "border-box", position: "relative", display: "flex", alignItems: "center", paddingLeft: "90px" },
  });
  const row1Marker = element("div", {
    "aria-hidden": "true",
    style: { position: "absolute", left: "0", right: "0", top: "50%", height: "1px", background: COLORS.muted, opacity: "0.55", pointerEvents: "none" },
  });
  const rowLabel = element("span", {
    style: { color: COLORS.muted, font: "12px system-ui, sans-serif", userSelect: "none" },
  }, "ROW 1 REFERENCE");
  row1.append(row1Marker, rowLabel);
  const row2 = element("div", {
    "aria-label": "Row two reference",
    style: { height: "30px", boxSizing: "border-box", borderTop: `1px solid ${COLORS.line}`, display: "flex", alignItems: "center", paddingLeft: "12px", gap: "8px" },
  }, "ROW 2");
  const marker = element("output", {
    "aria-label": "Visible capture sequence",
    role: "status",
    style: { position: "fixed", right: "8px", top: "8px", zIndex: "20", boxSizing: "border-box", width: "136px", height: "28px", padding: "3px 4px", color: COLORS.ink, background: "white", border: `1px solid ${COLORS.line}`, font: "10px/10px ui-monospace, monospace", display: "grid", gap: "2px" },
  });
  const markerText = element("span", { "aria-hidden": "true" }, "S01 000000 READY");
  const markerBits = element("span", {
    "aria-hidden": "true",
    "data-s01-visible-code": "true",
    style: { display: "flex", gap: "1px", width: "103px", height: "8px", overflow: "hidden" },
  });
  const markerCells = Array.from({ length: 26 }, () => element("span", {
    "aria-hidden": "true",
    style: { display: "block", flex: "0 0 3px", width: "3px", height: "8px", background: "white" },
  }));
  markerBits.append(...markerCells);
  marker.append(markerText, markerBits);
  const controls = element("section", {
    "aria-label": "S01 scenario controls",
    style: { padding: "92px 18px 24px", display: "grid", gap: "12px", maxWidth: "760px" },
  });
  const densityGroup = element("div", { role: "group", "aria-label": "Density", style: { display: "flex", gap: "8px", alignItems: "center" } });
  const layoutGroup = element("div", { role: "group", "aria-label": "Tab layout", style: { display: "flex", gap: "8px", alignItems: "center" } });
  const fullscreenGroup = element("div", { role: "group", "aria-label": "Window state", style: { display: "flex", gap: "8px", alignItems: "center" } });
  const stateText = element("output", { role: "status", style: { font: "14px ui-monospace, monospace", color: COLORS.ink } }, "");
  const receipt = element("pre", {
    "aria-label": "Native AppKit measurement",
    role: "status",
    style: { margin: "0", whiteSpace: "pre-wrap", font: "11px ui-monospace, monospace", color: COLORS.ink, background: "white", padding: "8px", border: `1px solid ${COLORS.line}` },
  }, "Waiting for native measurement");

  function geometry() {
    const row1Height = state.compact ? 30 : 34;
    const row2Height = state.capsules ? 0 : state.compact ? 28 : 30;
    return { row1Height, row2Height, barHeight: row1Height + row2Height };
  }

  function setMarker(phase, sequence = state.visibleSequence) {
    const phaseBits = { ready: 0, applying: 1, settled: 2, error: 3 }[phase] ?? 3;
    const value = sequence & 0xffffff;
    const label = `S01 ${String(sequence).padStart(6, "0")} ${phase.toUpperCase()}`;
    markerText.textContent = label;
    marker.setAttribute("aria-label", label);
    marker.dataset.sequence = String(sequence);
    marker.dataset.phase = phase;
    frame(sequence, phase, { nativeEventNs: state.nativeEventNs, hostUpdateNs: state.hostUpdateNs, spike: "s01", caseId, density: state.compact ? "compact" : "comfortable", layout: state.capsules ? "capsules" : "rows" });
    for (let bit = 0; bit < 24; bit += 1) {
      const enabled = (value & (1 << (23 - bit))) !== 0;
      markerCells[bit].style.background = enabled ? "#111111" : "#ffffff";
    }
    markerCells[24].style.background = (phaseBits & 2) !== 0 ? "#111111" : "#ffffff";
    markerCells[25].style.background = (phaseBits & 1) !== 0 ? "#111111" : "#ffffff";
  }

  function renderState() {
    const { row1Height, row2Height, barHeight } = geometry();
    row1.style.height = `${row1Height}px`;
    row2.style.display = state.capsules ? "none" : "flex";
    row2.style.height = `${row2Height}px`;
    titlebar.style.height = `${barHeight}px`;
    stateText.textContent = `density=${state.compact ? "compact" : "comfortable"}; layout=${state.capsules ? "Team capsules" : "Two rows"}; row1=${row1Height}px; row2=${row2Height}px; total=${barHeight}px; fullscreen=${state.fullscreen}`;
    fullscreenButton.textContent = state.fullscreen ? "Exit full screen" : "Enter full screen";
    fullscreenButton.setAttribute("aria-label", state.fullscreen ? "Exit full screen" : "Enter full screen");
    surface.style.paddingTop = `${barHeight}px`;
  }

  async function record(kind, details = {}) {
    await emitEvent(kind, {
      casePrefix: "S01",
      shellCaseId: caseId,
      sequenceId: state.sequence,
      utc: new Date().toISOString(),
      rendererMonotonicMs: performance.now(),
      density: state.compact ? "compact" : "comfortable",
      tabLayout: state.capsules ? "capsules" : "rows",
      ...geometry(),
      fullscreen: state.fullscreen,
      ...details,
    });
  }

  async function inspect() {
    return invokeS01("s01_inspect_traffic_lights", {
      sequenceId: state.sequence || 1,
      compact: state.compact,
      capsules: state.capsules,
    });
  }

  async function applyGeometry(next) {
    if (state.busy) return;
    state.busy = true;
    state.sequence += 1;
    setMarker("applying");
    const before = { compact: state.compact, capsules: state.capsules, ...geometry() };
    try {
      await record("transition-intent", { before, requested: next });
      // Reposition first, before the new DOM row geometry can be presented.
      // The native call changes only AppKit button y coordinates.
      const native = await invokeS01("s01_reposition_traffic_lights", {
        sequenceId: state.sequence,
        compact: next.compact,
        capsules: next.capsules,
      });
      state.nativeEventNs = native.nativeEventNs;
      state.hostUpdateNs = native.hostUpdateNs;
      await record("native-reposition-returned", { native, requested: next });
      state.compact = next.compact;
      state.capsules = next.capsules;
      state.visibleSequence = state.sequence;
      renderState();
      setMarker("applying");
      receipt.textContent = JSON.stringify(native, null, 2);
      // The recorder correlates this visible marker with its presentation
      // frames; this animation-frame callback is only a marker update.
      requestAnimationFrame(() => {
        state.busy = false;
        renderState();
        setMarker("settled");
        void record("renderer-marker-committed");
      });
    } catch (error) {
      state.busy = false;
      state.visibleSequence = state.sequence;
      setMarker("error");
      receipt.textContent = String(error);
      await record("transition-error", { error: String(error) });
    }
  }

  async function setFullscreen(next) {
    if (state.busy) return;
    state.busy = true;
    state.sequence += 1;
    setMarker("applying");
    try {
      if (!next) {
        // Refresh the target while AppKit keeps the lights hidden, before
        // asking the native window to leave full screen.
        const native = await invokeS01("s01_reposition_traffic_lights", {
          sequenceId: state.sequence,
          compact: state.compact,
          capsules: state.capsules,
        });
        receipt.textContent = JSON.stringify(native, null, 2);
        await record("fullscreen-exit-preposition", { native });
      }
      await record("fullscreen-transition-intent", { requestedFullscreen: next });
      await invokeS01("s01_set_fullscreen", { fullscreen: next });
      await record("fullscreen-requested", { requestedFullscreen: next });
      state.fullscreen = next;
      renderState();
      // XCTest and full-desktop capture independently verify the settled OS
      // state; this timeout only prevents a hung control from looking settled.
      const deadline = performance.now() + 10000;
      let native = await inspect();
      await record("fullscreen-native-state-poll", { native, requestedFullscreen: next });
      state.visibleSequence = state.sequence;
      setMarker("applying");
      while (native.isFullscreen !== next && performance.now() < deadline) {
        await new Promise((resolve) => requestAnimationFrame(resolve));
        native = await inspect();
        await record("fullscreen-native-state-poll", { native, requestedFullscreen: next });
      }
      if (native.isFullscreen !== next) throw new Error("native full-screen state did not settle");
      if (!next) {
        native = await invokeS01("s01_reposition_traffic_lights", {
          sequenceId: state.sequence,
          compact: state.compact,
          capsules: state.capsules,
        });
        receipt.textContent = JSON.stringify(native, null, 2);
      }
      state.nativeEventNs = native.nativeEventNs;
      state.hostUpdateNs = native.hostUpdateNs;
      await record("fullscreen-native-state-settled", { native });
      requestAnimationFrame(() => {
        state.busy = false;
        renderState();
        setMarker("settled");
        void record("renderer-marker-committed");
      });
    } catch (error) {
      state.busy = false;
      state.visibleSequence = state.sequence;
      setMarker("error");
      receipt.textContent = String(error);
      await record("fullscreen-error", { error: String(error) });
    }
  }

  const comfortableButton = button("Comfortable density", () => void applyGeometry({ compact: false, capsules: state.capsules }));
  const compactButton = button("Compact density", () => void applyGeometry({ compact: true, capsules: state.capsules }));
  const rowsButton = button("Two rows", () => void applyGeometry({ compact: state.compact, capsules: false }));
  const capsulesButton = button("Team capsules", () => void applyGeometry({ compact: state.compact, capsules: true }));
  const fullscreenButton = button("Enter full screen", () => void setFullscreen(!state.fullscreen));
  const measureButton = button("Read native measurements", async () => {
    try {
      const native = await inspect();
      receipt.textContent = JSON.stringify(native, null, 2);
      await record("native-inspection", { native });
    } catch (error) {
      receipt.textContent = String(error);
      await record("inspection-error", { error: String(error) });
    }
  });

  densityGroup.append(element("span", {}, "Density:"), comfortableButton, compactButton);
  layoutGroup.append(element("span", {}, "Tab layout:"), rowsButton, capsulesButton);
  fullscreenGroup.append(fullscreenButton, measureButton);
  controls.append(densityGroup, layoutGroup, fullscreenGroup, stateText, receipt);
  surface.append(titlebar, marker, controls);
  root.replaceChildren(surface);
  renderState();

  state.sequence = 1;
  state.busy = true;
  setMarker("applying");
  void invokeS01("s01_inspect_traffic_lights", { sequenceId: state.sequence, compact: false, capsules: false })
    .then(async (creationNative) => {
      await record("creation-position-snapshot", { native: creationNative });
      state.visibleSequence = state.sequence;
      setMarker("applying", state.sequence);
      state.sequence += 1;
      const native = await invokeS01("s01_reposition_traffic_lights", { sequenceId: state.sequence, compact: false, capsules: false });
      await record("creation-position-verified", { native, creationSequence: creationNative.sequenceId });
      state.visibleSequence = state.sequence;
      receipt.textContent = JSON.stringify(native, null, 2);
      state.busy = false;
      renderState();
      setMarker("settled");
    })
    .catch(async (error) => {
      state.busy = false;
      state.visibleSequence = state.sequence;
      setMarker("error");
      receipt.textContent = String(error);
      await record("creation-position-error", { error: String(error) });
    });

  return () => root.replaceChildren();
}

