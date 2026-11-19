#!/usr/bin/env bash
set -euo pipefail
if [[ "${SHELL_PACKAGE_ROOT:-}" == 1 && "$EUID" == 0 ]]; then sudo() { "$@"; }; fi
for attempt in 1 2 3; do
  if ((attempt > 1)); then sudo dnf clean metadata; fi
  if ((attempt == 3)); then
    for name in fedora updates; do
      path="/etc/yum.repos.d/$name.repo"
      [[ -f "$path" ]] || continue
      if [[ "$name" == fedora ]]; then base='releases/$releasever/Everything/$basearch/os/';
      else base='updates/$releasever/Everything/$basearch/'; fi
      sudo sed -E -i "s@^metalink=@#metalink=@; s@^#?baseurl=.*@baseurl=https://mirrors.kernel.org/fedora/$base@" "$path"
    done
  fi
  echo "Provisioning Fedora attempt=$attempt packages=$*"
  sudo sed -n -E '/^\[|^metalink=|^baseurl=|^enabled=/p' /etc/yum.repos.d/fedora.repo /etc/yum.repos.d/updates.repo
  if sudo timeout --kill-after=10 600 dnf --refresh --disablerepo=fedora-cisco-openh264 \
      --setopt=install_weak_deps=False --setopt=retries=2 --setopt=timeout=20 "$@"; then
    sudo timeout --kill-after=10 60 dnf repo info || sudo timeout --kill-after=10 60 dnf repoinfo || true
    exit 0
  else status=$?; fi
done
exit "$status"
