#!/usr/bin/env bash
# Keep hosted-runner package downloads on Ubuntu's official archive endpoints.
set -euo pipefail
sudo python3 - <<'PY'
from pathlib import Path
import re
for path in [Path('/etc/apt/sources.list'), *Path('/etc/apt/sources.list.d').glob('*.sources'), *Path('/etc/apt/sources.list.d').glob('*.list')]:
    if path.is_file():
        source = path.read_text()
        updated = re.sub(r'https?://(?:[a-z0-9.-]+\.)?archive\.ubuntu\.com/ubuntu/?', 'https://archive.ubuntu.com/ubuntu/', source)
        updated = updated.replace('http://security.ubuntu.com/ubuntu', 'https://security.ubuntu.com/ubuntu')
        if updated != source:
            path.write_text(updated)
        for line in updated.splitlines():
            if 'ubuntu.com/ubuntu' in line:
                print(path.name + ': ' + line, flush=True)
PY
sudo env DEBIAN_FRONTEND=noninteractive timeout "${SHELL_APT_TIMEOUT_SECONDS:-600}" apt-get \
  -o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 \
  "$@"
