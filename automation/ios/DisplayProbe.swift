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
        guard Thread.isMainThread else { return }
        let samples = DisplaySamples()
        let link = CADisplayLink(target: samples, selector: #selector(DisplaySamples.frame(_:)))
        link.add(to: .main, forMode: .common)
        defer { link.invalidate() }
        let deadline = Date().addingTimeInterval(3)
        while samples.timestamps.count < 10 && Date() < deadline {
            RunLoop.main.run(until: Date().addingTimeInterval(0.05))
        }
        let screen = UIScreen.main
        let data: [String: Any] = [
            "caseId": ProcessInfo.processInfo.environment["SHELL_CASE_ID"] ?? "",
            "simulatorUdid": ProcessInfo.processInfo.environment["SHELL_IOS_SIMULATOR_UDID"] ?? "",
            "resolution": "\(Int(screen.nativeBounds.width))x\(Int(screen.nativeBounds.height))",
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
