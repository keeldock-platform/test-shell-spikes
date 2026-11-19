$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This driver requires Windows.' }
python automation/colour/runner.py --platform windows @args
exit $LASTEXITCODE
