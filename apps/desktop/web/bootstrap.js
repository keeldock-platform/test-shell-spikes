import { addPluginListener, invoke } from "./vendor/@tauri-apps/api/core.js";
import { emit, listen } from "./vendor/@tauri-apps/api/event.js";
import { frame, record } from "./frame-marker.js";

const allowedSpikes = new Set(["s01", "s02", "s03", "s08", "s10", "s11"]);
const root = document.querySelector("#spike-root");
const params = new URLSearchParams(window.location.search);
const requested = params.get("spike");
const requestedCase = params.get("case");
let transportSpike = requested;
let transportCase = requestedCase;
const pendingWrites = new Set();
const transportErrors = [];
function persist(type, detail) {
  if (!transportCase) return Promise.resolve();
  const write = invoke("record_renderer_event", {
    payload: JSON.stringify({ type, detail, spike: transportSpike, caseId: transportCase }),
  });
  pendingWrites.add(write);
  write.catch((error) => transportErrors.push(String(error))).finally(() => pendingWrites.delete(write));
  return write;
}
// Producers may emit during registration, so install both listeners before start().
for (const type of ["shell-spike:frame", "shell-spike:event"]) {
  window.addEventListener(type, (event) => { void persist(type, event.detail); });
}
export async function flushRendererEvents() {
  while (pendingWrites.size) await Promise.allSettled([...pendingWrites]);
  if (transportErrors.length) throw new Error(transportErrors.join("; "));
}
window.shellSpikeFlush = flushRendererEvents;
const shutdownListener = listen("shell-spike:shutdown", async () => {
  await flushRendererEvents();
  await persist("shell-spike:shutdown-flushed", {});
});

function scenarioLinks() {
  const nav = document.querySelector("#scenario-list");
  const caseInput = document.querySelector("#case-id");
  for (const id of [...allowedSpikes].sort()) {
    const link = document.createElement("a");
    link.href = `?spike=${encodeURIComponent(id)}`;
    link.textContent = id.toUpperCase();
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const target = new URL(link.href);
      const caseId = caseInput?.value.trim();
      if (caseId) target.searchParams.set("case", caseId);
      void flushRendererEvents().then(() => window.location.assign(target.href));
    });
    nav?.append(link);
  }
}

function loadAssetModule(path) {
  if (typeof path !== "string" || path.startsWith("/") || path.includes(":") || path.split("/").includes("..")) {
    throw new TypeError("asset module path must stay within the renderer root");
  }
  const url = new URL(path, document.baseURI);
  if (url.origin !== window.location.origin) throw new TypeError("cross-origin module denied");
  return import(url.href);
}

async function start() {
  await shutdownListener;
  scenarioLinks();
  let compiled;
  try {
    compiled = await invoke("selected_spike");
  } catch (error) {
    record("host-selection-unavailable", { message: String(error).slice(0, 160) });
    return;
  }
  const id = requested ?? compiled;
  const caseId = requestedCase ?? await invoke("selected_case");
  document.documentElement.dataset.spike = id;
  transportSpike = id;
  transportCase = caseId;
  if (id === "smoke" || !allowedSpikes.has(id)) {
    frame(0, "smoke-ready", { compiled });
    return;
  }
  if (compiled !== "mobile" && compiled !== id) throw new Error(`requested ${id} but host compiled ${compiled}`);

  if (compiled === "mobile" && id === "s11" && /Android/i.test(navigator.userAgent)) {
    const pluginListener = await addPluginListener("s11-accent", "accent-update", (payload) => {
      void emit("s11:accent-update", payload).catch((error) => {
        record("s11-android-event-bridge-failed", { message: String(error).slice(0, 160) });
      });
    });
    window.addEventListener("beforeunload", () => {
      void pluginListener.unregister();
    }, { once: true });
  }

  const module = await loadAssetModule(`./spikes/${id}.js`);
  const context = { root, caseId, invoke, frame, record, loadAssetModule };
  if (typeof module.registerSpike === "function") {
    await module.registerSpike(context);
  } else {
    const legacyName = `mount${id.toUpperCase()}`;
    if (typeof module[legacyName] !== "function") {
      throw new TypeError(`${id} must export registerSpike(context)`);
    }
    await module[legacyName](root, { invoke, emitEvent: record, frame, caseId, loadAssetModule });
  }
  frame(1, "scenario-ready", { spike: id, caseId });
}

start().catch((error) => {
  record("scenario-start-failed", { message: String(error).slice(0, 240) });
  const target = document.querySelector("#spike-root");
  if (target) target.textContent = "Scenario could not start. See recorder output for the failure reason.";
  frame(1, "scenario-failed");
});
