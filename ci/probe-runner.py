#!/usr/bin/env python3
"""Cheap, read-only tool inventory before platform builds and cases."""
import os
import platform
import shutil
import subprocess
import sys

print(f"platform={platform.platform()} architecture={platform.machine()}", flush=True)
for key in ("ImageOS", "ImageVersion", "PATH", "ANDROID_HOME", "ANDROID_SDK_ROOT", "JAVA_HOME", "DEVELOPER_DIR"):
    print(f"{key}={os.environ.get(key, 'unset')}", flush=True)
commands = [["node", "--version"], ["npm", "--version"], ["rustc", "--version"], ["cargo", "--version"], [sys.executable, "--version"]]
target = sys.argv[1]
if target in ("macos", "ios"):
    commands += [["xcode-select", "-p"], ["xcodebuild", "-version"], ["xcrun", "--find", "simctl"], ["ffmpeg", "-version"]]
if target == "ios":
    commands += [["xcrun", "simctl", "list", "runtimes", "--json"], ["xcrun", "simctl", "list", "devices", "available", "--json"]]
if target == "windows":
    commands += [["ffmpeg", "-version"], ["ffprobe", "-version"]]
if target == "android":
    commands += [["java", "-version"], ["sdkmanager", "--version"], ["avdmanager", "list", "device"], ["adb", "--version"], ["emulator", "-version"], ["emulator", "-accel-check"]]
if target == "linux":
    commands += [["gnome-shell", "--version"], ["pkg-config", "--modversion", "webkit2gtk-4.1"], ["ffmpeg", "-version"]]
for command in commands:
    resolved = shutil.which(command[0])
    print(f"$ {command!r} resolved={resolved}", flush=True)
    if resolved:
        try:
            result = subprocess.run([resolved, *command[1:]], timeout=60, check=False)
            print(f"exit={result.returncode}", flush=True)
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"probe error: {error}", flush=True)
# The inventory is diagnostic; platform preflights enforce required tools.
