import AppKit
import Foundation
import XCTest

/// UI driver for the synthetic S01 screen. The coordinator's macOS harness
/// supplies an XCTest UI-test target and launches this test against the
/// built Tauri app. The recorder must already be capturing the full desktop.
final class TrafficLightsUITests: XCTestCase {
    private var app: XCUIApplication!
    private var evidenceHandle: FileHandle!
    private var eventSequence = 0

    override func setUpWithError() throws {
        continueAfterFailure = false
        guard let bundleIdentifier = ProcessInfo.processInfo.environment["S01_APP_BUNDLE_ID"],
              let artifactDirectory = ProcessInfo.processInfo.environment["S01_ARTIFACT_DIR"],
              ProcessInfo.processInfo.environment["S01_PERMISSION_PROMPT_PREFLIGHT"] == "passed" else {
            throw NSError(domain: "S01", code: 1, userInfo: [NSLocalizedDescriptionKey: "CI must provide app/artifact paths and a passed no-permission-prompt preflight"])
        }

        let directory = URL(fileURLWithPath: artifactDirectory, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let eventFile = directory.appendingPathComponent("ui-events.jsonl")
        FileManager.default.createFile(atPath: eventFile.path, contents: nil)
        evidenceHandle = try FileHandle(forWritingTo: eventFile)

        app = XCUIApplication(bundleIdentifier: bundleIdentifier)
        // XCTest launches the target app in a separate process. Seed the
        // selected lane and evidence locations explicitly instead of relying
        // on xcodebuild to forward the test runner's environment implicitly.
        app.launchEnvironment = [
            "SHELL_SPIKE_ID": "s01",
            "SHELL_CASE_ID": ProcessInfo.processInfo.environment["SHELL_CASE_ID"] ?? "S01-CAPTURE",
            "SHELL_EVIDENCE_DIR": artifactDirectory,
            "S01_APP_BUNDLE_ID": bundleIdentifier,
            "S01_ARTIFACT_DIR": artifactDirectory,
            "S01_PERMISSION_PROMPT_PREFLIGHT": "passed",
        ]
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 10), "S01 app must become foreground")
        waitForMarker(status: "SETTLED", afterSequence: 0)

        // Native permission prompts are evidence failures. The helper never
        // clicks through, changes settings, or dismisses a prompt for the user.
        XCTAssertFalse(app.alerts.firstMatch.exists, "Unexpected in-app permission prompt")
        record(caseId: "S01-PREFLIGHT", kind: "app-ready", expected: "foreground; no prompt", actual: "foreground; no in-app alert")
        record(caseId: "S01-CREATION", kind: "state-settled", expected: "creation snapshot followed by comfortable row-one runtime reposition", actual: stateLabel())
    }

    override func tearDownWithError() throws {
        // Let the runner stop the full-desktop recorder when the test command
        // returns; an explicit app close would add an unrelated end frame.
        try evidenceHandle?.close()
    }

    func testS01TrafficLightsMatrix() {
        // Keep one app process for the entire capture. Sequence markers must
        // remain unique and increasing across all case cells.
        runGeometryCase("S01-DENSITY-01", button: "Compact density", expected: "density=compact;", fullscreen: false)
        runGeometryCase("S01-DENSITY-02", button: "Comfortable density", expected: "density=comfortable;", fullscreen: false)
        runGeometryCase("S01-LAYOUT-01", button: "Team capsules", expected: "layout=Team capsules;", fullscreen: false)
        runGeometryCase("S01-LAYOUT-02", button: "Two rows", expected: "layout=Two rows;", fullscreen: false)
        runFullscreenCase("S01-FS-01", compact: false, capsules: false)
        runFullscreenCase("S01-FS-02", compact: true, capsules: false)
        runFullscreenCase("S01-FS-03", compact: false, capsules: true)
        runFullscreenCase("S01-FS-04", compact: true, capsules: true)
        runGeometryCase("S01-FS-COMBO-01-setup-density", button: "Comfortable density", expected: "density=comfortable;", fullscreen: false)
        runGeometryCase("S01-FS-COMBO-01-setup-layout", button: "Two rows", expected: "layout=Two rows;", fullscreen: false)
        runGeometryCase("S01-FS-COMBO-01A", button: "Enter full screen", expected: "fullscreen=true", fullscreen: true)
        runGeometryCase("S01-FS-COMBO-01B", button: "Compact density", expected: "density=compact;", fullscreen: true)
        runGeometryCase("S01-FS-COMBO-01C", button: "Team capsules", expected: "layout=Team capsules;", fullscreen: true)
        runGeometryCase("S01-FS-COMBO-01D", button: "Comfortable density", expected: "density=comfortable;", fullscreen: true)
        runGeometryCase("S01-FS-COMBO-01E", button: "Two rows", expected: "layout=Two rows;", fullscreen: true)
        runGeometryCase("S01-FS-COMBO-01F", button: "Exit full screen", expected: "fullscreen=false", fullscreen: false)
        runGeometryCase("S01-FS-COMBO-02A", button: "Compact density", expected: "density=compact;", fullscreen: false)
        runGeometryCase("S01-FS-COMBO-02B", button: "Team capsules", expected: "layout=Team capsules;", fullscreen: false)
        runGeometryCase("S01-FS-COMBO-02C", button: "Enter full screen", expected: "fullscreen=true", fullscreen: true)
        runGeometryCase("S01-FS-COMBO-02D", button: "Comfortable density", expected: "density=comfortable;", fullscreen: true)
        runGeometryCase("S01-FS-COMBO-02E", button: "Two rows", expected: "layout=Two rows;", fullscreen: true)
        runGeometryCase("S01-FS-COMBO-02F", button: "Compact density", expected: "density=compact;", fullscreen: true)
        runGeometryCase("S01-FS-COMBO-02G", button: "Team capsules", expected: "layout=Team capsules;", fullscreen: true)
        runGeometryCase("S01-FS-COMBO-02H", button: "Exit full screen", expected: "fullscreen=false", fullscreen: false)
        // Binding checklist assertion S1-13. The per-frame pixel verdict
        // comes from analyze_capture.swift, not this settled UI check.
        for (caseId, compact, capsules) in [
            ("S1-13-comfortable-rows", false, false),
            ("S1-13-compact-rows", true, false),
            ("S1-13-comfortable-capsules", false, true),
            ("S1-13-compact-capsules", true, true),
        ] {
            if compact { runGeometryCase("\(caseId)-setup-density", button: "Compact density", expected: "density=compact;", fullscreen: false) }
            if !compact && stateLabel().contains("density=compact") {
                runGeometryCase("\(caseId)-setup-density", button: "Comfortable density", expected: "density=comfortable;", fullscreen: false)
            }
            if capsules { runGeometryCase("\(caseId)-setup-layout", button: "Team capsules", expected: "layout=Team capsules;", fullscreen: false) }
            if !capsules && stateLabel().contains("layout=Team capsules") {
                runGeometryCase("\(caseId)-setup-layout", button: "Two rows", expected: "layout=Two rows;", fullscreen: false)
            }
            runGeometryCase(caseId, button: "Enter full screen", expected: "fullscreen=true", fullscreen: true)
            record(caseId: caseId, kind: "S1-13-settled", expected: "zero native traffic-light pixels in full-screen ROI", actual: "native full-screen window observed; per-frame verdict pending analyzer")
            runGeometryCase("\(caseId)-exit", button: "Exit full screen", expected: "fullscreen=false", fullscreen: false)
        }
    }

    private func runFullscreenCase(_ caseId: String, compact: Bool, capsules: Bool) {
        let currentState = stateLabel()
        if compact && !currentState.contains("density=compact") {
            runGeometryCase("\(caseId)-setup-density", button: "Compact density", expected: "density=compact;", fullscreen: false)
        } else if !compact && currentState.contains("density=compact") {
            runGeometryCase("\(caseId)-setup-density", button: "Comfortable density", expected: "density=comfortable;", fullscreen: false)
        }
        let currentLayout = stateLabel()
        if capsules && !currentLayout.contains("layout=Team capsules") {
            runGeometryCase("\(caseId)-setup-layout", button: "Team capsules", expected: "layout=Team capsules;", fullscreen: false)
        } else if !capsules && currentLayout.contains("layout=Team capsules") {
            runGeometryCase("\(caseId)-setup-layout", button: "Two rows", expected: "layout=Two rows;", fullscreen: false)
        }
        runGeometryCase(caseId, button: "Enter full screen", expected: "fullscreen=true", fullscreen: true)
        record(caseId: caseId, kind: "S1-13-settled", expected: "zero native traffic-light pixels in full-screen ROI", actual: "native full-screen window observed; per-frame verdict pending analyzer")
        runGeometryCase("\(caseId)-exit", button: "Exit full screen", expected: "fullscreen=false", fullscreen: false)
    }

    private func runGeometryCase(_ caseId: String, button label: String, expected: String, fullscreen: Bool) {
        let before = currentSequence()
        record(caseId: caseId, kind: "action", expected: expected, actual: "tap \(label)")
        let control = app.buttons[label]
        XCTAssertTrue(control.waitForExistence(timeout: 5), "Missing accessible S01 control: \(label)")
        control.tap()
        waitForMarker(status: "SETTLED", afterSequence: before)
        let actualState = stateLabel()
        XCTAssertTrue(actualState.contains(expected), "Expected \(expected), got \(actualState)")
        waitForNativeFullscreen(fullscreen)
        record(caseId: caseId, kind: "state-settled", expected: expected, actual: actualState)
    }

    private func waitForMarker(status: String, afterSequence: Int) {
        let marker = app.descendants(matching: .any).matching(
            NSPredicate(format: "label BEGINSWITH %@", "S01 ")
        ).firstMatch
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard marker.exists else { return false }
            let parts = marker.label.split(separator: " ")
            guard parts.count >= 3, parts[0] == "S01",
                  let sequence = Int(parts[1]) else { return false }
            return sequence > afterSequence && marker.label.contains(status)
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 12), .completed, "S01 marker did not settle after sequence \(afterSequence)")
    }

    private func currentSequence() -> Int {
        let marker = app.descendants(matching: .any).matching(
            NSPredicate(format: "label BEGINSWITH %@", "S01 ")
        ).firstMatch
        let parts = marker.label.split(separator: " ")
        return parts.count > 1 ? Int(parts[1]) ?? 0 : 0
    }

    private func stateLabel() -> String {
        let state = app.descendants(matching: .any).matching(
            NSPredicate(format: "label CONTAINS %@", "density=")
        ).firstMatch
        return state.exists ? state.label : ""
    }

    private func waitForNativeFullscreen(_ expected: Bool) {
        let window = app.windows.firstMatch
        let largestScreen = NSScreen.screens.max { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }?.frame
        guard let screen = largestScreen else {
            XCTFail("No runner display bounds; full-screen state is unverified")
            return
        }
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard window.exists else { return false }
            let frame = window.frame
            // XCTest and AppKit use different vertical origins on macOS;
            // compare native full-screen dimensions, not their raw y origins.
            let coversScreen = abs(frame.width - screen.width) <= 2
                && abs(frame.height - screen.height) <= 2
            return expected ? coversScreen : !coversScreen
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 15), .completed, "Native window did not reach fullscreen=\(expected)")
    }

    private func record(caseId: String, kind: String, expected: String, actual: String) {
        eventSequence += 1
        let event: [String: Any] = [
            "caseId": caseId,
            "kind": kind,
            "eventSequence": eventSequence,
            "visibleSequence": currentSequence(),
            "utc": ISO8601DateFormatter().string(from: Date()),
            "runnerMonotonicSeconds": ProcessInfo.processInfo.systemUptime,
            "expected": expected,
            "actual": actual,
            "framePointer": "video/capture-index.jsonl (visible S01 marker sequence)",
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: event),
              var line = String(data: data, encoding: .utf8) else {
            XCTFail("Could not serialize S01 UI event")
            return
        }
        line.append("\n")
        evidenceHandle.write(Data(line.utf8))
    }
}

