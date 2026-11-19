import AppKit
import Foundation

guard let converted = NSColor.controlAccentColor.usingColorSpace(.sRGB) else {
    fputs("controlAccentColor could not convert to sRGB\n", stderr)
    exit(2)
}
let red = Double(converted.redComponent)
let green = Double(converted.greenComponent)
let blue = Double(converted.blueComponent)
let payload: [String: Any] = ["source": "NSColor.controlAccentColor", "space": "sRGB", "rgb": [red, green, blue]]
let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
print(String(decoding: data, as: UTF8.self))
