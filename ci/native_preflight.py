"""Collect native display and webview versions without trusting workflow guesses."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from pathlib import Path


def command(arguments: list[str], timeout: int = 15) -> str | None:
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    return (result.stdout + result.stderr).strip()


def first_match(pattern: str, value: str | None, group: int = 1) -> str | None:
    match = re.search(pattern, value or "", re.IGNORECASE | re.MULTILINE)
    return match.group(group).strip() if match else None


def display_linux() -> tuple[dict, dict]:
    raw = command(["xrandr", "--current"])
    resolution = first_match(r"current\s+(\d+\s+x\s+\d+)", raw)
    refresh = first_match(r"^\s+\d+x\d+.*?([0-9.]+)\*", raw)
    compositor = None
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        compositor = command([
            "gdbus", "call", "--session", "--dest", "org.gnome.Mutter.DisplayConfig",
            "--object-path", "/org/gnome/Mutter/DisplayConfig",
            "--method", "org.gnome.Mutter.DisplayConfig.GetCurrentState",
        ])
        active_mode = re.search(r"'(\d+x\d+)@([0-9.]+)'", compositor or "")
        if active_mode:
            resolution = active_mode.group(1)
            refresh = active_mode.group(2)
        else:
            # The outer X server is only a host for nested Mutter; do not report
            # its dimensions as the active Wayland compositor's display.
            resolution = None
            refresh = None
    scale = first_match(r"^Xft\.dpi:\s*([0-9.]+)", command(["xrdb", "-query"]))
    scale_value = round(float(scale) / 96.0, 3) if scale else None
    if scale_value is None and os.environ.get("GDK_SCALE"):
        scale_value = os.environ["GDK_SCALE"]
    return (
        {"resolution": resolution, "scale": scale_value, "refreshHz": refresh, "session": os.environ.get("XDG_SESSION_TYPE")},
        {"xrandr": raw, "mutterDisplayState": compositor},
    )


def display_macos() -> tuple[dict, dict]:
    raw = command(["system_profiler", "SPDisplaysDataType", "-json"], timeout=25)
    resolution = None
    refresh = None
    scale = None
    if raw:
        try:
            data = json.loads(raw)
            adapters = data.get("SPDisplaysDataType", [])
            displays = [item for adapter in adapters for item in adapter.get("spdisplays_ndrvs", [])]
            selected = next((item for item in displays if item.get("spdisplays_main") == "spdisplays_yes"), displays[0] if displays else {})
            resolution = selected.get("spdisplays_resolution")
            refresh = first_match(r"([0-9.]+)\s*Hz", selected.get("spdisplays_refresh_rate", ""))
            pixel_dims = selected.get("spdisplays_pixels")
            if isinstance(pixel_dims, str) and resolution:
                logical = re.findall(r"\d+", resolution)
                pixels = re.findall(r"\d+", pixel_dims)
                if len(logical) >= 2 and len(pixels) >= 2 and int(logical[0]):
                    scale = round(int(pixels[0]) / int(logical[0]), 3)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    webkit = command(["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleVersion", "/System/Library/Frameworks/WebKit.framework/Versions/A/Resources/Info.plist"])
    native = None
    if probe := os.environ.get("SHELL_MAC_DISPLAY_PROBE"):
        try:
            native = json.loads(command([probe, "--probe-only"]) or "null")
            if isinstance(native, dict):
                resolution, scale, refresh = (native.get(key) for key in ("resolution", "scale", "refreshHz"))
        except (ValueError, TypeError):
            pass
    return ({"resolution": resolution, "scale": scale, "refreshHz": refresh}, {"systemProfiler": raw, "nativeDisplay": native, "webkitBuild": webkit})


def display_windows() -> tuple[dict, dict]:
    script = r'''
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.Screen]::PrimaryScreen
$graphics = [System.Drawing.Graphics]::FromHwnd([IntPtr]::Zero)
$dpi = $graphics.DpiX
$graphics.Dispose()
$mode = Get-CimInstance Win32_VideoController | Where-Object { $_.CurrentHorizontalResolution -gt 0 } | Select-Object -First 1
$runtimeRoot = Join-Path ${env:ProgramFiles(x86)} "Microsoft\EdgeWebView\Application"
$runtime = Get-ChildItem $runtimeRoot -Directory -ErrorAction SilentlyContinue | Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
[pscustomobject]@{
  width = $screen.Bounds.Width
  height = $screen.Bounds.Height
  refreshHz = $mode.CurrentRefreshRate
  scale = [math]::Round($dpi / 96.0, 3)
  webview = if ($runtime) { $runtime.Name } else { $null }
  windowsBuild = [System.Environment]::OSVersion.Version.ToString()
} | ConvertTo-Json -Compress
'''
    raw = command(["pwsh", "-NoProfile", "-Command", script])
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    resolution = f"{data['width']}x{data['height']}" if data.get("width") and data.get("height") else None
    return ({"resolution": resolution, "scale": data.get("scale"), "refreshHz": data.get("refreshHz")}, {"windowsNative": data})


def webview_version(target: str) -> tuple[str | None, dict]:
    if target == "linux":
        value = command(["pkg-config", "--modversion", "webkit2gtk-4.1"])
        return value, {"webkit2gtk": value}
    if target == "macos":
        value = command(["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleVersion", "/System/Library/Frameworks/WebKit.framework/Versions/A/Resources/Info.plist"])
        return value, {"webkitFrameworkBuild": value}
    if target == "windows":
        _display, raw = display_windows()
        value = raw.get("windowsNative", {}).get("webview")
        return str(value) if value else None, raw
    if target == "android":
        raw = command(["adb", "shell", "dumpsys", "webviewupdate"])
        value = first_match(r"Current WebView package(?: \(name, version\))?:\s*\(([^,]+),\s*([^)]+)\)", raw, 2)
        return value, {"webviewUpdate": raw}
    if target == "ios":
        device_list = command(["xcrun", "simctl", "list", "devices", "--json"])
        runtime_list = command(["xcrun", "simctl", "list", "runtimes", "--json"])
        runtime_id = None
        device_summary = None
        try:
            devices = json.loads(device_list or "{}").get("devices", {})
            booted = next((device for rows in devices.values() for device in rows if device.get("state") == "Booted"), None)
            runtime_id = next((key for key, rows in devices.items() if booted in rows), None) if booted else None
            if booted:
                device_summary = {
                    key: booted.get(key)
                    for key in ("name", "runtimeIdentifier", "deviceTypeIdentifier", "state")
                    if booted.get(key) is not None
                }
            runtimes = json.loads(runtime_list or "{}").get("runtimes", [])
            selected_runtime = next((item for item in runtimes if item.get("identifier") == runtime_id), None)
            bundle = Path(selected_runtime["bundlePath"]) / "Contents/Resources/RuntimeRoot/System/Library/Frameworks/WebKit.framework/Versions/A/Resources/Info.plist" if selected_runtime and selected_runtime.get("bundlePath") else None
            if bundle and not bundle.is_file():
                bundle = Path(selected_runtime["bundlePath"]) / "Contents/Resources/RuntimeRoot/System/Library/Frameworks/WebKit.framework/Info.plist"
            value = command(["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleVersion", str(bundle)]) if bundle else None
            runtime_summary = {
                key: selected_runtime.get(key)
                for key in ("name", "identifier", "version", "buildversion", "isAvailable")
                if selected_runtime and selected_runtime.get(key) is not None
            }
            return value, {"simulator": device_summary, "simulatorRuntime": runtime_summary, "webkitRuntimeBuild": value}
        except (json.JSONDecodeError, StopIteration, KeyError, TypeError):
            return None, {"simulator": device_summary, "simulatorRuntime": {"identifier": runtime_id}, "webkitRuntimeBuild": None}
    return None, {}


def collect(platform_name: str, evidence_dir: Path) -> dict:
    if platform_name == "linux":
        display, raw_display = display_linux()
    elif platform_name == "macos":
        display, raw_display = display_macos()
    elif platform_name == "windows":
        display, raw_display = display_windows()
    elif platform_name == "android":
        resolution = command(["adb", "shell", "wm", "size"])
        density = command(["adb", "shell", "wm", "density"])
        state = command(["adb", "shell", "dumpsys", "display"])
        resolution_value = first_match(r"Physical size:\s*(\d+x\d+)", resolution) or first_match(r"Override size:\s*(\d+x\d+)", resolution)
        density_value = first_match(r"Physical density:\s*(\d+)", density) or first_match(r"Override density:\s*(\d+)", density)
        refresh = first_match(r"refreshRate\s*=\s*([0-9.]+)", state)
        scale_value = round(int(density_value) / 160.0, 3) if density_value else None
        display = {"resolution": resolution_value, "scale": scale_value, "refreshHz": refresh}
        raw_display = {"wmSize": resolution, "wmDensity": density, "displayState": state}
    elif platform_name == "ios":
        screenshot = evidence_dir / "recorder" / "simulator-display-preflight.png"
        try:
            subprocess.run(["xcrun", "simctl", "io", "booted", "screenshot", str(screenshot)], capture_output=True, timeout=20, check=True)
            with screenshot.open("rb") as stream:
                header = stream.read(24)
            resolution_value = f"{int.from_bytes(header[16:20], 'big')}x{int.from_bytes(header[20:24], 'big')}" if len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n" else None
        except (OSError, subprocess.SubprocessError):
            resolution_value = None
        device_list = command(["xcrun", "simctl", "list", "devices", "--json"])
        runtimes = command(["xcrun", "simctl", "list", "runtimes", "--json"])
        device_summary = None
        runtime_summary = None
        try:
            device_data = json.loads(device_list or "{}").get("devices", {})
            booted = next((device for rows in device_data.values() for device in rows if device.get("state") == "Booted"), None)
            if booted:
                device_summary = {
                    key: booted.get(key)
                    for key in ("name", "runtimeIdentifier", "deviceTypeIdentifier", "state")
                    if booted.get(key) is not None
                }
            runtime_data = json.loads(runtimes or "{}").get("runtimes", [])
            selected = next((item for item in runtime_data if item.get("identifier") == (booted or {}).get("runtimeIdentifier")), None)
            if selected:
                runtime_summary = {
                    key: selected.get(key)
                    for key in ("name", "identifier", "version", "buildversion", "isAvailable")
                    if selected.get(key) is not None
                }
        except (json.JSONDecodeError, TypeError):
            pass
        display = {"resolution": resolution_value, "scale": None, "refreshHz": None}
        raw_display = {"simulatorScreenshot": str(screenshot.relative_to(evidence_dir)), "simulator": device_summary, "runtime": runtime_summary}
    else:
        display, raw_display = {}, {}
    webview, raw_webview = webview_version(platform_name)
    report = {
        "platform": platform_name,
        "display": display,
        "displayStatus": "measured" if all(display.get(key) is not None for key in ("resolution", "scale", "refreshHz")) else "UNVERIFIED",
        "webview": webview,
        "webviewStatus": "measured" if webview else "UNVERIFIED",
        "runnerImage": os.environ.get("ImageOS", "unavailable"),
        "runnerImageVersion": os.environ.get("ImageVersion", "unavailable"),
        "platformVersion": platform.platform(),
        "evidence": {"display": raw_display, "webview": raw_webview},
    }
    path = evidence_dir / "recorder" / "native-preflight.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
