#!/usr/bin/env python3
"""Probe exact public Android toolchain coordinates before emulator provisioning."""
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def probe(lock):
    kotlin = lock['kotlinGradlePlugin']
    agp = lock['androidGradlePlugin']
    urls = [f'https://repo.maven.apache.org/maven2/org/jetbrains/kotlin/{name}/{kotlin}/{name}-{kotlin}.pom'
            for name in ('kotlin-gradle-plugin', 'kotlin-gradle-plugins-bom', 'kotlin-gradle-plugin-api', 'kotlin-stdlib')]
    urls.append(f'https://dl.google.com/dl/android/maven2/com/android/tools/build/gradle/{agp}/gradle-{agp}.pom')
    records = []
    for url in urls:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(2 * 1024 * 1024)
        tree = ET.fromstring(data)
        if tree.tag != '{http://maven.apache.org/POM/4.0.0}project':
            raise ValueError('Dependency coordinate did not return a Maven project')
        records.append({'url': url, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        print('Resolved dependency coordinate: ' + url, flush=True)
    url = f"https://services.gradle.org/distributions/gradle-{lock['gradle']}-bin.zip.sha256"
    with urllib.request.urlopen(url, timeout=30) as response:
        digest = response.read(1024).decode().strip()
    if digest != lock['gradleSha256']:
        raise ValueError('Gradle distribution checksum does not match the lock')
    records.append({'url': url, 'distributionSha256': digest})
    return records


def main():
    path = Path(os.environ.get('SHELL_EVIDENCE_DIR', 'evidence')) / 'preflight/android-dependency-coordinates.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    result = {'status': 'UNVERIFIED'}
    try:
        result['resolved'] = probe(json.loads((ROOT / 'ci/environment-lock.json').read_text())['android'])
        result['status'] = 'resolved'
    except (OSError, ValueError, ET.ParseError) as error:
        result['error'] = str(error)
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return int(result['status'] != 'resolved')


if __name__ == '__main__':
    sys.exit(main())
