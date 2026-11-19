#!/usr/bin/env bash
set -euo pipefail
python3 ci/run-platform.py ios --spikes s10 s11
