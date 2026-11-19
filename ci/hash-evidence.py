#!/usr/bin/env python3
"""Copy final upload bytes into a sealed snapshot, then hash that snapshot."""
import os
from pathlib import Path
import shutil
import tempfile

from run_case import write_hashes


def seal(root, destination):
    shutil.copytree(root, destination, ignore=shutil.ignore_patterns('hashes.sha256'))
    write_hashes(destination)
    return destination


def main():
    root = Path(os.environ.get('SHELL_EVIDENCE_DIR', 'evidence')).resolve()
    if not root.is_dir():
        return
    parent = Path(tempfile.mkdtemp(prefix='shell-spikes-upload-', dir=os.environ.get('RUNNER_TEMP')))
    snapshot = seal(root, parent / 'evidence')
    env_file = os.environ.get('GITHUB_ENV')
    if env_file:
        with open(env_file, 'a', encoding='utf-8') as stream:
            stream.write(f'SHELL_UPLOAD_DIR={snapshot}\n')
    print(f'Sealed upload snapshot: {snapshot}', flush=True)


if __name__ == '__main__':
    main()
