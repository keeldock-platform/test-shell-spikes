#!/usr/bin/env bash
set -euo pipefail

action="${1:-}"
profile="${LINUX_DISTRO:-unknown}"
session="${LINUX_SESSION:-unknown}"
profile_slug="${profile,,}"
session_slug="${session,,}"
diagnostics="${SHELL_EVIDENCE_DIR:-evidence}/preflight/linux-${profile_slug}-${session_slug}.json"
mkdir -p "$(dirname "$diagnostics")"
export SHELL_LINUX_SESSION_DIAGNOSTICS="$diagnostics"

record_status() {
  python3 - "$diagnostics" "$profile" "$session" "$1" "$2" <<'PY'
import json, sys
from pathlib import Path
path, profile, session, status, reason = sys.argv[1:]
Path(path).write_text(json.dumps({"distribution": profile, "session": session, "status": status, "reason": reason}, indent=2) + "\n", encoding="utf-8")
PY
}

provision_host() {
  if [[ "$profile" != "Ubuntu 24.04" ]]; then
    record_status "UNVERIFIED" "Only the Ubuntu 24.04 hosted runner is provisioned for this wave."
    return 78
  fi
  if [[ "$session_slug" != "x11" && "$session_slug" != "wayland" ]]; then
    record_status "UNVERIFIED" "The requested display session is not supported."
    return 78
  fi

  bash ci/apt-host.sh update
  bash ci/apt-host.sh install --yes --no-install-recommends \
    at-spi2-core dbus-x11 ffmpeg gnome-shell gnome-session gsettings-desktop-schemas \
    gnome-screenshot=41.0-2build2 libayatana-appindicator3-dev libgtk-3-dev libwebkit2gtk-4.1-dev patchelf \
    python3-pyatspi x11-utils xauth xdotool xvfb

  if [[ "$session_slug" == "wayland" ]]; then
    bash ci/apt-host.sh install --yes --no-install-recommends ydotool ydotoold
    if [[ ! -e /dev/uinput ]]; then
      sudo modprobe uinput || true
    fi
  fi

  python3 ci/probe-runner.py linux

  local gnome_version webkit_version ffmpeg_version package_summary
  local -a package_names
  gnome_version="$(gnome-shell --version | tr -d '\r')"
  webkit_version="$(pkg-config --modversion webkit2gtk-4.1)"
  ffmpeg_version="$(ffmpeg -version | head -n 1)"
  package_names=(at-spi2-core dbus-x11 ffmpeg gnome-shell gnome-session gnome-screenshot libgtk-3-dev libwebkit2gtk-4.1-dev python3-pyatspi xdotool xvfb)
  if [[ "$session_slug" == "wayland" ]]; then package_names+=(ydotool ydotoold); fi
  package_summary="$(dpkg-query -W -f='${binary:Package}=${Version}\n' "${package_names[@]}" 2>/dev/null | sort)"
  python3 - "$diagnostics" "$profile" "$session" "$gnome_version" "$webkit_version" "$ffmpeg_version" "$package_summary" <<'PY'
import json, sys
from pathlib import Path
path, profile, session, gnome, webkit, ffmpeg, packages = sys.argv[1:]
Path(path).write_text(json.dumps({
    "distribution": profile,
    "session": session,
    "status": "PROVISIONED",
    "gnomeShell": gnome,
    "webkitGtk": webkit,
    "ffmpeg": ffmpeg,
    "packages": packages.splitlines(),
    "provisioning": "workflow-installed packages on the ubuntu-24.04 hosted runner",
}, indent=2) + "\n", encoding="utf-8")
PY
}

run_in_session() {
  shift
  if (($# == 0)); then
    echo "usage: $0 run <command> [args...]" >&2
    return 2
  fi
  command -v Xvfb >/dev/null || { record_status "UNVERIFIED" "Xvfb is unavailable"; return 78; }
  command -v gnome-shell >/dev/null || { record_status "UNVERIFIED" "GNOME Shell is unavailable"; return 78; }
  command -v gdbus >/dev/null || { record_status "UNVERIFIED" "D-Bus command-line tools are unavailable"; return 78; }
  command -v xdotool >/dev/null || { record_status "UNVERIFIED" "XTest input driver is unavailable"; return 78; }

  local display runtime_dir outer_x_pid shell_log
  display=":97"
  runtime_dir="${RUNNER_TEMP:-/tmp}/shell-spikes-${session_slug}-runtime"
  shell_log="${SHELL_EVIDENCE_DIR:-evidence}/preflight/gnome-shell-${session_slug}.log"
  mkdir -p "$runtime_dir" "$(dirname "$shell_log")"
  chmod 700 "$runtime_dir"
  # Nested hosted displays have no DRI3 device. Mesa must render in software;
  # retain GLX because GNOME/Mutter needs it even with llvmpipe.
  export LIBGL_ALWAYS_SOFTWARE=1
  export GALLIUM_DRIVER=llvmpipe
  export WEBKIT_DISABLE_DMABUF_RENDERER=1
  export DISPLAY="$display"
  Xvfb "$display" -screen 0 1600x1000x24 -ac +extension RANDR >"${shell_log}.xvfb" 2>&1 &
  outer_x_pid=$!
  trap 'kill "$outer_x_pid" 2>/dev/null || true; wait "$outer_x_pid" 2>/dev/null || true' RETURN
  for _ in {1..40}; do
    if xdpyinfo -display "$display" >/dev/null 2>&1; then break; fi
    sleep 0.25
  done
  xdpyinfo -display "$display" >/dev/null 2>&1 || { record_status "UNVERIFIED" "Nested X server did not start"; return 78; }

  export XDG_RUNTIME_DIR="$runtime_dir"
  export XDG_CURRENT_DESKTOP=GNOME
  export NO_AT_BRIDGE=0
  export GDK_BACKEND="${session_slug}"
  export GDK_SCALE=1
  export SHELL_SESSION="$profile-$session"
  export SHELL_TOOLCHAIN_PYTHON="$(python3 --version 2>&1)"
  export SHELL_DISPLAY_SCALE="1"
  export S03_SCREENSHOT_TOOL="$(command -v gnome-screenshot || true)"
  if [[ "$session_slug" == "wayland" ]]; then
    export XDG_SESSION_TYPE=wayland
    export WAYLAND_DISPLAY=wayland-0
    export MUTTER_DEBUG_DUMMY_MODE_SPECS=1600x1000
    export SHELL_WAYLAND_INPUT_HELPER="kernel uinput through ydotool"
    export S03_WAYLAND_INPUT="$PWD/ci/linux/wayland-input.sh"
    export S03_WAYLAND_INPUT_BACKEND=uinput
    export YDOTOOLD_BIN="$(command -v ydotoold || true)"
    export YDOTOOL_BIN="$(command -v ydotool || true)"
    if [[ -z "$YDOTOOLD_BIN" ]] || ! timeout 5 "$YDOTOOLD_BIN" --help 2>&1 | grep -q -- --socket-path; then
      record_status "UNVERIFIED" "Distro ydotoold lacks the socket-path protocol required by the Wayland input adapter."
      return 78
    fi
    [[ -x "$S03_WAYLAND_INPUT" && -n "$YDOTOOL_BIN" && -e /dev/uinput ]] || {
      record_status "UNVERIFIED" "Wayland requires the uinput device, ydotool client, and input adapter."
      return 78
    }
  else
    export XDG_SESSION_TYPE=x11
    unset WAYLAND_DISPLAY || true
    export SHELL_WAYLAND_INPUT_HELPER=unavailable
  fi

  dbus-run-session -- bash -c '
    set -euo pipefail
    export XDG_SESSION_TYPE="$1"
    export XDG_CURRENT_DESKTOP=GNOME
    export NO_AT_BRIDGE=0
    export GDK_BACKEND="$1"
    log="$2"
    shift 2
    if [[ "$XDG_SESSION_TYPE" == "wayland" ]]; then
      export WAYLAND_DISPLAY=wayland-0
      gnome-shell --nested --wayland --display-server >"$log" 2>&1 &
    else
      gnome-shell --x11 --replace --sm-disable >"$log" 2>&1 &
    fi
    shell_pid=$!
    ready=0
    for _ in {1..120}; do
      if gdbus introspect --session --dest org.gnome.Shell --object-path /org/gnome/Shell >/dev/null 2>&1; then ready=1; break; fi
      if ! kill -0 "$shell_pid" 2>/dev/null; then break; fi
      sleep 0.5
    done
    if [[ "$ready" != 1 ]]; then
      cat "$log" >&2 || true
      kill "$shell_pid" 2>/dev/null || true
      exit 78
    fi
    export SHELL_GNOME_SESSION_READY=1
    export SHELL_GNOME_VERSION="$(gnome-shell --version | tr -d '\''\r'\'')"
    if [[ "$XDG_SESSION_TYPE" == "wayland" ]]; then
      socket="$XDG_RUNTIME_DIR/.ydotool_socket"
      sudo --non-interactive "$YDOTOOLD_BIN" --socket-path="$socket" --socket-own="$(id -u):$(id -g)" --socket-perm=0600 >"${log}.input" 2>&1 &
      input_daemon_pid=$!
      export YDOTOOL_SOCKET="$socket"
      ready=0
      for _ in {1..40}; do
        if [[ -S "$socket" ]] && ydotool key 1:1 1:0 >/dev/null 2>&1; then ready=1; break; fi
        if ! kill -0 "$input_daemon_pid" 2>/dev/null; then break; fi
        sleep 0.25
      done
      if [[ "$ready" != 1 ]]; then
        cat "${log}.input" >&2 || true
        kill "$shell_pid" 2>/dev/null || true
        sudo --non-interactive pkill -x ydotoold 2>/dev/null || true
        exit 78
      fi
    fi
    command="$1"
    shift
    # Ubuntu AT-SPI bindings use the distribution Python. A local wrapper keeps
    # cargo, npm, and the pinned workflow interpreter ahead of system binaries.
    export PATH="$PWD/ci/linux:$PATH"
    set +e
    "$command" "$@"
    status=$?
    kill "$shell_pid" 2>/dev/null || true
    wait "$shell_pid" 2>/dev/null || true
    if [[ "$XDG_SESSION_TYPE" == "wayland" ]]; then sudo --non-interactive pkill -x ydotoold 2>/dev/null || true; fi
    exit "$status"
  ' shell-session "$session_slug" "$shell_log" "$@"
}

case "$action" in
  provision)
    provision_host
    ;;
  run)
    run_in_session "$@"
    ;;
  *)
    echo "usage: $0 provision | run <command> [args...]" >&2
    exit 2
    ;;
esac
