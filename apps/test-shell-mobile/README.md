# Mobile test shell

This directory packages the same synthetic renderer in an iOS simulator and Android wrapper.
S10 owns its colour input page. S11 owns the Android accent reader plugin. No store signing or
release configuration is part of this test shell.

## Platform project generation

Generate native wrappers on the matching hosted runner after checking out the frozen revision:

```sh
npm ci
npm run build:renderer
cargo install tauri-cli --version 2.12.5 --locked
ci/generate-mobile-projects.sh ios
# or
ci/generate-mobile-projects.sh android
```

The generated `src-tauri/ios/` and `src-tauri/android/` trees are disposable runner outputs and are
ignored by Git. Android API level, emulator image and iOS simulator runtime must match
`ci/environment-lock.json`. The workflow uses unsigned simulator builds only.

For Android, the generation recipe copies the lane-owned `AndroidAccentReader.kt` and the
coordinator-owned Tauri lifecycle wrapper into the generated source tree. The wrapper constructs
the app-scoped reader, forwards its update payloads through the `s11-accent` plugin event, exposes
the initial snapshot command and closes the reader with the activity. The shared renderer bridges
that plugin event to S11's synthetic global event name. API 30 uses the same reader and reports its
documented unavailable state without requesting a permission.

The smoke page exposes a synthetic case-ID field and links for the six spike modules. Mobile native
automation selects a spike and case through those controls; the URL query carries them to the
shared bootstrap. iOS runs S10 only; Android runs S10 on API 31/35 and S11 on API 30/31/35.
