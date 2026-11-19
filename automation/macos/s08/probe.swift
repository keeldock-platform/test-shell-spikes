// S08 native macOS UI probe. Source only: CI runs this script after launching the
// synthetic shell. It never requests Accessibility consent or opens app settings.
import AppKit
import ApplicationServices
import CoreGraphics
import Foundation
import ScreenCaptureKit

struct ProbeFailure: Error, CustomStringConvertible {
    let description: String
}

struct NativeWindow {
    let element: AXUIElement
    let title: String
    let role: String
    let frame: CGRect
    let windowID: Int?
}

struct Options {
    let scenario: String
    let bundleID: String
    let eventsURL: URL
}

let knownAssertions: [String: String] = [
    "S08-A01": "Command+Comma opens one lazy 1040x660 Settings window.",
    "S08-A02": "Repeated Command+Comma focuses the same Settings instance.",
    "S08-A03": "Option+Command+Comma opens tool settings in main only.",
    "S08-A04": "The Security pose is visible with Settings key.",
    "S08-A05": "Step-up is one AppKit accessibility sheet attached to Settings.",
    "S08-A06": "The sheet blocks its Settings parent but leaves main usable.",
    "S08-A07": "Main is visible and inactive while Settings is key, without a scrim.",
    "S08-A08": "Command+W hides Settings; reopening restores Team page and scroll.",
    "S08-A09": "Destroy/recreate restores position and size through window-state 2.5.0.",
    "S08-A10": "Recreated Settings displays Team pose S4-18 and restores the same nonzero page/scroll mock.",
    "S08-A11": "Mock lock destroys Settings until mock unlock.",
    "S08-A12": "Allowed mock Settings operations and parented pickers succeed.",
    "S08-A13": "Settings webview policy-denies every sentinel and direct dialog command.",
]

func parseOptions() throws -> Options {
    var values: [String: String] = [:]
    var index = 1
    while index < CommandLine.arguments.count {
        let key = CommandLine.arguments[index]
        guard key.hasPrefix("--"), index + 1 < CommandLine.arguments.count else {
            throw ProbeFailure(description: "Expected --scenario, --bundle-id, and --events arguments")
        }
        values[key] = CommandLine.arguments[index + 1]
        index += 2
    }
    guard let scenario = values["--scenario"],
          let bundleID = values["--bundle-id"],
          let events = values["--events"] else {
        throw ProbeFailure(description: "Missing required probe arguments")
    }
    guard ["ready", "entry", "tool-settings", "sheet", "geometry", "mock-lock", "permissions"].contains(scenario) else {
        throw ProbeFailure(description: "Unknown S08 scenario: \(scenario)")
    }
    return Options(scenario: scenario, bundleID: bundleID, eventsURL: URL(fileURLWithPath: events))
}

final class Probe {
    let options: Options
    let process: NSRunningApplication
    let application: AXUIElement
    private let output: FileHandle
    private var sequence = 0

    init(options: Options) throws {
        self.options = options
        guard AXIsProcessTrusted() else {
            throw ProbeFailure(description: "Accessibility preflight is unavailable; no consent prompt was requested")
        }
        guard let process = NSRunningApplication.runningApplications(withBundleIdentifier: options.bundleID).first,
              !process.isTerminated else {
            throw ProbeFailure(description: "The expected S08 bundle is not running: \(options.bundleID)")
        }
        self.process = process
        self.application = AXUIElementCreateApplication(process.processIdentifier)
        let parent = options.eventsURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: true)
        guard FileManager.default.createFile(atPath: options.eventsURL.path, contents: nil) else {
            throw ProbeFailure(description: "Could not create the S08 event log")
        }
        self.output = try FileHandle(forWritingTo: options.eventsURL)
    }

    func emit(_ name: String, _ fields: [String: Any] = [:]) {
        sequence += 1
        var row: [String: Any] = [
            "sequence": sequence,
            "event": name,
            "scenario": options.scenario,
            "monotonicSeconds": ProcessInfo.processInfo.systemUptime,
            "wallTime": ISO8601DateFormatter().string(from: Date()),
        ]
        fields.forEach { row[$0.key] = $0.value }
        guard let data = try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys, .fragmentsAllowed]) else { return }
        output.write(data)
        output.write(Data([0x0a]))
        try? output.synchronize()
    }

    func assertion(_ id: String, passed: Bool?, actual: String, evidence: [String] = []) {
        let verdict = passed.map { $0 ? "PASS" : "FAIL" } ?? "UNVERIFIED"
        emit("assertion", [
            "id": id,
            "expected": knownAssertions[id] ?? "See cases/s08.json",
            "actual": actual,
            "verdict": verdict,
            "evidence": evidence,
        ])
    }

    func windows() -> [NativeWindow] {
        guard let elements = attribute(application, "AXWindows") as? [AXUIElement] else { return [] }
        return elements.compactMap { element in
            guard let frame = frameOf(element) else { return nil }
            let title = stringAttribute(element, "AXTitle") ?? ""
            let role = stringAttribute(element, "AXRole") ?? ""
            return NativeWindow(element: element, title: title, role: role, frame: frame, windowID: cgWindowID(frame: frame, title: title, pid: process.processIdentifier))
        }
    }

    func settingsWindow() -> NativeWindow? { windows().first { $0.title == "Settings" && $0.windowID != nil } }
    func mainWindow() -> NativeWindow? { windows().first { $0.title != "Settings" && $0.role == "AXWindow" && $0.windowID != nil } }

    func focusedWindow() -> NativeWindow? {
        guard let value = attribute(application, "AXFocusedWindow"),
              CFGetTypeID(value as CFTypeRef) == AXUIElementGetTypeID() else { return nil }
        let focused = value as! AXUIElement
        guard let frame = frameOf(focused) else { return nil }
        let title = stringAttribute(focused, "AXTitle") ?? ""
        let role = stringAttribute(focused, "AXRole") ?? ""
        return NativeWindow(element: focused, title: title, role: role, frame: frame, windowID: cgWindowID(frame: frame, title: title, pid: process.processIdentifier))
    }

    func observe(_ name: String, _ window: NativeWindow? = nil, extra: [String: Any] = [:]) {
        var fields = extra
        fields["frontmostBundleID"] = NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? ""
        fields["appIsActive"] = process.isActive
        if let window {
            fields["windowTitle"] = window.title
            fields["windowRole"] = window.role
            fields["nativeWindowID"] = window.windowID ?? -1
            fields["bounds"] = [window.frame.origin.x, window.frame.origin.y, window.frame.width, window.frame.height]
        }
        if let focused = focusedWindow() {
            fields["activeWindowTitle"] = focused.title
            fields["activeWindowID"] = focused.windowID ?? -1
        }
        fields["settingsWindowCount"] = windows().filter { $0.title == "Settings" }.count
        emit(name, fields)
    }

    func sendComma(command: Bool = true, option: Bool = false) throws {
        guard let down = CGEvent(keyboardEventSource: nil, virtualKey: 43, keyDown: true),
              let up = CGEvent(keyboardEventSource: nil, virtualKey: 43, keyDown: false) else {
            throw ProbeFailure(description: "Could not create native comma key events")
        }
        var flags: CGEventFlags = []
        if command { flags.insert(.maskCommand) }
        if option { flags.insert(.maskAlternate) }
        down.flags = flags
        up.flags = flags
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        emit("native-key", ["key": "comma", "command": command, "option": option])
    }

    func sendCommandW() throws {
        guard let down = CGEvent(keyboardEventSource: nil, virtualKey: 13, keyDown: true),
              let up = CGEvent(keyboardEventSource: nil, virtualKey: 13, keyDown: false) else {
            throw ProbeFailure(description: "Could not create native W key events")
        }
        down.flags = .maskCommand
        up.flags = .maskCommand
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        emit("native-key", ["key": "w", "command": true])
    }

    func waitUntil<T>(_ description: String, timeout: TimeInterval = 8, _ predicate: () -> T?) throws -> T {
        let end = ProcessInfo.processInfo.systemUptime + timeout
        while ProcessInfo.processInfo.systemUptime < end {
            if let value = predicate() { return value }
            RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
        }
        var nodes: [[String: String]] = []
        func snapshot(_ node: AXUIElement, depth: Int) {
            guard depth < 10 && nodes.count < 2000 else { return }
            nodes.append(["role": stringAttribute(node, "AXRole") ?? "",
                          "title": stringAttribute(node, "AXTitle") ?? "",
                          "description": stringAttribute(node, "AXDescription") ?? "",
                          "value": stringAttribute(node, "AXValue") ?? ""])
            for child in attribute(node, "AXChildren") as? [AXUIElement] ?? [] { snapshot(child, depth: depth + 1) }
        }
        snapshot(application, depth: 0)
        emit("timeout-native-tree", ["waitingFor": description, "nodes": nodes])
        throw ProbeFailure(description: "Timed out waiting for \(description)")
    }

    func find(_ title: String, in element: AXUIElement? = nil) -> AXUIElement? {
        let root = element ?? application
        if stringAttribute(root, "AXTitle") == title || stringAttribute(root, "AXValue") == title || stringAttribute(root, "AXDescription") == title {
            return root
        }
        guard let children = attribute(root, "AXChildren") as? [AXUIElement] else { return nil }
        for child in children {
            if let match = find(title, in: child) { return match }
        }
        return nil
    }

    func press(_ title: String) throws {
        let target = try waitUntil("Accessibility control: \(title)", timeout: 20) { self.find(title) }
        let status = AXUIElementPerformAction(target, kAXPressAction as CFString)
        guard status == .success else { throw ProbeFailure(description: "Could not press \(title): AXError \(status.rawValue)") }
        emit("accessibility-press", ["control": title])
    }

    func raise(_ window: NativeWindow) throws {
        let status = AXUIElementPerformAction(window.element, kAXRaiseAction as CFString)
        guard status == .success else { throw ProbeFailure(description: "Could not raise native window \(window.title): AXError \(status.rawValue)") }
        emit("native-window-raised", ["title": window.title, "nativeWindowID": window.windowID ?? -1])
    }

    func textValue(_ title: String) -> String? {
        guard let target = find(title) else { return nil }
        return stringAttribute(target, "AXValue") ?? stringAttribute(target, "AXTitle")
    }

    func click(_ title: String) throws {
        guard let target = find(title), let frame = frameOf(target) else {
            throw ProbeFailure(description: "Cannot locate native click target: \(title)")
        }
        let point = CGPoint(x: frame.midX, y: frame.midY)
        guard let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
              let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else {
            throw ProbeFailure(description: "Could not create native pointer events")
        }
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        emit("native-click", ["control": title, "screenPoint": [point.x, point.y]])
    }

    func scroll(_ elementTitle: String) throws {
        guard let target = find(elementTitle), let frame = frameOf(target) else {
            throw ProbeFailure(description: "Cannot locate scroll target: \(elementTitle)")
        }
        let point = CGPoint(x: frame.midX, y: frame.midY)
        guard let event = CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 1, wheel1: -260, wheel2: 0, wheel3: 0) else {
            throw ProbeFailure(description: "Could not create native wheel event")
        }
        event.location = point
        event.post(tap: .cghidEventTap)
        emit("native-scroll", ["target": elementTitle, "screenPoint": [point.x, point.y], "deltaY": 260])
    }

    func sheets(for window: NativeWindow) -> [AXUIElement] {
        var result = attribute(window.element, "AXSheets") as? [AXUIElement] ?? []
        func collect(_ parent: AXUIElement, depth: Int) {
            guard depth < 8 else { return }
            for child in attribute(parent, "AXChildren") as? [AXUIElement] ?? [] {
                if stringAttribute(child, "AXRole") == "AXSheet" {
                    if !result.contains(where: { CFEqual($0, child) }) { result.append(child) }
                } else { collect(child, depth: depth + 1) }
            }
        }
        collect(window.element, depth: 0)
        return result
    }

    func waitForSettings() throws -> NativeWindow {
        try waitUntil("the Settings accessibility window") { self.settingsWindow() }
    }

    func waitForNoSettings() throws {
        _ = try waitUntil("Settings to close or hide") { self.settingsWindow() == nil ? true : nil }
    }

    func setGeometry(_ window: NativeWindow, position: CGPoint, size: CGSize) throws {
        var point = position
        var dimension = size
        guard let pointValue = AXValueCreate(.cgPoint, &point), let sizeValue = AXValueCreate(.cgSize, &dimension) else {
            throw ProbeFailure(description: "Could not create AX position/size values")
        }
        let positionResult = AXUIElementSetAttributeValue(window.element, kAXPositionAttribute as CFString, pointValue)
        let sizeResult = AXUIElementSetAttributeValue(window.element, kAXSizeAttribute as CFString, sizeValue)
        guard positionResult == .success, sizeResult == .success else {
            throw ProbeFailure(description: "Native window geometry is not writable through Accessibility")
        }
    }

    func emitVerdict(_ id: String, expected: String, actual: String, pass: Bool?) {
        assertion(id, passed: pass, actual: actual, evidence: ["events.jsonl#\(id)"])
        if knownAssertions[id] == nil {
            emit("assertion-detail", ["id": id, "expected": expected, "actual": actual, "verdict": pass.map { $0 ? "PASS" : "FAIL" } ?? "UNVERIFIED"])
        }
    }

    func captureWholeDesktop(_ name: String) throws {
        let evidenceRoot = ProcessInfo.processInfo.environment["SHELL_EVIDENCE_DIR"]
            .map { URL(fileURLWithPath: $0, isDirectory: true) }
            ?? options.eventsURL.deletingLastPathComponent()
        let screens = evidenceRoot.appendingPathComponent("screens", isDirectory: true)
        try FileManager.default.createDirectory(at: screens, withIntermediateDirectories: true)
        let url = screens.appendingPathComponent(name)
        guard #available(macOS 14.0, *), CGPreflightScreenCaptureAccess() else {
            throw ProbeFailure(description: "ScreenCaptureKit capture requires macOS 14 and pre-authorised screen recording")
        }
        // Completion values are delivered to the main queue while waitUntil
        // pumps its run loop, so capture never blocks that queue on a semaphore.
        var contentResult: Result<SCShareableContent, Error>?
        SCShareableContent.getExcludingDesktopWindows(false, onScreenWindowsOnly: true) { content, error in
            DispatchQueue.main.async {
                if let content { contentResult = .success(content) }
                else { contentResult = .failure(error ?? ProbeFailure(description: "No shareable desktop content")) }
            }
        }
        let content = try waitUntil("ScreenCaptureKit display list", timeout: 15) { contentResult }.get()
        guard !content.displays.isEmpty else {
            throw ProbeFailure(description: "ScreenCaptureKit returned no displays")
        }
        let bounds = content.displays.reduce(CGRect.null) { $0.union($1.frame) }
        let scale = NSScreen.screens.map { $0.backingScaleFactor }.max() ?? 1
        guard let canvas = CGContext(data: nil, width: Int(bounds.width * scale),
                                     height: Int(bounds.height * scale), bitsPerComponent: 8,
                                     bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                     bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
            throw ProbeFailure(description: "Could not allocate whole-desktop capture")
        }
        for display in content.displays {
            let configuration = SCStreamConfiguration()
            configuration.width = Int(display.frame.width * scale)
            configuration.height = Int(display.frame.height * scale)
            configuration.showsCursor = false
            let filter = SCContentFilter(display: display, excludingWindows: [])
            var imageResult: Result<CGImage, Error>?
            SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration) { image, error in
                DispatchQueue.main.async {
                    if let image { imageResult = .success(image) }
                    else { imageResult = .failure(error ?? ProbeFailure(description: "No desktop capture image")) }
                }
            }
            let captured = try waitUntil("ScreenCaptureKit display capture", timeout: 15) { imageResult }.get()
            canvas.draw(captured, in: CGRect(x: (display.frame.minX - bounds.minX) * scale,
                                            y: (bounds.maxY - display.frame.maxY) * scale,
                                            width: display.frame.width * scale,
                                            height: display.frame.height * scale))
        }
        guard let image = canvas.makeImage() else {
            throw ProbeFailure(description: "Could not compose whole-desktop capture")
        }
        let representation = NSBitmapImageRep(cgImage: image)
        guard let png = representation.representation(using: .png, properties: [:]) else {
            throw ProbeFailure(description: "Could not encode whole-desktop capture \(name)")
        }
        try png.write(to: url, options: .atomic)
        emit("capture-point", ["screenRef": "screens/\(name)", "scope": "whole desktop"])
    }

    func run() throws {
        emit("preflight", [
            "bundleID": options.bundleID,
            "processID": process.processIdentifier,
            "accessibilityTrusted": AXIsProcessTrusted(),
            "displayBounds": NSScreen.screens.map { NSStringFromRect($0.frame) },
            "scenario": options.scenario,
        ])
        switch options.scenario {
        case "ready": try runReady()
        case "entry": try runEntry()
        case "tool-settings": try runToolSettings()
        case "sheet": try runSheet()
        case "geometry": try runGeometry()
        case "mock-lock": try runMockLock()
        case "permissions": try runPermissions()
        default: throw ProbeFailure(description: "Unsupported S08 scenario")
        }
    }

    private func runReady() throws {
        guard process.activate(options: [.activateIgnoringOtherApps]) else {
            throw ProbeFailure(description: "Could not activate the synthetic shell")
        }
        let main = try waitUntil("the main native window") { self.mainWindow() }
        let marker = try waitUntil("the shared S08 ready marker") { self.findByPrefix("Pose: S08-MAIN") }
        emit("ready-marker", ["marker": marker, "windowTitle": main.title, "nativeWindowID": main.windowID ?? -1])
    }

    private func runEntry() throws {
        guard process.activate(options: [.activateIgnoringOtherApps]) else {
            throw ProbeFailure(description: "Could not activate the synthetic shell")
        }
        let initialMain = try waitUntil("the main native window") { self.mainWindow() }
        observe("initial-main", initialMain)
        guard let main = mainWindow() else { throw ProbeFailure(description: "Main window disappeared before repeat-entry check") }
        try raise(main)
        _ = try waitUntil("main window to become key before repeat entry") { self.focusedWindow()?.windowID == main.windowID ? true : nil }
        try sendComma()
        let first = try waitForSettings()
        guard let firstID = first.windowID else { throw ProbeFailure(description: "Could not map Settings to a CGWindow identifier") }
        let firstCount = windows().filter { $0.title == "Settings" }.count
        let firstIsActive = focusedWindow()?.windowID == firstID
        observe("S08-A01", first, extra: ["caseId": "S08-MAC-01-entry-instance", "expectedWidth": 1040, "expectedHeight": 660])
        let geometryMarker = try waitUntil("the Tauri logical content geometry marker", timeout: 20) {
            guard let marker = self.findByPrefix("Native geometry: settings ") else { return nil as String? }
            return marker
        }
        let expectedLogicalSize = geometryMarker.contains("Native geometry: settings 1040×660 logical points")
        emit("native-content-geometry", ["marker": geometryMarker, "nativeOuterBounds": rectArray(first.frame), "deviceScale": NSScreen.main?.backingScaleFactor ?? 0])
        try captureWholeDesktop("s08-s4-14.png")
        let firstSizeOK = expectedLogicalSize
        emitVerdict("S08-A01", expected: knownAssertions["S08-A01"]!, actual: "count=\(firstCount); id=\(firstID); active=\(firstIsActive); logicalContentSize=\(geometryMarker); outerBounds=\(NSStringFromRect(first.frame))", pass: firstCount == 1 && first.title == "Settings" && firstIsActive && firstSizeOK)

        guard let main = mainWindow() else { throw ProbeFailure(description: "Main window disappeared before repeat-entry check") }
        try raise(main)
        _ = try waitUntil("main window to become key before repeat entry") { self.focusedWindow()?.windowID == main.windowID ? true : nil }
        try sendComma()
        let focusedAgain: NativeWindow = try waitUntil("the existing Settings window to be focused") {
            guard let focused = self.focusedWindow(), focused.title == "Settings" else { return nil }
            return focused
        }
        let secondCount = windows().filter { $0.title == "Settings" }.count
        observe("S08-A02", focusedAgain, extra: ["caseId": "S08-MAC-01-entry-instance", "firstWindowID": firstID])
        try captureWholeDesktop("s08-repeat-focus.png")
        emitVerdict("S08-A02", expected: knownAssertions["S08-A02"]!, actual: "count=\(secondCount); firstID=\(firstID); focusedID=\(focusedAgain.windowID ?? -1)", pass: secondCount == 1 && focusedAgain.windowID == firstID)
    }

    private func runToolSettings() throws {
        guard process.activate(options: [.activateIgnoringOtherApps]) else { throw ProbeFailure(description: "Could not activate shell") }
        let main = try waitUntil("the main native window") { self.mainWindow() }
        try raise(main)
        _ = try waitUntil("main window to become key before tool settings entry") { self.focusedWindow()?.windowID == main.windowID ? true : nil }
        try sendComma(option: true)
        let toolView = try waitUntil("the tool settings mock view") { self.find("Tool settings mock") }
        let settingsCount = windows().filter { $0.title == "Settings" }.count
        observe("S08-A03", mainWindow(), extra: ["toolSettingsVisible": toolView != nil, "settingsWindowCount": settingsCount])
        try captureWholeDesktop("s08-tool-settings-main.png")
        emitVerdict("S08-A03", expected: knownAssertions["S08-A03"]!, actual: "toolSettingsVisible=\(toolView != nil); settingsWindowCount=\(settingsCount)", pass: toolView != nil && settingsCount == 0)
    }

    private func runSheet() throws {
        let baselineMain = try waitUntil("main baseline window") { self.mainWindow() }
        try raise(baselineMain)
        try captureWholeDesktop("s08-baseline-a.png")
        Thread.sleep(forTimeInterval: 0.25)
        try captureWholeDesktop("s08-baseline-b.png")
        emit("scrim-baseline", ["windowID": baselineMain.windowID ?? -1,
             "mainBounds": rectArray(baselineMain.frame),
             "displayBounds": rectArray(CGDisplayBounds(CGMainDisplayID())),
             "displayCount": NSScreen.screens.count,
             "screens": ["screens/s08-baseline-a.png", "screens/s08-baseline-b.png"]])
        try openSettingsAndSelect("Security")
        let settings = try waitForSettings()
        let activeSecurity = focusedWindow()?.windowID == settings.windowID
        let securityPage = try waitUntil("the Security page marker") { self.findByPrefix("Page: Security;") }
        observe("S08-A04", settings, extra: ["caseId": "S08-MAC-03-parented-sheet-and-inactive-main", "securityPageMarker": securityPage])
        try captureWholeDesktop("s08-s4-16.png")
        emitVerdict("S08-A04", expected: knownAssertions["S08-A04"]!, actual: "settingsActive=\(activeSecurity); pageMarker=\(securityPage); title=\(settings.title)", pass: activeSecurity && securityPage.contains("Security"))

        try press("Request step-up")
        let sheetElements: [AXUIElement] = try waitUntil("one Accessibility sheet attached to Settings") {
            guard let settings = self.settingsWindow() else { return nil }
            let sheets = self.sheets(for: settings)
            return sheets.count == 1 ? sheets : nil
        }
        let sheetRoles = sheetElements.map { stringAttribute($0, "AXRole") ?? "" }
        observe("S08-A05", settingsWindow(), extra: ["sheetCount": sheetElements.count, "sheetRoles": sheetRoles, "caseId": "S08-MAC-03-parented-sheet-and-inactive-main"])
        try captureWholeDesktop("s08-s4-17.png")
        emitVerdict("S08-A05", expected: knownAssertions["S08-A05"]!, actual: "sheetCount=\(sheetElements.count); roles=\(sheetRoles)", pass: sheetElements.count == 1 && sheetRoles.allSatisfy { $0 == "AXSheet" })

        let main = try waitUntil("main window alongside the sheet") { self.mainWindow() }
        let inactiveMarker = textValue("Main window inactive") != nil || find("Main window inactive", in: main.element) != nil
        observe("S08-A07", main, extra: ["settingsIsKey": focusedWindow()?.windowID == settings.windowID, "mainInactiveMarker": inactiveMarker, "wholeDesktopCaptureRequired": true, "caseId": "S08-MAC-03-parented-sheet-and-inactive-main"])
        emit("scrim-interval-start", ["mainBounds": rectArray(main.frame), "windowID": main.windowID ?? -1,
             "excludeBounds": rectArray(settings.frame)])
        try captureWholeDesktop("s08-s1-12.png")
        Thread.sleep(forTimeInterval: 0.3)
        emit("scrim-interval-stop")
        emitVerdict("S08-A07", expected: knownAssertions["S08-A07"]!, actual: "settingsIsKey=\(focusedWindow()?.windowID == settings.windowID); mainVisible=true; inactiveMarker=\(inactiveMarker); scrim=requires-full-desktop-frame-analysis", pass: nil)

        try click("Hide Settings")
        RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.25))
        let settingsStillVisible = settingsWindow() != nil && settingsWindow().map { sheets(for: $0).count == 1 } == true
        let mainBefore = counterValue("Main actions:")
        try click("Increment main action counter")
        let mainAfter = try waitUntil("the main action counter to increment") { self.counterValue("Main actions:") }
        let mainChanged = mainBefore != mainAfter
        observe("S08-A06", settingsWindow(), extra: ["settingsStillVisibleWithSheet": settingsStillVisible, "mainCounterBefore": mainBefore ?? "unavailable", "mainCounterAfter": mainAfter, "mainCounterChanged": mainChanged, "caseId": "S08-MAC-03-parented-sheet-and-inactive-main"])
        try captureWholeDesktop("s08-sheet-scope.png")
        emitVerdict("S08-A06", expected: knownAssertions["S08-A06"]!, actual: "settingsStillVisibleWithSheet=\(settingsStillVisible); mainCounterChanged=\(mainChanged)", pass: settingsStillVisible && mainChanged)
    }

    private func runGeometry() throws {
        try openSettingsAndSelect("Team")
        let original = try waitForSettings()
        try scroll("Settings page content")
        let nonzeroMarker: String = try waitUntil("a nonzero synthetic Team scroll marker") {
            guard let value = self.findByPrefix("Page: Team; scroll: "),
                  let scroll = Int(value.split(separator: ":").last?.trimmingCharacters(in: .whitespaces) ?? "0"),
                  scroll > 0 else { return nil }
            return value
        }
        let savedMarker: String = try waitUntil("the host to confirm the Team page/scroll mock was saved") {
            guard let value = self.findByPrefix("View state saved: Page: Team; scroll:"),
                  value.contains(nonzeroMarker) else { return nil }
            return value
        }
        try captureWholeDesktop("s08-s4-18.png")
        let beforeHide = textValuePrefix("Page: Team; scroll: ") ?? ""
        try sendCommandW()
        try waitForNoSettings()
        try sendComma()
        let reopened = try waitForSettings()
        let afterReopen: String = try waitUntil("Team page and scroll state to restore") {
            guard let value = self.findByPrefix("Page: Team; scroll: "), value == nonzeroMarker else { return nil }
            return value
        }
        let sameWindow = reopened.windowID == original.windowID
        let scrollRestored = afterReopen.contains("Team; scroll:") && !afterReopen.hasSuffix("scroll: 0")
        observe("S08-A08", reopened, extra: ["pageMarkerBeforeHide": beforeHide, "hostSavedMarker": savedMarker, "pageMarkerAfterReopen": afterReopen, "sameWindowID": sameWindow, "caseId": "S08-MAC-04-window-state-and-view-restore"])
        try captureWholeDesktop("s08-hide-reopen.png")
        emitVerdict("S08-A08", expected: knownAssertions["S08-A08"]!, actual: "sameWindowID=\(sameWindow); restoredMarker=\(afterReopen)", pass: sameWindow && scrollRestored)

        let originalFrame = reopened.frame
        let requestedPosition = CGPoint(x: originalFrame.origin.x + 37, y: originalFrame.origin.y + 29)
        let requestedSize = CGSize(width: originalFrame.width - 80, height: originalFrame.height - 60)
        try setGeometry(reopened, position: requestedPosition, size: requestedSize)
        let moved: NativeWindow = try waitUntil("Settings move and resize to settle") {
            guard let value = self.settingsWindow() else { return nil }
            return abs(value.frame.origin.x - requestedPosition.x) < 3
                && abs(value.frame.origin.y - requestedPosition.y) < 3
                && abs(value.frame.width - requestedSize.width) < 3
                && abs(value.frame.height - requestedSize.height) < 3 ? value : nil
        }
        observe("geometry-before-destroy", moved, extra: ["originalBounds": rectArray(originalFrame)])
        try press("Destroy Settings window (test)")
        try waitForNoSettings()
        try sendComma()
        var restored = try waitForSettings()
        let restoreDeadline = ProcessInfo.processInfo.systemUptime + 8
        repeat {
            if let sample = settingsWindow() { restored = sample }
            observe("geometry-restore-sample", restored, extra: ["savedBounds": rectArray(moved.frame)])
            if abs(restored.frame.origin.x - moved.frame.origin.x) < 3
                && abs(restored.frame.origin.y - moved.frame.origin.y) < 3
                && abs(restored.frame.width - moved.frame.width) < 3
                && abs(restored.frame.height - moved.frame.height) < 3 { break }
            RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.1))
        } while ProcessInfo.processInfo.systemUptime < restoreDeadline
        let geometryRestored = abs(restored.frame.origin.x - moved.frame.origin.x) < 3
            && abs(restored.frame.origin.y - moved.frame.origin.y) < 3
            && abs(restored.frame.width - moved.frame.width) < 3
            && abs(restored.frame.height - moved.frame.height) < 3
        let newInstance = restored.windowID != moved.windowID
        observe("S08-A09", restored, extra: ["savedBounds": rectArray(moved.frame), "restoredBounds": rectArray(restored.frame), "newInstance": newInstance, "visibleFlagExcluded": true, "caseId": "S08-MAC-04-window-state-and-view-restore"])
        try captureWholeDesktop("s08-geometry-restored.png")
        emitVerdict("S08-A09", expected: knownAssertions["S08-A09"]!, actual: "newInstance=\(newInstance); geometryRestored=\(geometryRestored)", pass: geometryRestored && newInstance)

        let recreatedViewMarker: String = try waitUntil("recreated Team page and saved scroll marker") {
            guard let marker = self.textValuePrefix("Page: Team; scroll: "), marker == afterReopen else { return nil }
            return marker
        }
        let viewStateRestored = recreatedViewMarker == afterReopen && !recreatedViewMarker.hasSuffix("scroll: 0")
        let teamPose = find("Team") != nil && viewStateRestored
        observe("S08-A10", restored, extra: ["teamPose": teamPose, "pageScrollMarker": recreatedViewMarker, "matchesBeforeDestroy": viewStateRestored, "caseId": "S08-MAC-04-window-state-and-view-restore"])
        try captureWholeDesktop("s08-s4-18-restored.png")
        emitVerdict("S08-A10", expected: knownAssertions["S08-A10"]!, actual: "teamPose=\(teamPose); viewStateRestored=\(viewStateRestored); nativeWindowID=\(restored.windowID ?? -1)", pass: teamPose && viewStateRestored)
    }

    private func runMockLock() throws {
        try openSettingsAndSelect("General")
        try press("Simulate vault lock (test)")
        try waitForNoSettings()
        try sendComma()
        RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.3))
        let remainsClosed = settingsWindow() == nil
        try captureWholeDesktop("s08-mock-lock.png")
        try press("Unlock mock state (test)")
        try sendComma()
        let reopened = try waitForSettings()
        observe("S08-A11", reopened, extra: ["lockedShortcutStayedClosed": remainsClosed, "unlockedOpened": true, "caseId": "S08-MAC-05-mock-lock-destroys-settings"])
        emitVerdict("S08-A11", expected: knownAssertions["S08-A11"]!, actual: "lockedShortcutStayedClosed=\(remainsClosed); unlockedOpened=true", pass: remainsClosed && reopened.title == "Settings")
    }

    private func runPermissions() throws {
        try openSettingsAndSelect("General")
        try press("Run allowed command checks")
        let allowed: String = try waitUntil("all Settings allowed-command checks") {
            guard let result = self.findByPrefix("settings read:allowed") else { return nil }
            return result
        }
        let allAllowed = ["settings read:allowed", "settings write:allowed", "settings schema:allowed", "settings search:allowed", "shortcut editor:allowed", "vault passphrase:allowed", "vault recovery:allowed", "project settings:allowed", "team settings:allowed"].allSatisfy(allowed.contains)
        try captureWholeDesktop("s08-allowed-commands.png")
        var parentedNativeSurfaces: [Bool] = []
        try press("Request step-up")
        let stepUpSheets: [AXUIElement] = try waitUntil("parented step-up dialog") {
            guard let settings = self.settingsWindow() else { return nil }
            let sheets = self.sheets(for: settings)
            return sheets.count == 1 ? sheets : nil
        }
        let stepUpIsSheet = stepUpSheets.allSatisfy { stringAttribute($0, "AXRole") == "AXSheet" }
        parentedNativeSurfaces.append(stepUpIsSheet)
        observe("step-up-parent", settingsWindow(), extra: ["sheetRoles": stepUpSheets.map { stringAttribute($0, "AXRole") ?? "" }, "parentWindowID": settingsWindow()?.windowID ?? -1])
        try press("Cancel")
        for (buttonTitle, pickerTitle) in [
            ("Import licence (host picker)", "Open"),
            ("Export sample data (host picker)", "Save"),
            ("Import sample data (host picker)", "Open"),
        ] {
            try press(buttonTitle)
            let pickerSheets: [AXUIElement] = try waitUntil("parented \(pickerTitle) picker") {
                guard let settings = self.settingsWindow() else { return nil }
                let sheets = self.sheets(for: settings)
                return sheets.count == 1 ? sheets : nil
            }
            let pickerIsSheet = pickerSheets.allSatisfy { stringAttribute($0, "AXRole") == "AXSheet" }
            parentedNativeSurfaces.append(pickerIsSheet)
            observe("host-picker-open", settingsWindow(), extra: ["button": buttonTitle, "expectedPickerTitle": pickerTitle, "sheetRoles": pickerSheets.map { stringAttribute($0, "AXRole") ?? "" }, "parentWindowID": settingsWindow()?.windowID ?? -1])
            try press("Cancel")
        }
        try press("Hide Settings")
        try waitForNoSettings()
        try sendComma()
        _ = try waitForSettings()
        try press("Run denial probes")
        let denial = try waitUntil("all denial probes to finish") { self.findByPrefix("plugin:dialog|open:") }
        let denialIDs = [
            "plugin:s08-settings|s08_sentinel_tool_command:policy-denied",
            "plugin:s08-settings|s08_sentinel_pane_command:policy-denied",
            "plugin:s08-settings|s08_sentinel_tab_project_open:policy-denied",
            "plugin:s08-settings|s08_sentinel_mcp_command:policy-denied",
            "plugin:s08-settings|s08_sentinel_marketplace_command:policy-denied",
            "plugin:s08-settings|s08_sentinel_file_grant:policy-denied",
            "plugin:dialog|open:policy-denied",
        ]
        let allDenied = denialIDs.allSatisfy(denial.contains)
        try captureWholeDesktop("s08-denial-probes.png")
        let parentedPickers = parentedNativeSurfaces.count == 4 && parentedNativeSurfaces.allSatisfy { $0 }
        observe("S08-A12", settingsWindow(), extra: ["allowedCommandChecks": allAllowed, "parentedStepUpAndPickerSurfaces": parentedNativeSurfaces, "caseId": "S08-MAC-06-capability-and-host-allowlist"])
        emitVerdict("S08-A12", expected: knownAssertions["S08-A12"]!, actual: "allAllowed=\(allAllowed); parentedStepUpAndPickerSurfaces=\(parentedPickers); allowedResults=\(allowed)", pass: allAllowed && parentedPickers)
        observe("S08-A13", settingsWindow(), extra: ["denialResults": denial, "allPolicyDenied": allDenied, "caseId": "S08-MAC-06-capability-and-host-allowlist"])
        emitVerdict("S08-A13", expected: knownAssertions["S08-A13"]!, actual: "allPolicyDenied=\(allDenied); results=\(denial)", pass: allDenied)
    }

    private func openSettingsAndSelect(_ page: String) throws {
        guard process.activate(options: [.activateIgnoringOtherApps]) else { throw ProbeFailure(description: "Could not activate shell") }
        let main = try waitUntil("main window") { self.mainWindow() }
        try raise(main)
        _ = try waitUntil("main window to become key before Settings entry") { self.focusedWindow()?.windowID == main.windowID ? true : nil }
        try sendComma()
        _ = try waitForSettings()
        try press(page)
    }

    private func counterValue(_ prefix: String) -> String? {
        findByPrefix(prefix)
    }

    private func textValuePrefix(_ prefix: String) -> String? { findByPrefix(prefix) }

    private func findByPrefix(_ prefix: String) -> String? {
        guard let element = findElement(containing: prefix) else { return nil }
        return matchingAccessibilityText([
            stringAttribute(element, "AXValue"), stringAttribute(element, "AXTitle"),
            stringAttribute(element, "AXDescription"),
        ], containing: prefix)
    }

    private func findElement(containing text: String, in root: AXUIElement? = nil) -> AXUIElement? {
        let node = root ?? application
        let values = [stringAttribute(node, "AXTitle"), stringAttribute(node, "AXValue"), stringAttribute(node, "AXDescription")].compactMap { $0 }
        if values.contains(where: { $0.contains(text) }) { return node }
        guard let children = attribute(node, "AXChildren") as? [AXUIElement] else { return nil }
        for child in children {
            if let found = findElement(containing: text, in: child) { return found }
        }
        return nil
    }
}

func matchingAccessibilityText(_ values: [String?], containing text: String) -> String? {
    values.compactMap { $0 }.first { $0.contains(text) }
}

func attribute(_ element: AXUIElement, _ name: String) -> Any? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return nil }
    return value
}

func stringAttribute(_ element: AXUIElement, _ name: String) -> String? {
    attribute(element, name) as? String
}

func frameOf(_ element: AXUIElement) -> CGRect? {
    guard let positionObject = attribute(element, "AXPosition"),
          let sizeObject = attribute(element, "AXSize"),
          CFGetTypeID(positionObject as CFTypeRef) == AXValueGetTypeID(),
          CFGetTypeID(sizeObject as CFTypeRef) == AXValueGetTypeID() else { return nil }
    let positionValue = positionObject as! AXValue
    let sizeValue = sizeObject as! AXValue
    var position = CGPoint.zero
    var size = CGSize.zero
    guard AXValueGetValue(positionValue, .cgPoint, &position), AXValueGetValue(sizeValue, .cgSize, &size) else { return nil }
    return CGRect(origin: position, size: size)
}

func cgWindowID(frame: CGRect, title: String, pid: pid_t) -> Int? {
    guard let rows = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] else { return nil }
    return rows.first { row in
        guard let owner = row[kCGWindowOwnerPID as String] as? pid_t,
              owner == pid,
              let bounds = row[kCGWindowBounds as String] as? [String: Any],
              let nativeFrame = CGRect(dictionaryRepresentation: bounds as CFDictionary) else { return false }
        let name = row[kCGWindowName as String] as? String ?? ""
        let intersects = nativeFrame.insetBy(dx: -3, dy: -3).intersects(frame)
        return intersects && (title.isEmpty || name == title || name.isEmpty)
    }?[kCGWindowNumber as String] as? Int
}

func rectArray(_ rect: CGRect) -> [Double] { [rect.origin.x, rect.origin.y, rect.width, rect.height] }

func runProbe() throws {
    let options = try parseOptions()
    let probe = try Probe(options: options)
    try probe.run()
}

do {
    try runProbe()
} catch {
    let line = "S08 probe stopped: \(error)\n"
    FileHandle.standardError.write(Data(line.utf8))
    exit(2)
}
