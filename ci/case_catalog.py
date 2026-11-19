"""Explicit case-to-cell map for the one public evidence wave."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Keep platform routing reviewable here. Case text is descriptive evidence, not
# a routing language: each required cell names the exact cases it owns.
CELL_CASES: dict[str, dict[str, tuple[str, ...]]] = {
    "mac-desktop": {
        "s01": ("S01-CAPTURE",),
        "s08": (
            "S08-MAC-01-entry-instance",
            "S08-MAC-02-tool-settings-entry",
            "S08-MAC-03-parented-sheet-and-inactive-main",
            "S08-MAC-04-window-state-and-view-restore",
            "S08-MAC-05-mock-lock-destroys-settings",
            "S08-MAC-06-capability-and-host-allowlist",
        ),
        "s10": ("S10-MACOS-WKWEBVIEW",),
        "s11": (
            "S11-MACOS-LIVE",
            "S11-MACOS-DEFAULT-BRAND-IDENTITY",
            "S11-CONTRAST-BOUNDARY-INJECTION",
            "S11-HIGH-CONTRAST-IGNORES-SYSTEM",
            "S11-POLICY-WEB",
        ),
    },
    "win-desktop": {
        "s02": (
            "S02-WIN-01-native-pointer-open",
            "S02-WIN-02-alt-space-input",
            "S02-WIN-03-alt-space-empty-chrome",
            "S02-WIN-04-app-icon-entry",
            "S02-WIN-05-enabled-items-normal",
            "S02-WIN-06-enabled-items-maximized",
            "S02-WIN-07-native-mouse-command-matrix",
            "S02-WIN-08-native-keyboard-command-matrix",
            "S02-WIN-09-move-and-size-bounds",
            "S02-WIN-10-minimize-and-restore-visibility",
            "S02-WIN-11-negative-control-context",
            "S02-WIN-12-escape-dismissal",
            "S02-WIN-13-snap-windows-2025",
            "S02-WIN-15-native-close-guard-relaunch",
            "S02-WIN-16-kit-fallback-pointer-and-icon",
            "S02-WIN-17-kit-fallback-keyboard",
            "S02-WIN-18-kit-fallback-command-matrix",
            "S02-WIN-19-kit-fallback-close-guard-relaunch",
        ),
        "s10": ("S10-WINDOWS-WEBVIEW2",),
        "s11": ("S11-WINDOWS-LIVE",),
    },
    "win-client": {"s02": ("S02-WIN-14-snap-windows-11-arm",)},
    "linux-ubuntu-24.04-x11": {
        "s03": ("S03-UBUNTU-24.04-X11",),
        "s10": ("S10-LINUX-UBUNTU24-X11-WEBKITGTK",),
    },
    "linux-ubuntu-24.04-wayland": {
        "s03": (
            "S03-UBUNTU-24.04-WAYLAND",
            "S03-UBUNTU-24.04-WAYLAND-KIT-FALLBACK",
        ),
        "s10": ("S10-LINUX-UBUNTU24-WAYLAND-WEBKITGTK",),
        "s11": (
            "S11-LINUX-UBUNTU-24",
            "S11-LINUX-ABSENT-KEY",
            "S11-LINUX-FAULT-FALLBACKS",
            "S11-SYSTEM-UNAVAILABLE-RESOLVES-BRAND",
        ),
    },
    "linux-ubuntu-26.04-x11": {
        "s10": ("S10-LINUX-UBUNTU26-X11-WEBKITGTK",),
    },
    "linux-ubuntu-26.04-wayland": {
        "s10": ("S10-LINUX-UBUNTU26-WAYLAND-WEBKITGTK",),
        "s11": ("S11-LINUX-UBUNTU-26",),
    },
    "linux-fedora-current-x11": {
        "s03": ("S03-FEDORA-CURRENT-X11",),
        "s10": ("S10-LINUX-FEDORA-CURRENT-X11-WEBKITGTK",),
    },
    "linux-fedora-current-wayland": {
        "s03": ("S03-FEDORA-CURRENT-WAYLAND",),
        "s10": ("S10-LINUX-FEDORA-CURRENT-WAYLAND-WEBKITGTK",),
        "s11": ("S11-LINUX-FEDORA-CURRENT",),
    },
    "ios-colour-iphone": {
        "s10": ("S10-IOS-IPHONE-WKWEBVIEW",),
        "s11": ("S11-POLICY-IPHONE",),
    },
    "ios-colour-ipad": {
        "s10": ("S10-IOS-IPAD-WKWEBVIEW",),
        "s11": ("S11-POLICY-IPAD",),
    },
    "android-api-30": {"s11": ("S11-ANDROID-API-30-NEGATIVE",)},
    "android-api-31": {
        "s10": ("S10-ANDROID-API31-SYSTEMWEBVIEW",),
        "s11": (
            "S11-ANDROID-API-31",
            "S11-ANDROID-PROVIDER-UNAVAILABLE",
        ),
    },
    "android-api-35": {
        "s10": ("S10-ANDROID-API35-SYSTEMWEBVIEW",),
        "s11": ("S11-ANDROID-API-35",),
    },
}


def case_ids_for(spike: str, cell: str) -> list[str]:
    """Return the reviewed, explicit case list for one cell and lane."""
    return list(CELL_CASES.get(cell, {}).get(spike, ()))


def assertion_specs_for(spike: str, case_id: str) -> list[dict]:
    """Resolve case-local assertions and top-level string references."""
    path = ROOT / "cases" / f"{spike}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    definitions = {
        item["id"]: item
        for item in data.get("assertions", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    case = next(
        (item for item in data.get("cases", []) if isinstance(item, dict) and item.get("id") == case_id),
        None,
    )
    if case is None:
        return []
    specs: list[dict] = []
    for item in case.get("assertions", []):
        if isinstance(item, str):
            resolved = definitions.get(item)
            if resolved:
                specs.append(dict(resolved))
            else:
                specs.append({"id": item, "expected": "Declared assertion reference", "evidence": []})
        elif isinstance(item, dict):
            specs.append(dict(item))
    return specs


def fallback_for(cell: str, spike: str, case_id: str) -> str:
    """Return the documented planning route when a cell is not proven."""
    if spike == "s01":
        return "Keep traffic lights at the comfortable row-one height; preserve a 34-point first row in compact mode."
    if spike == "s02":
        return "Use the same-item kit system menu with WebView Alt+Space; leave native Snap Layouts unresolved without client evidence."
    if spike == "s03":
        return "Use the same-item kit menu for this distribution and session."
    if spike == "s08":
        return "Use the existing modal Settings presentation on this platform."
    if spike == "s10":
        return "Use a hexadecimal colour field on this platform."
    if spike == "s11":
        if case_id == "S11-POLICY-WEB":
            return "Keep System accent hidden for Web by policy."
        if case_id == "S11-POLICY-IPHONE":
            return "Keep System accent hidden for iPhone by policy."
        if case_id == "S11-POLICY-IPAD":
            return "Keep System accent hidden for iPad by policy."
        return "Hide System accent on this platform; resolve stored System to the synthetic brand accent and retain the reason."
    return "No platform fallback is defined for this assertion."
