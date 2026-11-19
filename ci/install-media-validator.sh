#!/usr/bin/env bash
set -euo pipefail
if ! command -v ffprobe >/dev/null || ! command -v ffmpeg >/dev/null; then
  source /etc/os-release
  [[ "$ID" == ubuntu && "$VERSION_CODENAME" =~ ^[a-z]+$ ]] || exit 78
  media_apt="$(mktemp -d)"
  trap 'sudo rm -rf "$media_apt"' EXIT
  chmod 755 "$media_apt"
  mkdir -p "$media_apt/lists/partial"
  for suite in "$VERSION_CODENAME" "$VERSION_CODENAME-updates" "$VERSION_CODENAME-security"; do
    printf 'deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://archive.ubuntu.com/ubuntu/ %s main universe\n' "$suite"
  done > "$media_apt/sources.list"
  options=(-o "Dir::Etc::sourcelist=$media_apt/sources.list" -o Dir::Etc::sourceparts=-
    -o "Dir::State::lists=$media_apt/lists" -o Acquire::Retries=3 -o Acquire::http::Timeout=20)
  cat "$media_apt/sources.list"
  echo 'Media validator packages: ffmpeg (includes ffprobe)'
  sudo timeout --kill-after=10 180 apt-get "${options[@]}" update --error-on=any
  sudo env DEBIAN_FRONTEND=noninteractive timeout --kill-after=10 180 apt-get "${options[@]}" install --yes --no-install-recommends ffmpeg
fi
command -v ffprobe ffmpeg
ffprobe -version
ffmpeg -version
