import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

guard AXIsProcessTrusted() else {
    fputs("Accessibility preflight is not trusted; do not launch the S01 test.\n", stderr)
    exit(78)
}
guard CGPreflightScreenCaptureAccess() else {
    fputs("Screen capture preflight is not trusted; do not launch the S01 test.\n", stderr)
    exit(78)
}
let screens = NSScreen.screens
guard screens.isEmpty == false else {
    fputs("No display is available for the S01 test.\n", stderr)
    exit(78)
}
let displayRows: [[String: Any]] = screens.compactMap { screen in
    guard let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else {
        return nil
    }
    let display = CGDirectDisplayID(number.uint32Value)
    let frame = screen.frame
    return [
        "displayId": NSNumber(value: display),
        "frameAppkit": [frame.origin.x, frame.origin.y, frame.size.width, frame.size.height],
        "pixelSize": [NSNumber(value: CGDisplayPixelsWide(display)), NSNumber(value: CGDisplayPixelsHigh(display))],
        "backingScaleFactor": screen.backingScaleFactor,
        "main": display == CGMainDisplayID(),
    ]
}
let report: [String: Any] = [
    "status": "passed",
    "permissionPromptsRequested": false,
    "screens": displayRows,
]
do {
    let data = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
    print(String(decoding: data, as: UTF8.self))
} catch {
    fputs("Could not encode measured display preflight as JSON.\n", stderr)
    exit(78)
}
