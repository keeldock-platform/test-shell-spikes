#!/usr/bin/env bash
# Keep hosted-runner package downloads on Ubuntu's official archive endpoints.
set -euo pipefail
sudo python3 - <<'PY'
from pathlib import Path
import re
for path in [Path('/etc/apt/sources.list'), *Path('/etc/apt/sources.list.d').glob('*.sources'), *Path('/etc/apt/sources.list.d').glob('*.list')]:
    if path.is_file():
        source = path.read_text()
        source = source.replace('mirror+file:/etc/apt/apt-mirrors.txt', 'https://archive.ubuntu.com/ubuntu/')
        source = source.replace('mirror+file:/etc/apt/apt-security-mirrors.txt', 'https://security.ubuntu.com/ubuntu/')
        updated = re.sub(r'https?://(?:[a-z0-9.-]+\.)?archive\.ubuntu\.com/ubuntu/?', 'https://archive.ubuntu.com/ubuntu/', source)
        updated = updated.replace('http://security.ubuntu.com/ubuntu', 'https://security.ubuntu.com/ubuntu')
        if updated != path.read_text():
            path.write_text(updated)
        for line in updated.splitlines():
            if 'ubuntu.com/ubuntu' in line:
                print(path.name + ': ' + line, flush=True)
PY
attempts="${SHELL_APT_ATTEMPTS:-2}"
[[ "$attempts" =~ ^[1-3]$ ]] || { echo "apt attempts must be 1..3" >&2; exit 2; }
for ((attempt=1; attempt<=attempts; attempt++)); do
  if sudo env DEBIAN_FRONTEND=noninteractive timeout --kill-after=10 "${SHELL_APT_TIMEOUT_SECONDS:-600}" apt-get \
    -o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 \
    -o Acquire::Languages=none "$@"; then
    exit 0
  else
    status=$?
  fi
  echo "apt attempt $attempt/$attempts failed with status $status" >&2
done
exit "$status"
