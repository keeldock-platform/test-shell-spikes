#!/usr/bin/env bash
set -euo pipefail
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  brew install ffmpeg
fi
ffmpeg -version
ffprobe -version
