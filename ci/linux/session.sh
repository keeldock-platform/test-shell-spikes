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
  if [[ "$profile" != "Ubuntu 24.04" && "${SHELL_LINUX_GUEST:-}" != 1 ]]; then
    record_status "UNVERIFIED" "A non-host distribution requires its own provisioned guest."
    return 78
  fi
  if [[ "$session_slug" != "x11" && "$session_slug" != "wayland" ]]; then
    record_status "UNVERIFIED" "The requested display session is not supported."
    return 78
  fi

  local -a packages
  if [[ "$profile" == "Fedora current" ]]; then
    packages=(at-spi2-core dbus-daemon dbus-x11 procps-ng ffmpeg-free gnome-shell gnome-session gjs
      gsettings-desktop-schemas gnome-screenshot gtk3-devel webkit2gtk4.1-devel
      libappindicator-gtk3-devel openssl-devel librsvg2-devel libxdo-devel patchelf
      python3-pyatspi xdpyinfo xprop xrandr xrdb xorg-x11-xauth xdotool xorg-x11-server-Xvfb
      xdg-desktop-portal-gnome metacity)
    if [[ "$session_slug" == "wayland" ]]; then
      packages+=(ydotool pipewire pipewire-utils wireplumber pipewire-gstreamer gstreamer1-plugins-base
        gstreamer1-plugins-good mutter-devkit)
    fi
    printf 'Provisioning resolved package set (%s/%s): %s\n' "$profile" "$session" "${packages[*]}"
    bash ci/dnf-retry.sh repoquery --available "${packages[@]}" | tee "${diagnostics%.json}-packages.txt"
    bash ci/dnf-retry.sh install -y "${packages[@]}"
  else
    bash ci/apt-host.sh update
    screenshot=gnome-screenshot
    if [[ "$profile" == "Ubuntu 24.04" ]]; then screenshot=gnome-screenshot=41.0-2build2; fi
    packages=(at-spi2-core dbus-x11 procps ffmpeg gnome-shell gnome-shell-common gnome-session gjs
      gsettings-desktop-schemas "$screenshot" libssl-dev librsvg2-dev
      libayatana-appindicator3-dev libgtk-3-dev libwebkit2gtk-4.1-dev patchelf
      python3-pyatspi x11-utils x11-xserver-utils xauth xdotool xvfb metacity)
    if [[ "$session_slug" == "wayland" ]]; then
      packages+=(ydotool pipewire wireplumber gstreamer1.0-pipewire gstreamer1.0-plugins-good xdg-desktop-portal-gnome)
      if [[ "$profile" == "Ubuntu 24.04" ]]; then packages+=(ydotoold); else packages+=(mutter-dev-bin); fi
    fi
    printf 'Provisioning resolved package set (%s/%s): %s\n' "$profile" "$session" "${packages[*]}"
    apt-cache policy "${packages[@]}" | tee "${diagnostics%.json}-packages.txt"
    bash ci/apt-host.sh --simulate install --yes --no-install-recommends "${packages[@]}"
    bash ci/apt-host.sh install --yes --no-install-recommends "${packages[@]}"
  fi
  if [[ "$session_slug" == "wayland" && ! -e /dev/uinput ]]; then sudo modprobe uinput || true; fi

  python3 ci/probe-runner.py linux

  local gnome_version webkit_version ffmpeg_version package_summary
  local -a package_names
  gnome_version="$(gnome-shell --version | tr -d '\r')"
  webkit_version="$(pkg-config --modversion webkit2gtk-4.1)"
  ffmpeg_version="$(ffmpeg -version | sed -n '1p')"
  package_names=(at-spi2-core dbus-x11 ffmpeg gnome-shell gnome-session gnome-screenshot libgtk-3-dev libwebkit2gtk-4.1-dev python3-pyatspi xdotool xvfb)
  if [[ "$session_slug" == "wayland" ]]; then
    package_names+=(ydotool)
    if [[ "$profile" == "Ubuntu 24.04" ]]; then package_names+=(ydotoold); fi
  fi
  if [[ "$profile" == "Fedora current" ]]; then
    package_summary="$(rpm -qa | sort)"
    export SHELL_FEDORA_VERSION_ID="$(source /etc/os-release; echo "$VERSION_ID")"
  else
  package_summary="$(dpkg-query -W -f='${binary:Package}=${Version}\n' "${package_names[@]}" 2>/dev/null | sort)"
  fi
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
    "provisioning": "distribution-native packages in the declared host or guest",
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

  if [[ "$profile" == "Fedora current" ]]; then
    export SHELL_FEDORA_VERSION_ID="$(source /etc/os-release; echo "$VERSION_ID")"
  fi
  export XDG_RUNTIME_DIR="$runtime_dir"
  export XDG_CURRENT_DESKTOP=GNOME
  export NO_AT_BRIDGE=0
  export GDK_BACKEND="${session_slug}"
  export GDK_SCALE=1
  if [[ "${SHELL_LINUX_GUEST:-}" == 1 ]]; then export WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1; fi
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
    export SHELL_YDOTOOL_REAL="$(command -v ydotool || true)"
    export YDOTOOL_BIN="$PWD/ci/linux/ydotool-compat.sh"
    # Ubuntu 24.04 ships the older /tmp/.ydotool_socket protocol. Record
    # capabilities and support both protocols instead of skipping the cell.
    timeout 5 "$YDOTOOLD_BIN" --help >"${shell_log}.input-help" 2>&1 || true
    if [[ -z "$YDOTOOLD_BIN" ]]; then
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
    shell_pid=""
    input_daemon_pid=""
    pipewire_pid=""
    wireplumber_pid=""
    screencast_pid=""
    source ci/linux/stop-owned.sh
    stop_capture_services() {
      stop_owned_process "$shell_pid"
      if [[ -n "$input_daemon_pid" ]]; then
        timeout 5 sudo --non-interactive pkill -x ydotoold 2>/dev/null || true
        stop_owned_process "$input_daemon_pid"
      fi
      for process_id in "$screencast_pid" "$wireplumber_pid" "$pipewire_pid"; do
        stop_owned_process "$process_id"
      done
    }
    trap stop_capture_services EXIT
    if [[ "$XDG_SESSION_TYPE" == "wayland" ]]; then
      pipewire >"${log}.pipewire" 2>&1 &
      pipewire_pid=$!
      pipewire_ready=0
      for _ in {1..40}; do
        if timeout 2 pw-cli info 0 >"${log}.pipewire-probe" 2>&1; then pipewire_ready=1; break; fi
        if ! kill -0 "$pipewire_pid" 2>/dev/null; then break; fi
        sleep 0.25
      done
      [[ "$pipewire_ready" == 1 ]] || { cat "${log}.pipewire" "${log}.pipewire-probe" >&2; exit 78; }
      wireplumber >"${log}.wireplumber" 2>&1 &
      wireplumber_pid=$!
      export WAYLAND_DISPLAY=wayland-0
      export SHELL_LINUX_COMPOSITOR=gnome-shell-wayland
      if gnome-shell --help 2>&1 | grep -q -- --devkit; then
        env -u WAYLAND_DISPLAY GDK_BACKEND=x11 gnome-shell --wayland --devkit --unsafe-mode >"$log" 2>&1 &
      else
        env -u WAYLAND_DISPLAY GDK_BACKEND=x11 gnome-shell --nested --wayland --display-server --unsafe-mode >"$log" 2>&1 &
      fi
    else
      if gnome-shell --help 2>&1 | grep -q -- --x11; then
        export SHELL_LINUX_COMPOSITOR=gnome-shell-x11
        gnome-shell --x11 --replace --sm-disable --unsafe-mode >"$log" 2>&1 &
      else
        export SHELL_LINUX_COMPOSITOR=metacity-x11
        echo "GNOME Shell has no X11 backend; using distribution Metacity X11" | tee "${log}.backend"
        metacity --replace --sm-disable >"$log" 2>&1 &
      fi
    fi
    shell_pid=$!
    ready=0
    for _ in {1..120}; do
      if [[ "${SHELL_LINUX_COMPOSITOR:-}" == metacity-x11 ]]; then
        if xprop -root _NET_SUPPORTING_WM_CHECK | grep -q "window id"; then ready=1; break; fi
      elif gdbus introspect --session --dest org.gnome.Shell --object-path /org/gnome/Shell >/dev/null 2>&1; then ready=1; break; fi
      if ! kill -0 "$shell_pid" 2>/dev/null; then break; fi
      sleep 0.5
    done
    if [[ "$ready" != 1 ]]; then
      cat "$log" >&2 || true
      exit 78
    fi
    printf "Session backend=%s; GNOME=%s\n" "${SHELL_LINUX_COMPOSITOR:-gnome-shell-wayland}" "$(gnome-shell --version)" | tee "${log}.backend-version"
    if [[ "$SHELL_LINUX_COMPOSITOR" != metacity-x11 ]]; then
      bash ci/linux/gnome-normal-mode.sh "${log}.normal-mode"
    fi
    export SHELL_LINUX_SESSION_READY=1
    if [[ "$SHELL_LINUX_COMPOSITOR" != metacity-x11 ]]; then export SHELL_GNOME_SESSION_READY=1; fi
    export SHELL_GNOME_VERSION="$(gnome-shell --version | tr -d '\''\r'\'')"
    if [[ "$XDG_SESSION_TYPE" == "wayland" ]]; then
      wayland_socket=""
      for _ in {1..40}; do
        wayland_socket="$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -type s -name "wayland-*" -print | sort | head -n 1)"
        if [[ -n "$wayland_socket" ]]; then break; fi
        sleep 0.25
      done
      [[ -n "$wayland_socket" ]] || { echo "Compositor did not create a Wayland socket" >&2; exit 78; }
      export WAYLAND_DISPLAY="${wayland_socket##*/}"
      printf "Resolved Wayland socket: %s\n" "$WAYLAND_DISPLAY" | tee "${log}.wayland-socket"
      # D-Bus was started before Mutter chose its socket. Activated GTK helpers
      # must receive the resolved display rather than the initial guess.
      dbus-update-activation-environment DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR GDK_BACKEND XDG_SESSION_TYPE XDG_CURRENT_DESKTOP
      printf "DISPLAY=%s WAYLAND_DISPLAY=%s GDK_BACKEND=%s\n" "$DISPLAY" "$WAYLAND_DISPLAY" "$GDK_BACKEND" >"${log}.activation-environment"
      export PATH="/usr/share/gnome-shell:$PATH"
      if [[ -f /usr/share/gnome-shell/org.gnome.Shell.Screencast ]]; then
        gjs -m /usr/share/gnome-shell/org.gnome.Shell.Screencast >"${log}.screencast" 2>&1 &
        screencast_pid=$!
      fi
      ready=0
      for _ in {1..40}; do
        if timeout 3 gdbus introspect --session --dest org.gnome.Shell.Screencast --object-path /org/gnome/Shell/Screencast >"${log}.screencast-probe" 2>&1; then ready=1; break; fi
        sleep 0.25
      done
      if [[ "$ready" != 1 ]]; then
        cat "${log}.screencast" "${log}.screencast-probe" >&2 || true
        exit 78
      fi
      socket="$XDG_RUNTIME_DIR/.ydotool_socket"
      if grep -q -- --socket-path "${log}.input-help"; then
        sudo --non-interactive "$YDOTOOLD_BIN" --socket-path="$socket" --socket-own="$(id -u):$(id -g)" --socket-perm=0600 >"${log}.input" 2>&1 &
      else
        export SHELL_YDOTOOL_LEGACY=1
        socket=/tmp/.ydotool_socket
        sudo --non-interactive "$YDOTOOLD_BIN" >"${log}.input" 2>&1 &
      fi
      input_daemon_pid=$!
      export YDOTOOL_SOCKET="$socket"
      ready=0
      for _ in {1..40}; do
        if [[ -S "$socket" ]]; then sudo --non-interactive chown "$(id -u):$(id -g)" "$socket"; fi
        if [[ -S "$socket" ]] && "$YDOTOOL_BIN" key 1:1 1:0 >/dev/null 2>&1; then ready=1; break; fi
        if ! kill -0 "$input_daemon_pid" 2>/dev/null; then break; fi
        sleep 0.25
      done
      if [[ "$ready" != 1 ]]; then
        cat "${log}.input" >&2 || true
        exit 78
      fi
    fi
    if [[ "$SHELL_LINUX_COMPOSITOR" != metacity-x11 ]]; then
      bash ci/linux/portal-ready.sh "${log}.portal-readiness"
    fi
    command="$1"
    shift
    # Ubuntu AT-SPI bindings use the distribution Python. A local wrapper keeps
    # cargo, npm, and the pinned workflow interpreter ahead of system binaries.
    export PATH="$PWD/ci/linux:$PATH"
    set +e
    "$command" "$@"
    status=$?
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
