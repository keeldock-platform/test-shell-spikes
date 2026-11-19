const marker = () => document.querySelector("#spike-frame-marker");

// Self-locating, compositor-visible code: eight chromatic sync cells, then
// 24 sequence bits and two phase bits. CSS mutation and marker share one paint.
function visibleCode(sequence, phase) {
  let code = document.querySelector("#presentation-code");
  if (!code) {
    code = document.createElement("div");
    code.id = "presentation-code";
    code.setAttribute("aria-hidden", "true");
    Object.assign(code.style, { position: "fixed", left: "8px", top: "8px", display: "flex",
      width: "136px", height: "16px", zIndex: "2147483647", pointerEvents: "none" });
    for (let bit = 0; bit < 34; bit++) {
      const cell = document.createElement("span");
      Object.assign(cell.style, { flex: "0 0 4px", width: "4px", height: "16px" });
      code.append(cell);
    }
    document.body.append(code);
  }
  const phaseBits = phase === "tokens-mutated" ? 2 : 0;
  const bits = (sequence * 4 + phaseBits).toString(2).padStart(26, "0");
  [...code.children].forEach((cell, bit) => {
    cell.style.background = bit < 8 ? (bit % 2 ? "#00ffff" : "#ff00ff")
      : bits[bit - 8] === "1" ? "#000000" : "#ffffff";
  });
}

export function frame(sequence, phase, fields = {}) {
  const target = marker();
  if (!Number.isSafeInteger(sequence) || sequence < 0 || sequence > 0xffffff) {
    throw new TypeError("frame sequence must be a non-negative safe integer");
  }
  if (document.documentElement.dataset.spike === "s11") visibleCode(sequence, phase);
  const safePhase = String(phase).slice(0, 80);
  if (target) {
    target.textContent = `${safePhase} · ${sequence}`;
    target.dataset.sequence = String(sequence);
    target.dataset.phase = safePhase;
  }
  const detail = { sequence, phase: safePhase, fields, monotonicTime: performance.now() };
  window.dispatchEvent(new CustomEvent("shell-spike:frame", { detail }));
  return detail;
}

export function record(name, fields = {}) {
  window.dispatchEvent(new CustomEvent("shell-spike:event", {
    detail: { name: String(name).slice(0, 100), fields, monotonicTime: performance.now() },
  }));
}
