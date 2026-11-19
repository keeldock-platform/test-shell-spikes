#!/usr/bin/env python3
"""Resolve generated XCTest scheme values at each case launch, across Xcode versions."""
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def configure(project, scheme, environment):
    path = Path(project) / 'xcshareddata/xcschemes' / (scheme + '.xcscheme')
    tree = ET.parse(path)
    action = tree.getroot().find('TestAction')
    if action is None:
        raise ValueError('Generated scheme has no TestAction')
    action.set('shouldUseLaunchSchemeArgsEnv', 'NO')
    resolved = {}
    for variable in action.findall('EnvironmentVariables/EnvironmentVariable'):
        key = variable.get('key')
        value = environment.get(key, '')
        variable.set('value', value)
        resolved[key] = value
    tree.write(path, encoding='utf-8', xml_declaration=True)
    # Persist the concrete envelope so missing values cannot masquerade as macros.
    document = json.dumps(resolved, indent=2) + '\n'
    (path.parent / (scheme + '-resolved-environment.json')).write_text(document)
    if environment.get('SHELL_EVIDENCE_DIR'):
        recorder = Path(environment['SHELL_EVIDENCE_DIR']) / 'recorder'
        recorder.mkdir(parents=True, exist_ok=True)
        (recorder / 'xctest-resolved-environment.json').write_text(document)
    return resolved


if __name__ == '__main__':
    resolved = configure(sys.argv[1], sys.argv[2], os.environ)
    print('Resolved XCTest environment keys: ' + ', '.join(sorted(key for key, value in resolved.items() if value)))
