#!/usr/bin/env bash
# Run the requested distribution's own GNOME/WebKit packages, never relabel Ubuntu 24.04.
set -euo pipefail
case "${LINUX_DISTRO:-}" in
  'Ubuntu 26.04') image=ubuntu:26.04 ;;
  'Fedora current') image=fedora:latest ;;
  *) echo 'Unsupported guest distribution' >&2; exit 78 ;;
esac
out="${SHELL_EVIDENCE_DIR:-evidence}/preflight"
mkdir -p "$out"
sudo modprobe uinput || true
docker pull "$image"
docker image inspect "$image" > "$out/linux-guest-image.json"
node_dir="$(dirname "$(command -v node)")"
args=(--rm --privileged --shm-size=2g -v "$PWD:$PWD" -w "$PWD"
  -v /run/udev:/run/udev:ro
  -v /opt/hostedtoolcache:/opt/hostedtoolcache:ro
  -v "$HOME/.rustup:/toolchain/rustup:ro" -v "$HOME/.cargo:/toolchain/cargo"
  -e SHELL_LINUX_GUEST=1 -e RUSTUP_HOME=/toolchain/rustup -e CARGO_HOME=/toolchain/cargo
  -e "PATH=$node_dir:/toolchain/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e "GIT_CONFIG_VALUE_0=$PWD")
for name in LINUX_DISTRO LINUX_SESSION SHELL_CELL SHELL_SESSION SHELL_EVIDENCE_DIR FROZEN_SHA \
  GITHUB_ACTIONS GITHUB_REF GITHUB_REF_TYPE GITHUB_RUN_NUMBER GITHUB_RUN_ATTEMPT GITHUB_RUN_ID RUNNER_NAME ImageOS ImageVersion; do
  args+=(-e "$name")
done
docker run "${args[@]}" "$image" bash -c '
  set -euo pipefail
  if command -v apt-get >/dev/null; then
    export SHELL_PACKAGE_ROOT=1
    bash ci/apt-host.sh update
    packages=(sudo python3 git ca-certificates build-essential curl pkg-config)
    printf "Guest bootstrap packages: %s\n" "${packages[*]}"
    apt-cache policy "${packages[@]}" | tee evidence/preflight/linux-bootstrap-packages.txt
    bash ci/apt-host.sh install -y --no-install-recommends "${packages[@]}"
  else
    export SHELL_PACKAGE_ROOT=1
    packages=(sudo python3 git ca-certificates gcc gcc-c++ make curl-minimal pkgconf-pkg-config)
    printf "Guest bootstrap packages: %s\n" "${packages[*]}"
    bash ci/dnf-retry.sh repoquery --available "${packages[@]}" | tee evidence/preflight/linux-bootstrap-packages.txt
    bash ci/dnf-retry.sh install -y "${packages[@]}"
  fi
  # A private system bus supports GNOME services inside the container.
  mkdir -p /run/dbus
  bash ci/linux/session.sh provision
  dbus-uuidgen --ensure
  dbus-uuidgen --ensure=/etc/machine-id
  dbus-daemon --system --fork
  bash ci/linux/session.sh run python3 ci/run-platform.py linux --spikes s03 s10 s11
'
