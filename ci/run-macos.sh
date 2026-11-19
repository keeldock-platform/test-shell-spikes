#!/usr/bin/env bash
set -euo pipefail
mkdir -p target/native-tests/macos "${SHELL_EVIDENCE_DIR:-evidence}/recorder"
swiftc ci/macos-display.swift -o target/native-tests/macos/display-probe
export SHELL_MAC_DISPLAY_PROBE="$PWD/target/native-tests/macos/display-probe"
"$SHELL_MAC_DISPLAY_PROBE" --configure > "${SHELL_EVIDENCE_DIR:-evidence}/recorder/macos-display.json"
python3 ci/run-platform.py macos --spikes s01 s08 s10 s11
