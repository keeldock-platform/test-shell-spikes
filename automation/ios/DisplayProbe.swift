import XCTest
import UIKit

private final class DisplaySamples: NSObject {
    var timestamps: [CFTimeInterval] = []

    @objc func frame(_ link: CADisplayLink) {
        timestamps.append(link.timestamp)
    }
}

extension XCTestCase {
    func captureDisplayProbe() throws {
        // Sample the simulator's own display callbacks; the advertised maximum
        // frame rate is not a measurement of the running display.
        if !Thread.isMainThread {
            try DispatchQueue.main.sync { try captureDisplayProbe() }
            return
        }
        let samples = DisplaySamples()
        let link = CADisplayLink(target: samples, selector: #selector(DisplaySamples.frame(_:)))
        link.add(to: .main, forMode: .common)
        defer { link.invalidate() }
        let deadline = Date().addingTimeInterval(3)
        while samples.timestamps.count < 10 && Date() < deadline {
            RunLoop.main.run(until: Date().addingTimeInterval(0.05))
        }
        let screen = UIScreen.main
        // The UI-test runner can expose compatibility-mode UIKit bounds (for
        // example 960x1440 on a 1206x2622 simulator). Measure the actual display
        // pixels through XCTest, as the recorder/preflight does.
        let screenshot = XCUIScreen.main.screenshot()
        guard let pixels = screenshot.image.cgImage else {
            throw NSError(domain: "DisplayProbe", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "XCTest display screenshot has no pixel image"])
        }
        let data: [String: Any] = [
            "caseId": ProcessInfo.processInfo.environment["SHELL_CASE_ID"] ?? "",
            "simulatorUdid": ProcessInfo.processInfo.environment["SHELL_IOS_SIMULATOR_UDID"] ?? "",
            "resolution": "\(pixels.width)x\(pixels.height)",
            "resolutionSource": "XCUIScreen.main.screenshot CGImage pixels",
            "uiKitNativeBounds": "\(Int(screen.nativeBounds.width))x\(Int(screen.nativeBounds.height))",
            "scale": screen.nativeScale,
            "displayLinkTimestamps": samples.timestamps,
        ]
        let attachment = XCTAttachment(
            data: try JSONSerialization.data(withJSONObject: data, options: [.sortedKeys]),
            uniformTypeIdentifier: "public.json")
        attachment.name = "recorder/ios-display.json"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
