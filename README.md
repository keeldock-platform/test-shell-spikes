# Test Shell Spikes

This repository contains a small synthetic desktop and mobile test shell for measuring native
window, menu, settings, colour-input, and system-accent behaviour across operating systems.

All screens and values are generated test fixtures. The repository is exercised by one manually
dispatched workflow on a frozen source revision. Its evidence describes that run only.

The workflow maps every required case to a platform cell, records runner-native versions and display
measurements, and emits an explicit fallback whenever a case is `FAIL` or `UNVERIFIED`. Linux X11
and Wayland cases run in GNOME/Mutter sessions provisioned on Ubuntu 24.04; unavailable Linux
release/session profiles are reported as `UNVERIFIED` with their selected fallback.

See [SCAFFOLD-CONTRACT.md](SCAFFOLD-CONTRACT.md) for lane interfaces, case files, and evidence
layout. Local instructions and run artifacts are maintained outside this public repository.
