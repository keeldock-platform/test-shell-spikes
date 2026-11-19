$ErrorActionPreference = "Stop"
python ci/run-platform.py windows --spikes s02
exit $LASTEXITCODE
