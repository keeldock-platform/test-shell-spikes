# Android accent reader

`AndroidAccentReader.kt` is the S11-only Android adapter. The shared mobile wrapper owns its
construction, forwards `AccentUpdate` values to the renderer, calls `onActivityRecreated()` after
activity replacement, and closes the reader with the wrapper. Keep the reader instance app-scoped so
activity recreation re-samples the current resource without losing the wallpaper listener.

On API 31+, the reader resolves `android.R.color.system_accent1_500` and listens with
`WallpaperManager.OnColorsChangedListener`. It records the system wallpaper id, resource ARGB value,
source sequence, callback kind, activity generation, and monotonic timestamp. A real wallpaper or
configuration callback is marked `nativeEvent` only when the wallpaper/resource fingerprint
changes; an overlapping callback for the same fingerprint is deduplicated. Initial and recreation
reads are read-backs and do not stand in for an OS event. The wrapper preserves the source sequence
and adds the same value to its `events.jsonl` host/frame correlation.

Below API 31, a missing dynamic-colour resource, or a provider failure, emit unavailable with a
stable reason. The renderer hides System and resolves a stored `system` value to brand. The reader
does not request or read wallpaper files and does not declare `READ_EXTERNAL_STORAGE`,
`SET_WALLPAPER`, or another accent-reader permission. Any permission required by CI's separate
wallpaper automation is setup permission and must be recorded separately.

The optional `readSystemAccent` function exists only for an adapter-fallback fixture: CI may provide
a function that throws to model a missing dynamic-colour resource and confirm the reader publishes
`dynamic-colour-resource-unavailable`. It must not emit a native callback or stand in for the API
31/35 wallpaper event cases. Normal wrapper construction uses the Android system resource.

The case runner must change the wallpaper through the disposable emulator's real wallpaper UI or a
separately identified automation helper with equivalent OS-owned behavior. A broadcast, direct
callback, injected colour, or renderer-only event is not an acceptable live-event stimulus. Record
the wallpaper id and resolved resource value before and after activity recreation.
