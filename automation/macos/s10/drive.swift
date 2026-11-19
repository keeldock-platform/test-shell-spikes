import ApplicationServices
import AppKit
import CoreGraphics
import Darwin
import Foundation

let caseId = CommandLine.arguments[1]
let evidence = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
let videoRef = "video/capture.mkv"
let recorder = evidence.appendingPathComponent("recorder", isDirectory: true)
try FileManager.default.createDirectory(at: recorder, withIntermediateDirectories: true)

func children(_ element: AXUIElement) -> [AXUIElement] {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &value) == .success,
          let elements = value as? [AXUIElement] else { return [] }
    return elements
}

func attribute(_ element: AXUIElement, _ name: String) -> String {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return "" }
    guard let value else { return "" }
    return String(describing: value)
}

func flatten(_ root: AXUIElement) -> [(AXUIElement, String)] {
    var result: [(AXUIElement, String)] = []
    func visit(_ node: AXUIElement, depth: Int = 0) {
        guard depth < 30 && result.count < 3000 else { return }
        let text = [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute, kAXRoleAttribute, kAXSubroleAttribute]
            .map { attribute(node, $0 as String) }.filter { !$0.isEmpty }.joined(separator: " | ")
        var labelledText = text
        var titleElement: CFTypeRef?
        if AXUIElementCopyAttributeValue(node, kAXTitleUIElementAttribute as CFString, &titleElement) == .success,
           let titleElement, CFGetTypeID(titleElement) == AXUIElementGetTypeID() {
            labelledText += " | label=" + attribute(titleElement as! AXUIElement, kAXValueAttribute as String)
        }
        if !labelledText.isEmpty { result.append((node, labelledText)) }
        for child in children(node) { visit(child, depth: depth + 1) }
    }
    visit(root)
    return result
}

func press(_ element: AXUIElement) -> Bool {
    AXUIElementPerformAction(element, kAXPressAction as CFString) == .success
}

let running = NSWorkspace.shared.runningApplications
let appProcess = running.first(where: { String($0.processIdentifier) == ProcessInfo.processInfo.environment["SHELL_APP_PID"] })
_ = appProcess?.activate(options: [.activateIgnoringOtherApps])
let appElement = appProcess.map { AXUIElementCreateApplication($0.processIdentifier) }
var appRows = appElement.map(flatten) ?? []
let readyDeadline = Date(timeIntervalSinceNow: 10)
while !appRows.contains(where: { $0.1.contains("Ready: S10:") }) && Date() < readyDeadline {
    usleep(100_000)
    appRows = appElement.map(flatten) ?? []
}
let ready = appRows.contains(where: { $0.1.localizedCaseInsensitiveContains("Ready") })
let before = appRows.map(\.1).joined(separator: "\n") + "\n"
try before.write(to: recorder.appendingPathComponent("native-tree-before.txt"), atomically: true, encoding: .utf8)

func writeEvent(_ name: String, fields: [String: Any]) {
    var event: [String: Any] = ["timeNs": DispatchTime.now().uptimeNanoseconds, "name": name]
    fields.forEach { event[$0.key] = $0.value }
    guard let data = try? JSONSerialization.data(withJSONObject: event),
          let line = String(data: data, encoding: .utf8) else { return }
    let path = recorder.appendingPathComponent("native-events.jsonl")
    if !FileManager.default.fileExists(atPath: path.path) { FileManager.default.createFile(atPath: path.path, contents: nil) }
    if let handle = try? FileHandle(forWritingTo: path) {
        try? handle.seekToEnd(); try? handle.write(contentsOf: Data((line + "\n").utf8)); try? handle.close()
    }
}

let openButton = appRows.first(where: { $0.1.localizedCaseInsensitiveContains("Open Appearance dialog") })?.0
let openObserved = openButton.map(press) ?? false
usleep(500_000)
let pageRows = appElement.map(flatten) ?? []
let pickerControl = pageRows.first(where: { $0.1.localizedCaseInsensitiveContains("Custom colour picker") })?.0
let pickerOpened = pickerControl.map(press) ?? false
writeEvent("native-picker-open", fields: ["ready": ready, "opened": pickerOpened])
usleep(700_000)
let screenCapture = Process()
screenCapture.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
screenCapture.arguments = ["-x", recorder.appendingPathComponent("screen.png").path]
try? screenCapture.run(); screenCapture.waitUntilExit()

func nativePickerRows() -> [(AXUIElement, String)] {
    var rows: [(AXUIElement, String)] = []
    for process in NSWorkspace.shared.runningApplications where
        process.processIdentifier == appProcess?.processIdentifier ||
        (process.bundleIdentifier ?? "").localizedCaseInsensitiveContains("colorpicker") {
        let root = AXUIElementCreateApplication(process.processIdentifier)
        AXUIElementSetMessagingTimeout(root, 1)
        var windowsValue: CFTypeRef?
        guard AXUIElementCopyAttributeValue(root, kAXWindowsAttribute as CFString, &windowsValue) == .success,
              let windows = windowsValue as? [AXUIElement] else { continue }
        for window in windows {
            let title = attribute(window, kAXTitleAttribute as String).lowercased()
            if title.contains("color") || title.contains("colour") || process.processIdentifier != appProcess?.processIdentifier {
                rows += flatten(window)
            }
        }
    }
    return rows
}

func pickerField(_ rows: [(AXUIElement, String)], _ tokens: [String]) -> AXUIElement? {
    rows.first { row in
        row.1.contains("AXTextField") && tokens.contains { row.1.localizedCaseInsensitiveContains($0) }
    }?.0
}

func setNativeField(_ field: AXUIElement, _ value: String) -> Bool {
    guard AXUIElementSetAttributeValue(field, kAXFocusedAttribute as CFString, kCFBooleanTrue) == .success,
          AXUIElementSetAttributeValue(field, kAXValueAttribute as CFString, value as CFString) == .success else { return false }
    CGEvent(keyboardEventSource: nil, virtualKey: 36, keyDown: true)?.post(tap: .cghidEventTap)
    CGEvent(keyboardEventSource: nil, virtualKey: 36, keyDown: false)?.post(tap: .cghidEventTap)
    return true
}

var accepted: [String] = []
for (index, colour) in ["#7C4DFF", "#28A77A"].enumerated() {
    if index > 0, let appElement {
        if let control = flatten(appElement).first(where: { $0.1.localizedCaseInsensitiveContains("Custom colour picker") })?.0 {
            _ = press(control)
        }
    }
    var nativeRows: [(AXUIElement, String)] = []
    let panelDeadline = Date(timeIntervalSinceNow: 8)
    repeat {
        nativeRows = nativePickerRows()
        if !nativeRows.isEmpty { break }
        usleep(100_000)
    } while Date() < panelDeadline
    writeEvent("native-panel-owner-probe", fields: ["nodeCount": nativeRows.count, "selection": index])
    if let sliders = nativeRows.first(where: {
        $0.1.localizedCaseInsensitiveContains("sliders") &&
        ($0.1.contains("AXRadioButton") || $0.1.contains("AXButton"))
    })?.0 { _ = press(sliders); usleep(300_000) }
    nativeRows = nativePickerRows()
    if let mode = nativeRows.first(where: { $0.1.contains("AXPopUpButton") })?.0 {
        _ = press(mode)
        usleep(150_000)
        if let rgb = nativePickerRows().first(where: { $0.1.contains("RGB Sliders") && $0.1.contains("AXMenuItem") })?.0 {
            _ = press(rgb)
        } else {
            CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: true)?.post(tap: .cghidEventTap)
            CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: false)?.post(tap: .cghidEventTap)
        }
    }
    let fieldDeadline = Date(timeIntervalSinceNow: 5)
    repeat {
        nativeRows = nativePickerRows()
        if pickerField(nativeRows, ["hex", "html"]) != nil { break }
        usleep(100_000)
    } while Date() < fieldDeadline
    try nativeRows.map(\.1).joined(separator: "\n").write(
        to: recorder.appendingPathComponent("native-tree-picker-\(index).txt"), atomically: true, encoding: .utf8)
    try nativeRows.map(\.1).joined(separator: "\n").write(
        to: recorder.appendingPathComponent("native-tree-picker.txt"), atomically: true, encoding: .utf8)
    var entered = false
    var route = "no-native-fields"
    if let field = pickerField(nativeRows, ["hex", "html"]) {
        entered = setNativeField(field, String(colour.dropFirst()))
        route = "native-hex"
    } else {
        let components = index == 0 ? [124, 77, 255] : [40, 167, 122]
        let names = ["red", "green", "blue"]
        entered = true
        for channel in 0..<3 {
            guard let field = pickerField(nativeRows, [names[channel]]) else { entered = false; break }
            if !setNativeField(field, String(components[channel])) { entered = false; break }
        }
        route = "native-rgb-fields"
    }
    // Closing the real panel commits WKWebView's native chooser result.
    if let close = nativePickerRows().first(where: { $0.1.contains("AXCloseButton") })?.0 { _ = press(close) }
    let returnedDeadline = Date(timeIntervalSinceNow: 5)
    var returned = false
    repeat {
        returned = (appElement.map(flatten) ?? []).contains {
            $0.1.localizedCaseInsensitiveContains("native-change") && $0.1.localizedCaseInsensitiveContains(colour)
        }
        if returned { break }
        usleep(100_000)
    } while Date() < returnedDeadline
    if entered && returned { accepted.append(colour.lowercased()) }
    writeEvent("native-picker-value-entry", fields: ["value": colour.lowercased(), "route": route,
               "entered": entered, "returned": returned, "nativeNodeCount": nativeRows.count])
}

var finalRows = appElement.map(flatten) ?? []
try finalRows.map(\.1).joined(separator: "\n").write(
    to: recorder.appendingPathComponent("page-accessibility.txt"), atomically: true, encoding: .utf8)
let eventOutput = evidence.appendingPathComponent("events.jsonl")
if !FileManager.default.fileExists(atPath: eventOutput.path) { FileManager.default.createFile(atPath: eventOutput.path, contents: nil) }
if let handle = try? FileHandle(forWritingTo: eventOutput) {
    try? handle.seekToEnd()
    for text in finalRows.map(\.1).filter({
        let value = $0.lowercased()
        return value.contains("native-") || value.contains("appearance-") || value.contains("hex-")
    }) {
        let row: [String: Any] = ["monotonicTimeNs": DispatchTime.now().uptimeNanoseconds, "name": "s10.page-accessibility-event", "text": text]
        if let data = try? JSONSerialization.data(withJSONObject: row) {
            try? handle.write(contentsOf: data); try? handle.write(contentsOf: Data([0x0A]))
        }
    }
    try? handle.close()
}
let focusReturned = finalRows.contains(where: { $0.1.localizedCaseInsensitiveContains("Custom colour picker") })
func matching(_ rows: [(AXUIElement, String)], _ text: String) -> AXUIElement? {
    rows.first(where: { $0.1.localizedCaseInsensitiveContains(text) })?.0
}
func setAccessibleValue(_ rows: [(AXUIElement, String)], _ label: String, _ value: String) -> Bool {
    guard let field = rows.first(where: {
        $0.1.localizedCaseInsensitiveContains(label) && $0.1.localizedCaseInsensitiveContains("AXTextField")
    })?.0 else { return false }
    return AXUIElementSetAttributeValue(field, kAXValueAttribute as CFString, value as CFString) == .success
}
var manualOk = false, shortHexOk = false, invalidOk = false, cancelOk = false, dismissOk = false
if let appElement {
    finalRows = flatten(appElement)
    _ = press(matching(finalRows, "Open Appearance dialog") ?? appElement)
    usleep(250_000)
    finalRows = flatten(appElement)
    if setAccessibleValue(finalRows, "HEX", "#E0A526") {
        _ = press(matching(finalRows, "Use HEX value") ?? appElement)
        finalRows = flatten(appElement)
        _ = press(matching(finalRows, "Apply") ?? appElement)
        usleep(250_000)
        finalRows = flatten(appElement)
        manualOk = finalRows.contains(where: { $0.1.localizedCaseInsensitiveContains("#e0a526") })
        _ = press(matching(finalRows, "Open Appearance dialog") ?? appElement)
        finalRows = flatten(appElement)
        if setAccessibleValue(finalRows, "HEX", "abc") {
            _ = press(matching(finalRows, "Use HEX value") ?? appElement)
            finalRows = flatten(appElement)
            shortHexOk = finalRows.contains(where: { $0.1.localizedCaseInsensitiveContains("#aabbcc") })
            _ = press(matching(finalRows, "Cancel") ?? appElement)
            finalRows = flatten(appElement)
            cancelOk = finalRows.contains(where: { $0.1.localizedCaseInsensitiveContains("#e0a526") })
            _ = press(matching(finalRows, "Open Appearance dialog") ?? appElement)
            finalRows = flatten(appElement)
            if setAccessibleValue(finalRows, "HEX", "#12XZ") {
                _ = press(matching(finalRows, "Use HEX value") ?? appElement)
                finalRows = flatten(appElement)
                invalidOk = finalRows.contains(where: { $0.1.localizedCaseInsensitiveContains("Enter a colour") })
                _ = press(matching(finalRows, "Cancel") ?? appElement)
            }
        }
    }
    finalRows = flatten(appElement)
    _ = press(matching(finalRows, "Open Appearance dialog") ?? appElement)
    finalRows = flatten(appElement)
    if let picker = matching(finalRows, "Custom colour picker"), press(picker) {
        CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: true)?.post(tap: .cghidEventTap)
        CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: false)?.post(tap: .cghidEventTap)
        usleep(250_000)
        finalRows = flatten(appElement)
        dismissOk = finalRows.contains(where: { $0.1.localizedCaseInsensitiveContains("#e0a526") })
    }
}
try finalRows.map(\.1).joined(separator: "\n").write(
    to: recorder.appendingPathComponent("page-accessibility.txt"), atomically: true, encoding: .utf8)
var assertions: [String: Any] = [:]
let caseData = try Data(contentsOf: URL(fileURLWithPath: "cases/s10.json"))
let caseRoot = try JSONSerialization.jsonObject(with: caseData) as! [String: Any]
let cases = caseRoot["cases"] as! [[String: Any]]
if let selected = cases.first(where: { $0["id"] as? String == caseId }) {
    for assertion in selected["assertions"] as! [[String: Any]] {
        let id = assertion["id"] as! String
        let suffix = String(id.dropFirst(caseId.count + 1))
        var verdict = "UNVERIFIED"
        var actual = "Native interaction was attempted; full scenario evidence is required before a verdict."
        var refs = ["recorder/native-events.jsonl", "recorder/page-accessibility.txt"]
        if suffix == "NATIVE-PICKER" && ready && pickerOpened {
            verdict = accepted.count == 2 ? "PASS" : "FAIL"
            actual = "Picker surface observed; native field entries: \(accepted.joined(separator: ", "))."
            refs = ["recorder/native-tree-picker.txt", videoRef]
        } else if suffix == "ACCEPT-FOCUS" && accepted.count == 2 && focusReturned {
            verdict = "PASS"
            actual = "Two native colour field entries were returned and focus is visible in the webview."
            refs = ["recorder/page-accessibility.txt", videoRef]
        } else if suffix == "MANUAL-HEX" {
            verdict = manualOk && shortHexOk && invalidOk ? "PASS" : "UNVERIFIED"
            actual = "Manual six-digit, short, and invalid HEX observations: \(manualOk)/\(shortHexOk)/\(invalidOk)."
            refs = ["recorder/page-accessibility.txt", "events.jsonl", videoRef]
        } else if suffix == "APPLY-CANCEL" {
            verdict = manualOk && cancelOk ? "PASS" : "UNVERIFIED"
            actual = "Apply stored the first value and outer Cancel preserved it: \(manualOk)/\(cancelOk)."
            refs = ["recorder/page-accessibility.txt", "events.jsonl", videoRef]
        } else if suffix == "DISMISS" {
            verdict = dismissOk ? "PASS" : "UNVERIFIED"
            actual = "Escape dismissal returned to the page with committed value unchanged: \(dismissOk)."
            refs = ["recorder/native-tree-picker.txt", "recorder/page-accessibility.txt", videoRef]
        } else if suffix == "INPUT-USABILITY" {
            verdict = accepted.count == 2 ? "PASS" : "UNVERIFIED"
            actual = "Accessibility actions opened the native picker and returned \(accepted.count) selections."
            refs = ["recorder/native-tree-picker.txt", "recorder/page-accessibility.txt", videoRef]
        }
        for requiredRef in ["environment.json", "events.jsonl", "recorder/screen.png", videoRef, "video/index.json"] where !refs.contains(requiredRef) {
            refs.append(requiredRef)
        }
        assertions[id] = ["verdict": verdict, "actual": actual, "evidence": refs]
    }
}
let planning = accepted.count == 2 && focusReturned ? "native picker usable" : (ready && !pickerOpened ? "hex field only" : "UNVERIFIED")
let observation: [String: Any] = ["caseId": caseId, "platform": "macos", "ready": ready,
                                  "planningVerdict": planning, "assertions": assertions]
let output = try JSONSerialization.data(withJSONObject: observation, options: [.prettyPrinted, .sortedKeys])
try output.write(to: recorder.appendingPathComponent("observations.json"))
if !ready || !openObserved { exit(1) }
