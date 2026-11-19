param([string]$CaseId = $env:SHELL_CASE_ID)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This driver requires Windows.' }
python automation/accent/runner.py --platform windows --case-id $CaseId @args
exit $LASTEXITCODE
