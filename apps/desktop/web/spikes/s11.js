import { listen } from "../vendor/@tauri-apps/api/event.js";

const palette = [
  { id: "kit-blue", rgb: "#005FCC" },
  { id: "kit-green", rgb: "#146C43" },
  { id: "kit-purple", rgb: "#663399" },
  { id: "kit-amber", rgb: "#8C5400" },
  { id: "kit-red", rgb: "#A4262C" },
  { id: "kit-teal", rgb: "#006B70" },
  { id: "kit-indigo", rgb: "#4040A0" },
  { id: "kit-slate", rgb: "#405066" },
  { id: "kit-rose", rgb: "#9B315A" },
  { id: "kit-cyan", rgb: "#006D8F" },
];

const testBrand = "#405066";
const highContrastAccent = "#1B1B1B";
const surface = "#FFFFFF";
const processedSequences = new Set();

function element(tag, text, attributes = {}) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, String(value));
  }
  return node;
}

function platformFor(root, caseId) {
  if (root.dataset.platform) return root.dataset.platform;
  const id = String(caseId ?? "").toLowerCase();
  for (const platform of ["macos", "windows", "linux", "android", "ipad", "iphone", "ios", "web"]) {
    if (id.includes(platform)) return platform;
  }
  return "unsupported";
}

function hexToRgb(hex) {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match) return null;
  const value = Number.parseInt(match[1], 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255].map((channel) => channel / 255);
}

function rgbToHex(rgb) {
  const channels = rgb.map((channel) => Math.round(Math.max(0, Math.min(1, channel)) * 255));
  return `#${channels.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
}

function linear(channel) {
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}

function luminance(hex) {
  const rgb = hexToRgb(hex);
  if (!rgb) return null;
  return 0.2126 * linear(rgb[0]) + 0.7152 * linear(rgb[1]) + 0.0722 * linear(rgb[2]);
}

function contrast(a, b) {
  const left = luminance(a);
  const right = luminance(b);
  if (left === null || right === null) return 0;
  return (Math.max(left, right) + 0.05) / (Math.min(left, right) + 0.05);
}

function inkFor(fill) {
  return contrast(fill, "#000000") >= contrast(fill, "#FFFFFF") ? "#000000" : "#FFFFFF";
}

function distance(a, b) {
  const left = hexToRgb(a);
  const right = hexToRgb(b);
  if (!left || !right) return Number.POSITIVE_INFINITY;
  return left.reduce((sum, channel, index) => sum + (channel - right[index]) ** 2, 0);
}

function clampToFixtureKit(rawHex, theme) {
  const minSurface = theme === "high-contrast" ? 7 : 3;
  const minInk = theme === "high-contrast" ? 7 : 4.5;
  const usable = (hex) => contrast(hex, surface) >= minSurface && contrast(hex, inkFor(hex)) >= minInk;
  if (usable(rawHex)) return { fill: rawHex, clamped: false, kitId: null };

  const candidate = palette
    .filter((entry) => usable(entry.rgb))
    .sort((left, right) => distance(rawHex, left.rgb) - distance(rawHex, right.rgb))[0];
  if (!candidate) {
    return { fill: testBrand, clamped: true, kitId: "brand-fallback" };
  }
  return { fill: candidate.rgb, clamped: true, kitId: candidate.id };
}

function isPolicyFixture(caseId) {
  return ["s11-policy-web", "s11-policy-iphone", "s11-policy-ipad"].includes(caseId);
}

function policyPlatform(caseId) {
  if (caseId === "s11-policy-web") return "web";
  if (caseId === "s11-policy-iphone") return "iphone";
  if (caseId === "s11-policy-ipad") return "ipad";
  return "unsupported";
}

export async function registerSpike({ root, caseId, invoke, frame, record }) {
  const normalizedCaseId = String(caseId ?? "").toLowerCase();
  const platform = normalizedCaseId === "s11-high-contrast-ignores-system"
    ? "macos"
    : isPolicyFixture(normalizedCaseId)
      ? policyPlatform(normalizedCaseId)
      : platformFor(root, normalizedCaseId);
  let theme = normalizedCaseId === "s11-high-contrast-ignores-system" ? "high-contrast" : "light";
  const systemSeededCase = normalizedCaseId.endsWith("-live")
    || normalizedCaseId.startsWith("s11-linux-")
    || normalizedCaseId.startsWith("s11-android-api-")
    || normalizedCaseId === "s11-android-provider-unavailable"
    || normalizedCaseId === "s11-system-unavailable-resolves-brand";
  let storedAccent = systemSeededCase ? "system" : "brand";
  let snapshot = { available: false, reason: "reader-not-started", rgb: null, sequence: 0 };
  let latestRawHex = null;

  const heading = element("h1", "System accent host door");
  const status = element("p", "Reading the synthetic host status.", { role: "status" });
  const systemButton = element("button", "Use System accent", { type: "button" });
  const brandButton = element("button", "Use brand accent", { type: "button" });
  const highContrastButton = element("button", "High contrast preview", { type: "button" });
  const accentSample = element("div", "Synthetic accent surface", { "aria-label": "Accent surface sample" });
  const identitySample = element("div", "Identity colour remains independent", { "aria-label": "Identity colour sample" });
  const values = element("pre");
  const readyMarker = element("output", "", { "aria-label": "S11 scenario status", "data-s11-ready": "true" });
  const controls = element("div");
  controls.append(systemButton, brandButton, highContrastButton);
  root.replaceChildren(heading, status, controls, accentSample, identitySample, values);

  systemButton.addEventListener("click", () => {
    storedAccent = "system";
    render("user-selected-system");
  });
  brandButton.addEventListener("click", () => {
    storedAccent = "brand";
    render("user-selected-brand");
  });
  highContrastButton.addEventListener("click", () => {
    theme = "high-contrast";
    render("high-contrast-preview");
  });

  function render(reason) {
    const eligiblePlatform = ["macos", "windows", "linux", "android"].includes(platform);
    const systemVisible = (eligiblePlatform || normalizedCaseId === "s11-contrast-boundary-injection") && snapshot.available;
    systemButton.hidden = !systemVisible;
    const resolvedSource = theme === "high-contrast"
      ? "high-contrast-theme"
      : storedAccent === "system" && systemVisible
        ? "system"
        : "brand";
    const rawHex = snapshot.rgb ? rgbToHex(snapshot.rgb) : null;
    latestRawHex = rawHex;
    const selectedHex = resolvedSource === "system" && rawHex ? rawHex : testBrand;
    const resolved = theme === "high-contrast"
      ? { fill: highContrastAccent, clamped: false, kitId: "high-contrast-theme" }
      : clampToFixtureKit(selectedHex, theme);

    // The fixture exercises the token update through CSSOM; no token is interpolated into markup.
    root.style.setProperty("--test-accent-fill", resolved.fill);
    root.style.setProperty("--test-accent-ink", inkFor(resolved.fill));
    accentSample.style.setProperty("background-color", "var(--test-accent-fill)");
    accentSample.style.setProperty("color", "var(--test-accent-ink)");
    identitySample.style.setProperty("background-color", "#6B5B45");
    identitySample.style.setProperty("color", "#FFFFFF");
    accentSample.dataset.appliedSource = resolvedSource;
    accentSample.dataset.rawSystemAccent = rawHex ?? "unavailable";
    accentSample.dataset.clampTarget = resolved.kitId ?? "none";
    status.textContent = systemVisible
      ? `System is available; stored=${storedAccent}; resolved=${resolvedSource}.`
      : `System is hidden; stored=${storedAccent}; resolved=${resolvedSource}; reason=${snapshot.reason ?? "unsupported-platform"}.`;
    values.textContent = JSON.stringify({
      caseId,
      platform,
      reason,
      available: snapshot.available,
      unavailableReason: snapshot.reason,
      storedAccent,
      systemVisible,
      resolvedSource,
      rawHex,
      appliedHex: getComputedStyle(root).getPropertyValue("--test-accent-fill").trim(),
      clamped: resolved.clamped,
      clampTarget: resolved.kitId,
      surfaceContrast: contrast(resolved.fill, surface),
      inkContrast: contrast(inkFor(resolved.fill), resolved.fill),
      theme,
      identityHex: "#6B5B45",
    }, null, 2);
  }

  function acceptSnapshot(next, source) {
    snapshot = {
      available: next.available === true,
      reason: typeof next.reason === "string" ? next.reason : null,
      rgb: Array.isArray(next.rgb) && next.rgb.length === 3
        && next.rgb.every((value) => Number.isFinite(value) && value >= 0 && value <= 1)
        ? next.rgb
        : null,
      sequence: Number.isSafeInteger(next.sequence) ? next.sequence : 0,
      portalInterfaceVersion: Number.isSafeInteger(next.portalInterfaceVersion)
        ? next.portalInterfaceVersion
        : null,
    };
    if (snapshot.available && snapshot.rgb === null) {
      snapshot = { ...snapshot, available: false, reason: "invalid-native-rgb" };
    }
    render(source);
  }

  function markReady() {
    readyMarker.textContent = `Ready: S11: ${caseId ?? "unselected"}`;
    readyMarker.setAttribute("aria-label", readyMarker.textContent);
    root.append(readyMarker);
  }

  function acceptNativeEvent(event) {
    if (!event || event.nativeEvent !== true || !Number.isSafeInteger(event.sequence)) {
      acceptSnapshot(event ?? { available: false, reason: "invalid-host-event" }, "host-status-update");
      if (event && typeof event.cause === "string") {
        record("s11.reader-status", {
          nativeEvent: false,
          cause: event.cause,
          available: event.available === true,
          reason: event.reason ?? null,
          sequence: Number.isSafeInteger(event.sequence) ? event.sequence : null,
          wallpaperId: event.wallpaperId ?? null,
          resourceArgb: event.resourceArgb ?? null,
          activityGeneration: Number.isSafeInteger(event.activityGeneration) ? event.activityGeneration : null,
          permissionPrompt: event.permissionPrompt === true,
        });
      }
      if (event?.cause === "reader-ready") {
        record("s11.reader-ready", {
          available: event.available === true,
          reason: event.reason ?? null,
          portalInterfaceVersion: event.portalInterfaceVersion ?? null,
        });
      }
      return;
    }
    if (processedSequences.has(event.sequence)) return;
    processedSequences.add(event.sequence);
    const nativeEvent = {
      ...event,
      rgb: event.rgb,
      sequence: event.sequence,
    };
    record("s11.native-event", {
      sequence: event.sequence,
      nativeEventNs: event.nativeEventNs,
      cause: event.cause,
      rgb: event.rgb,
      wallpaperId: event.wallpaperId ?? null,
      resourceArgb: event.resourceArgb ?? null,
      activityGeneration: event.activityGeneration ?? null,
      permissionPrompt: event.permissionPrompt === true,
      portalInterfaceVersion: event.portalInterfaceVersion ?? null,
    });
    acceptSnapshot(nativeEvent, "native-event");
    record("s11.host-and-token-update", {
      sequence: event.sequence,
      hostUpdateNs: event.hostUpdateNs,
      rawHex: latestRawHex,
      appliedHex: getComputedStyle(root).getPropertyValue("--test-accent-fill").trim(),
      clamped: accentSample.dataset.clampTarget !== "none",
      rawSurfaceContrast: latestRawHex ? contrast(latestRawHex, surface) : null,
      rawInkContrast: latestRawHex ? contrast(inkFor(latestRawHex), latestRawHex) : null,
      appliedSurfaceContrast: contrast(
        getComputedStyle(root).getPropertyValue("--test-accent-fill").trim(),
        surface,
      ),
      appliedInkContrast: contrast(
        getComputedStyle(root).getPropertyValue("--test-accent-ink").trim(),
        getComputedStyle(root).getPropertyValue("--test-accent-fill").trim(),
      ),
      clampTarget: accentSample.dataset.clampTarget,
      identityHex: "#6B5B45",
      reload: false,
      wallpaperId: event.wallpaperId ?? null,
      resourceArgb: event.resourceArgb ?? null,
      activityGeneration: event.activityGeneration ?? null,
      permissionPrompt: event.permissionPrompt === true,
    });
    frame(event.sequence, "tokens-mutated", {
      nativeEventNs: event.nativeEventNs,
      hostUpdateNs: event.hostUpdateNs,
      rawHex: latestRawHex,
      appliedHex: getComputedStyle(root).getPropertyValue("--test-accent-fill").trim(),
      cause: event.cause,
    });
  }

  render("initial");

  if (normalizedCaseId === "s11-contrast-boundary-injection") {
    storedAccent = "system";
    const injected = { available: true, reason: null, rgb: [0.91, 0.94, 0.99], sequence: 0 };
    record("s11.boundary-injection", { purpose: "clamp-logic-only", rawHex: "#E8F0FC", nativeEvent: false });
    acceptSnapshot(injected, "boundary-injection-clamp-only");
    frame(0, "boundary-injection-clamp-only", {
      rawHex: "#E8F0FC",
      appliedHex: getComputedStyle(root).getPropertyValue("--test-accent-fill").trim(),
      nativeEvent: false,
    });
    const applied = getComputedStyle(root).getPropertyValue("--test-accent-fill").trim();
    const appliedInk = getComputedStyle(root).getPropertyValue("--test-accent-ink").trim();
    record("s11.clamp-result", {
      rawHex: "#E8F0FC",
      rawSurfaceContrast: contrast("#E8F0FC", surface),
      rawInkContrast: contrast(inkFor("#E8F0FC"), "#E8F0FC"),
      appliedHex: applied,
      appliedSurfaceContrast: contrast(applied, surface),
      appliedInkContrast: contrast(appliedInk, applied),
      clampTarget: accentSample.dataset.clampTarget,
      nativeEvent: false,
    });
    markReady();
    return;
  }

  if (normalizedCaseId === "s11-high-contrast-ignores-system") {
    snapshot = { available: true, reason: null, rgb: [0.02, 0.12, 0.85], sequence: 0 };
    storedAccent = "system";
    render("high-contrast-system-ignored");
    record("s11.high-contrast-ignored-system", {
      storedAccent,
      systemRaw: "#051FD9",
      appliedHex: getComputedStyle(root).getPropertyValue("--test-accent-fill").trim(),
      appliedInk: getComputedStyle(root).getPropertyValue("--test-accent-ink").trim(),
      fillContrast: contrast(getComputedStyle(root).getPropertyValue("--test-accent-fill").trim(), surface),
      inkContrast: contrast(
        getComputedStyle(root).getPropertyValue("--test-accent-ink").trim(),
        getComputedStyle(root).getPropertyValue("--test-accent-fill").trim(),
      ),
      resolvedSource: accentSample.dataset.appliedSource,
      sampleKind: "fixture-only",
      nativeEvent: false,
    });
    frame(0, "high-contrast-system-ignored", {
      resolvedSource: accentSample.dataset.appliedSource,
      appliedHex: getComputedStyle(root).getPropertyValue("--test-accent-fill").trim(),
      nativeEvent: false,
    });
    markReady();
    return;
  }

  if (isPolicyFixture(normalizedCaseId)) {
    snapshot = { available: false, reason: "policy-no-system-accent", rgb: null, sequence: 0 };
    storedAccent = "system";
    render("platform-policy-fixture");
    record("s11.platform-policy", { platform, systemVisible: systemButton.hidden === false, storedAccent, resolvedSource: accentSample.dataset.appliedSource });
    frame(0, "platform-policy-fixture", { platform, systemVisible: systemButton.hidden === false });
    markReady();
    return;
  }

  const stopListening = await listen("s11:accent-update", ({ payload }) => acceptNativeEvent(payload));
  record("s11.listener-ready", { caseId, platform });
  try {
    const initial = await invoke("plugin:s11-accent|current_accent", {});
    acceptSnapshot(initial, "initial-reader-snapshot");
    record("s11.initial-reader-snapshot", {
      sequence: initial.sequence ?? 0,
      nativeEvent: false,
      available: snapshot.available,
      reason: snapshot.reason,
      portalInterfaceVersion: snapshot.portalInterfaceVersion,
      rgb: snapshot.rgb,
      wallpaperId: initial.wallpaperId ?? null,
      resourceArgb: initial.resourceArgb ?? null,
      activityGeneration: initial.activityGeneration ?? null,
    });
    frame(0, "initial-token-state", {
      available: snapshot.available,
      reason: snapshot.reason,
      appliedHex: getComputedStyle(root).getPropertyValue("--test-accent-fill").trim(),
    });
  } catch (_error) {
    acceptSnapshot({ available: false, reason: "host-command-unavailable", rgb: null, sequence: 0 }, "host-command-fallback");
  }

  markReady();
  window.addEventListener("beforeunload", () => {
    void stopListening();
  }, { once: true });
}
