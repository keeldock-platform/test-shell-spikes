import AppKit
import CoreGraphics
import Foundation

let display = CGMainDisplayID()
if CommandLine.arguments.contains("--configure") {
    guard let current = CGDisplayCopyDisplayMode(display) else { exit(78) }
    if current.width < 1280 || current.height < 800 {
        let modes = CGDisplayCopyAllDisplayModes(display, nil) as? [CGDisplayMode] ?? []
        guard let mode = modes.filter({ $0.width >= 1280 && $0.height >= 800 })
            .min(by: { $0.width * $0.height < $1.width * $1.height }),
              CGDisplaySetDisplayMode(display, mode, nil) == .success else {
            fputs("No display mode can fit the 1040x660 Settings content; require at least 1280x800.\n", stderr)
            exit(78)
        }
        Thread.sleep(forTimeInterval: 1)
    }
}
guard let screen = NSScreen.screens.first(where: {
    ($0.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.uint32Value == display
}), let mode = CGDisplayCopyDisplayMode(display) else { exit(78) }
let refresh = mode.refreshRate > 0 ? mode.refreshRate : Double(screen.maximumFramesPerSecond)
let report: [String: Any] = [
    "source": "CoreGraphics active display mode and NSScreen",
    "displayId": display,
    "resolution": "\(CGDisplayPixelsWide(display))x\(CGDisplayPixelsHigh(display))",
    "logicalSize": [mode.width, mode.height],
    "scale": screen.backingScaleFactor,
    "refreshHz": refresh,
    "refreshSource": mode.refreshRate > 0 ? "CGDisplayMode.refreshRate" : "NSScreen.maximumFramesPerSecond",
]
let data = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
print(String(decoding: data, as: UTF8.self))
