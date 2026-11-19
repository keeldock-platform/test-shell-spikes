$ErrorActionPreference = "Stop"
py -3 ci/run-platform.py windows --spikes s02 s10 s11
exit $LASTEXITCODE
