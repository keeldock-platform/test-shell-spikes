$ErrorActionPreference = "Stop"
python ci/run-platform.py windows --spikes s02 s10 s11
exit $LASTEXITCODE
