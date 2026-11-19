$ErrorActionPreference = "Stop"
py -3 ci/run-platform.py windows --spikes s02
exit $LASTEXITCODE
