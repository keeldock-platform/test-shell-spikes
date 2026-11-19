const INITIAL_COLOUR = "#336699";
const LIGHT_SURFACE_LUMINANCE = 1;
const DARK_SURFACE_LUMINANCE = 0.0049;
const EVENT_LOG_LIMIT = 48;
const NATIVE_COLOUR_PATTERN = /^#[0-9a-fA-F]{6}$/;

function makeElement(document, tagName, attributes = {}, children = []) {
  const element = document.createElement(tagName);
  for (const [name, value] of Object.entries(attributes)) {
    if (typeof value === "boolean") {
      if (value) {
        element.setAttribute(name, "");
      }
    } else {
      element.setAttribute(name, String(value));
    }
  }
  for (const child of children) {
    element.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return element;
}

function buildPageContent(document) {
  const appearanceOutput = makeElement(document, "output", {
    id: "appearance-value",
    "aria-label": "Committed Appearance colour"
  }, [INITIAL_COLOUR]);
  const draftOutput = makeElement(document, "output", { id: "draft-value" }, [INITIAL_COLOUR]);
  const applyButton = makeElement(document, "button", {
    id: "apply-colour",
    type: "button",
    disabled: true
  }, ["Apply"]);

  const dialog = makeElement(document, "dialog", {
    id: "appearance-dialog",
    "aria-labelledby": "appearance-title"
  }, [
    makeElement(document, "h2", { id: "appearance-title" }, ["Appearance colour"]),
    makeElement(document, "p", {}, ["Sample entity: Synthetic sample"]),
    makeElement(document, "p", {}, ["Draft Appearance colour: ", draftOutput]),
    makeElement(document, "label", { for: "native-colour" }, ["Custom colour picker"]),
    makeElement(document, "input", {
      id: "native-colour",
      type: "color",
      value: INITIAL_COLOUR,
      autofocus: true
    }),
    makeElement(document, "p", { id: "picker-help" }, ["Activate this control to open the platform colour picker."]),
    makeElement(document, "label", { for: "hex-value" }, ["HEX"]),
    makeElement(document, "input", {
      id: "hex-value",
      type: "text",
      maxlength: 7,
      autocomplete: "off",
      autocapitalize: "characters",
      spellcheck: "false",
      "aria-describedby": "hex-help hex-error",
      "aria-invalid": "false"
    }),
    makeElement(document, "p", { id: "hex-help" }, ["Enter three or six hexadecimal digits, with an optional leading #."]),
    makeElement(document, "p", { id: "hex-error", role: "alert", hidden: true }),
    makeElement(document, "button", { id: "use-hex", type: "button" }, ["Use HEX value"]),
    makeElement(document, "p", { id: "contrast-warning", role: "status", "aria-live": "polite" }),
    makeElement(document, "output", { id: "focus-status", role: "status", "aria-live": "polite" }, ["Webview focus target: none"]),
    makeElement(document, "div", {}, [
      applyButton,
      makeElement(document, "button", { id: "cancel-colour", type: "button" }, ["Cancel"])
    ]),
    makeElement(document, "h3", {}, ["Input and change event log"]),
    makeElement(document, "ol", {
      id: "event-log",
      "aria-label": "Input and change event log",
      "aria-live": "polite",
      "aria-relevant": "additions"
    })
  ]);

  return makeElement(document, "section", { "aria-labelledby": "s10-heading" }, [
    makeElement(document, "h1", { id: "s10-heading" }, ["Native colour input probe"]),
    makeElement(document, "p", {}, ["This synthetic page measures native webview colour input behaviour. It stores no data and makes no network requests."]),
    makeElement(document, "p", {}, ["Committed Appearance colour: ", appearanceOutput]),
    makeElement(document, "button", { id: "open-appearance", type: "button" }, ["Open Appearance dialog"]),
    makeElement(document, "output", {
      id: "colour-event-marker",
      "aria-label": "Latest colour probe event",
      "data-sequence": "0",
      "data-phase": "ready"
    }, ["Ready"]),
    dialog
  ]);
}

function normalizeNativeColour(value) {
  if (typeof value !== "string" || !NATIVE_COLOUR_PATTERN.test(value)) {
    return null;
  }
  return value.toLowerCase();
}

function parseManualHex(value) {
  if (typeof value !== "string") {
    return null;
  }

  let digits = value.trim();
  if (digits.startsWith("#")) {
    digits = digits.slice(1);
  }

  if (/^[0-9a-fA-F]{3}$/.test(digits)) {
    return ("#" + digits[0] + digits[0] + digits[1] + digits[1] + digits[2] + digits[2]).toLowerCase();
  }
  if (/^[0-9a-fA-F]{6}$/.test(digits)) {
    return ("#" + digits).toLowerCase();
  }
  return null;
}

function channelToLinear(channel) {
  const value = channel / 255;
  if (value <= 0.04045) {
    return value / 12.92;
  }
  return ((value + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(colour) {
  const digits = colour.slice(1);
  const red = channelToLinear(Number.parseInt(digits.slice(0, 2), 16));
  const green = channelToLinear(Number.parseInt(digits.slice(2, 4), 16));
  const blue = channelToLinear(Number.parseInt(digits.slice(4, 6), 16));
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrastRatio(first, second) {
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}

function floorOneDecimal(value) {
  return (Math.floor(value * 10) / 10).toFixed(1);
}

export function mountColourPage(root, options = {}) {
  if (!root || typeof root.replaceChildren !== "function") {
    throw new TypeError("S10 requires a DOM mount point.");
  }

  const document = root.ownerDocument;
  const view = document.defaultView;
  root.replaceChildren(buildPageContent(document));

  const openButton = root.querySelector("#open-appearance");
  const dialog = root.querySelector("#appearance-dialog");
  const appearanceOutput = root.querySelector("#appearance-value");
  const draftOutput = root.querySelector("#draft-value");
  const colourInput = root.querySelector("#native-colour");
  const hexInput = root.querySelector("#hex-value");
  const hexError = root.querySelector("#hex-error");
  const useHexButton = root.querySelector("#use-hex");
  const warningOutput = root.querySelector("#contrast-warning");
  const focusOutput = root.querySelector("#focus-status");
  const eventLog = root.querySelector("#event-log");
  const marker = root.querySelector("#colour-event-marker");
  const applyButton = root.querySelector("#apply-colour");
  const cancelButton = root.querySelector("#cancel-colour");
  const cleanupCallbacks = [];

  let committedColour = INITIAL_COLOUR;
  let draftColour = INITIAL_COLOUR;
  let eventSequence = 0;
  let frameSequence = 0;

  function listen(target, eventName, handler) {
    target.addEventListener(eventName, handler);
    cleanupCallbacks.push(function removeListener() {
      target.removeEventListener(eventName, handler);
    });
  }

  function emit(name, fields = {}) {
    eventSequence += 1;
    const eventFields = Object.assign({}, fields);
    if (options.caseId) {
      eventFields.caseId = options.caseId;
    }

    const phase = "s10-" + name;
    frameSequence += 1;
    marker.dataset.sequence = String(frameSequence);
    marker.dataset.phase = phase;
    marker.textContent = name === "ready"
      ? "Ready: S10: " + (options.caseId || "unselected")
      : "Event " + frameSequence + ": " + name;
    marker.setAttribute("aria-label", marker.textContent);

    if (typeof options.frame === "function") {
      options.frame(frameSequence, phase, eventFields);
    } else {
      root.dispatchEvent(new view.CustomEvent("shell-spike:frame", {
        bubbles: true,
        detail: {
          sequence: frameSequence,
          phase: phase,
          fields: eventFields,
          monotonicTime: view.performance.now()
        }
      }));
    }

    if (typeof options.record === "function") {
      options.record(phase, eventFields);
    } else {
      root.dispatchEvent(new view.CustomEvent("shell-spike:event", {
        bubbles: true,
        detail: { name: phase, fields: eventFields }
      }));
    }

    const item = document.createElement("li");
    const valueText = typeof eventFields.value === "string" ? " " + eventFields.value : "";
    item.textContent = eventSequence + " " + name + valueText;
    eventLog.append(item);
    while (eventLog.children.length > EVENT_LOG_LIMIT) {
      eventLog.firstElementChild.remove();
    }
  }

  function setValidationError(message) {
    hexInput.setAttribute("aria-invalid", "true");
    hexError.textContent = message;
    hexError.hidden = false;
  }

  function clearValidationError() {
    hexInput.setAttribute("aria-invalid", "false");
    hexError.textContent = "";
    hexError.hidden = true;
  }

  function updateContrastWarning(colour) {
    const luminance = relativeLuminance(colour);
    const lightRatio = contrastRatio(luminance, LIGHT_SURFACE_LUMINANCE);
    const darkRatio = contrastRatio(luminance, DARK_SURFACE_LUMINANCE);
    const warnings = [];

    if (lightRatio < 3) {
      warnings.push("light theme " + floorOneDecimal(lightRatio) + ":1");
    }
    if (darkRatio < 3) {
      warnings.push("dark theme " + floorOneDecimal(darkRatio) + ":1");
    }

    if (warnings.length > 0) {
      warningOutput.textContent = "Contrast warning below 3:1: " + warnings.join(", ") + ". The chosen colour is kept unchanged.";
    } else {
      warningOutput.textContent = "The chosen colour is at least 3:1 against both theme surfaces.";
    }
  }

  function refreshDraftControls() {
    draftOutput.textContent = draftColour;
    applyButton.disabled = draftColour === committedColour;
    updateContrastWarning(draftColour);
  }

  function setFocusStatus() {
    const active = document.activeElement;
    let target = "outside the Appearance dialog";
    if (active === colourInput) {
      target = "Custom colour picker";
    } else if (active === hexInput) {
      target = "HEX";
    } else if (active === applyButton) {
      target = "Apply";
    } else if (active === cancelButton) {
      target = "Cancel";
    } else if (active === openButton) {
      target = "Open Appearance dialog";
    }

    focusOutput.textContent = "Webview focus target: " + target;
    emit("focus", { target: target });
  }

  function updateFromNativeEvent(eventName) {
    const returnedColour = normalizeNativeColour(colourInput.value);
    if (!returnedColour) {
      setValidationError("The native picker did not return a six-digit hexadecimal colour.");
      emit("native-" + eventName, { valid: false });
      return;
    }

    if (eventName === "input") {
      emit("native-input", { valid: true, value: returnedColour });
      return;
    }

    draftColour = returnedColour;
    hexInput.value = returnedColour;
    clearValidationError();
    refreshDraftControls();
    emit("native-change", { valid: true, value: returnedColour });
  }

  function commitManualHex() {
    const parsedColour = parseManualHex(hexInput.value);
    if (!parsedColour) {
      setValidationError("Enter a colour like #6366F1 or 636. Use three or six hexadecimal digits.");
      emit("hex-invalid", { valid: false });
      return false;
    }

    const changed = parsedColour !== draftColour;
    draftColour = parsedColour;
    colourInput.value = parsedColour;
    hexInput.value = parsedColour;
    clearValidationError();
    refreshDraftControls();
    emit("hex-commit", { valid: true, value: parsedColour, changed: changed });
    return true;
  }

  function openAppearanceDialog() {
    draftColour = committedColour;
    // Reopen from committed state so a dismissed native picker cannot seed the next edit.
    colourInput.value = draftColour;
    hexInput.value = draftColour;
    clearValidationError();
    refreshDraftControls();
    dialog.showModal();
    emit("appearance-opened", { value: committedColour });
  }

  function applyAppearanceColour() {
    const acceptedColour = normalizeNativeColour(draftColour);
    if (!acceptedColour || acceptedColour !== draftColour) {
      setValidationError("Choose a valid six-digit hexadecimal colour before applying.");
      return;
    }

    committedColour = acceptedColour;
    appearanceOutput.textContent = committedColour;
    refreshDraftControls();
    emit("appearance-applied", { value: committedColour });
    dialog.close("apply");
  }

  function cancelAppearanceColour() {
    draftColour = committedColour;
    colourInput.value = committedColour;
    hexInput.value = committedColour;
    clearValidationError();
    refreshDraftControls();
    emit("appearance-cancelled", { value: committedColour });
    if (dialog.open) {
      dialog.close("cancel");
    }
  }

  function validateManualHexWithoutCommitting() {
    if (!parseManualHex(hexInput.value)) {
      setValidationError("Enter a colour like #6366F1 or 636. Use three or six hexadecimal digits.");
      emit("hex-invalid", { valid: false });
      return;
    }
    clearValidationError();
    emit("hex-valid", { valid: true });
  }

  listen(openButton, "click", openAppearanceDialog);
  listen(colourInput, "input", function onNativeInput() {
    updateFromNativeEvent("input");
  });
  listen(colourInput, "change", function onNativeChange() {
    updateFromNativeEvent("change");
  });
  listen(hexInput, "input", validateManualHexWithoutCommitting);
  listen(hexInput, "keydown", function onHexKeydown(event) {
    if (event.key === "Enter") {
      event.preventDefault();
      commitManualHex();
    }
  });
  listen(hexInput, "blur", function onHexBlur(event) {
    if (hexInput.value.trim() === "") {
      return;
    }
    if (parseManualHex(hexInput.value)) {
      if (parseManualHex(hexInput.value) !== draftColour &&
          event.relatedTarget !== useHexButton &&
          event.relatedTarget !== cancelButton) {
        commitManualHex();
      }
    } else {
      validateManualHexWithoutCommitting();
    }
  });
  listen(useHexButton, "click", commitManualHex);
  listen(applyButton, "click", applyAppearanceColour);
  listen(cancelButton, "click", cancelAppearanceColour);
  listen(dialog, "cancel", function onDialogCancel(event) {
    event.preventDefault();
    cancelAppearanceColour();
  });
  listen(root, "focusin", setFocusStatus);
  listen(view, "focus", function onWindowFocus() {
    setFocusStatus();
    emit("window-focus", {});
  });

  appearanceOutput.textContent = committedColour;
  draftOutput.textContent = draftColour;
  hexInput.value = INITIAL_COLOUR;
  refreshDraftControls();
  emit("ready", { value: committedColour });

  return function unmountColourPage() {
    for (const removeListener of cleanupCallbacks) {
      removeListener();
    }
    root.replaceChildren();
  };
}

const standaloneMount = typeof document === "undefined"
  ? null
  : document.getElementById("colour-probe-mount");
if (standaloneMount) {
  mountColourPage(standaloneMount);
}

