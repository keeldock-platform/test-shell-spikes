#!/usr/bin/env bash
set -euo pipefail
python3 ci/run-platform.py macos --spikes s01 s08 s10 s11
