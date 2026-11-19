#!/usr/bin/env bash
set -euo pipefail
if [[ "${SHELL_PACKAGE_ROOT:-}" == 1 && "$EUID" == 0 ]]; then sudo() { "$@"; }; fi
for attempt in 1 2 3; do
  if ((attempt > 1)); then sudo dnf clean metadata; fi
  fallback=(--setopt=install_weak_deps=False)
  if ((attempt == 3)); then
    fallback+=(--setopt=fedora.metalink= --setopt=updates.metalink=
      '--setopt=fedora.baseurl=https://mirrors.kernel.org/fedora/releases/$releasever/Everything/$basearch/os/'
      '--setopt=updates.baseurl=https://mirrors.kernel.org/fedora/updates/$releasever/Everything/$basearch/')
  fi
  echo "Provisioning Fedora attempt=$attempt packages=$*"
  # Repo filenames vary between minimal dnf5 images and installed Fedora.
  sudo timeout --kill-after=10 60 dnf "${fallback[@]}" repo info || echo "Fedora repository diagnostic failed on attempt $attempt" >&2
  if sudo timeout --kill-after=10 600 dnf "${fallback[@]}" --refresh --disablerepo=fedora-cisco-openh264 \
      --setopt=retries=2 --setopt=timeout=20 "$@"; then
    sudo timeout --kill-after=10 60 dnf repo info || sudo timeout --kill-after=10 60 dnf repoinfo || true
    exit 0
  else status=$?; fi
done
exit "$status"
