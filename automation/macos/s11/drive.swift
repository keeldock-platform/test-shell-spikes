import Foundation
import Darwin

let caseId = CommandLine.arguments[1]
let evidence = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
let videoRef = "video/capture.mkv"
let recorder = evidence.appendingPathComponent("recorder", isDirectory: true)
try FileManager.default.createDirectory(at: recorder, withIntermediateDirectories: true)
let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)

func run(_ executable: String, _ arguments: [String], timeout: TimeInterval = 60) -> (Int32, String) {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: executable)
    task.arguments = arguments
    let output = Pipe()
    task.standardOutput = output
    task.standardError = output
    do {
        try task.run()
        task.waitUntilExit()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        return (task.terminationStatus, String(decoding: data, as: UTF8.self))
    } catch {
        return (127, String(describing: error))
    }
}

let fixtureOnly = ["S11-POLICY-WEB", "S11-MACOS-DEFAULT-BRAND-IDENTITY", "S11-CONTRAST-BOUNDARY-INJECTION",
                   "S11-HIGH-CONTRAST-IGNORES-SYSTEM", "S11-SYSTEM-UNAVAILABLE-RESOLVES-BRAND"].contains(caseId)
let selection = fixtureOnly ? (Int32(0), "No OS setting change is required for this page fixture.\n") :
    run("/usr/bin/osascript", [root.appendingPathComponent("automation/accent/macos-select-accent.applescript").path, "Purple"])
try selection.1.write(to: recorder.appendingPathComponent("accent-selection.txt"), atomically: true, encoding: .utf8)
let readback = fixtureOnly ? (Int32(0), "{}\n") :
    run("/usr/bin/swift", [root.appendingPathComponent("automation/accent/macos-readback.swift").path])
try readback.1.write(to: recorder.appendingPathComponent("native-readback.json"), atomically: true, encoding: .utf8)
let screenCapture = Process()
screenCapture.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
screenCapture.arguments = ["-x", recorder.appendingPathComponent("screen.png").path]
try? screenCapture.run(); screenCapture.waitUntilExit()

let eventFile = evidence.appendingPathComponent("events.jsonl")
let lines = (try? String(contentsOf: eventFile, encoding: .utf8).components(separatedBy: .newlines)) ?? []
let rows: [[String: Any]] = lines.compactMap { line in
    guard let data = line.data(using: .utf8) else { return nil }
    guard let row = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
          let pid = row["hostPid"] as? Int,
          String(pid) == ProcessInfo.processInfo.environment["SHELL_APP_PID"] else { return nil }
    return row
}
func eventName(_ row: [String: Any]) -> String {
    if let name = row["name"] as? String { return name }
    if let fields = row["fields"] as? [String: Any], let name = fields["name"] as? String { return name }
    return row["event"] as? String ?? ""
}
func eventFields(_ row: [String: Any]) -> [String: Any] { row["fields"] as? [String: Any] ?? row }
func rgb(_ row: [String: Any]) -> [Double]? {
    guard let values = eventFields(row)["rgb"] as? [NSNumber], values.count == 3 else { return nil }
    return values.map(\.doubleValue)
}
let readyEvents: Set<String> = [
    "s11.listener-ready", "s11.platform-policy", "s11.clamp-result",
    "s11.high-contrast-ignored-system",
]
let ready = rows.contains(where: { readyEvents.contains(eventName($0)) })
let readerReady = rows.contains(where: { eventName($0) == "s11.reader-ready" })
let native = rows.filter { eventName($0) == "s11.native-event" }
let updates = rows.filter { eventName($0) == "s11.host-and-token-update" }
let eventSequences = Set(native.compactMap { eventFields($0)["sequence"] as? Int })
let correlated = updates.filter { eventSequences.contains(eventFields($0)["sequence"] as? Int ?? -1) }
let frames = rows.filter { (eventFields($0)["phase"] as? String) == "tokens-mutated" }
let initial = rows.first(where: { eventName($0) == "s11.initial-reader-snapshot" })
let readbackRGB = (try? JSONSerialization.jsonObject(with: Data(contentsOf: recorder.appendingPathComponent("native-readback.json")))) as? [String: Any]
let independentRGB = readbackRGB?["rgb"] as? [NSNumber]
let hostRGB = initial.flatMap(rgb)
let readbackMatches = independentRGB?.count == 3 && hostRGB?.count == 3 && zip(independentRGB!, hostRGB!).allSatisfy { pair in
    abs(pair.0.doubleValue - pair.1) <= 1.0 / 255.0
}

let caseData = try Data(contentsOf: root.appendingPathComponent("cases/s11.json"))
let caseRoot = try JSONSerialization.jsonObject(with: caseData) as! [String: Any]
let cases = caseRoot["cases"] as! [[String: Any]]
let selected = cases.first(where: { $0["id"] as? String == caseId })
var assertions: [String: Any] = [:]
for item in selected?["assertions"] as? [[String: Any]] ?? [] {
    let id = item["id"] as! String
    let suffix = id
    var verdict = "UNVERIFIED"
    var actual = "The native setting/readback was attempted; synchronized presentation evidence is required."
    var refs = ["recorder/accent-selection.txt", "recorder/native-readback.json"]
    if suffix.contains("READBACK") {
        verdict = selection.0 == 0 && readback.0 == 0 && readerReady && readbackMatches ? "PASS" : "UNVERIFIED"
        actual = "Independent AppKit and host sRGB values agree within 1/255=\(readbackMatches); reader readiness observed=\(readerReady)."
        refs = ["recorder/accent-selection.txt", "recorder/native-readback.json", "events.jsonl"]
    } else if suffix.contains("EVENT") {
        verdict = !native.isEmpty && !correlated.isEmpty ? "PASS" : "UNVERIFIED"
        actual = "Native accent callbacks=\(native.count); sequence-matched renderer updates=\(correlated.count)."
        refs = ["events.jsonl", videoRef]
    } else if suffix.contains("FRAME") {
        verdict = "UNVERIFIED"
        actual = "Renderer frame markers=\(frames.count); the first presented-frame timestamp must be joined to full-screen capture."
        refs = ["events.jsonl", videoRef]
    } else if suffix.contains("UPDATE") {
        verdict = native.count == 1 && correlated.count == 1 && eventFields(correlated.first ?? [:])["reload"] as? Bool == false ? "PASS" : "UNVERIFIED"
        actual = "Native changes=\(native.count); sequence-matched host updates=\(correlated.count); reload=false required."
        refs = ["events.jsonl", videoRef]
    } else if caseId == "S11-CONTRAST-BOUNDARY-INJECTION" && id == "S11-CONTRAST-CLAMP" {
        let clamp = rows.first(where: { eventName($0) == "s11.clamp-result" }).map(eventFields)
        let clamped = clamp?["clamped"] as? Bool ?? ((clamp?["clampTarget"] as? String) != nil && (clamp?["clampTarget"] as? String) != "none")
        verdict = clamped ? "PASS" : "UNVERIFIED"
        actual = "Boundary injection was labelled non-native; clamp result observed=\(clamped)."
        refs = ["events.jsonl"]
    } else if caseId == "S11-CONTRAST-BOUNDARY-INJECTION" && id == "S11-CONTRAST-NATIVE" {
        let boundary = rows.first(where: { eventName($0) == "s11.boundary-injection" }).map(eventFields)
        let nonNative = boundary?["nativeEvent"] as? Bool == false
        verdict = nonNative ? "PASS" : "UNVERIFIED"
        actual = "Boundary sample native-event flag is false: \(nonNative)."
        refs = ["events.jsonl"]
    } else if caseId == "S11-HIGH-CONTRAST-IGNORES-SYSTEM" && id == "S11-HIGH-CONTRAST-IGNORED" {
        let sample = rows.first(where: { eventName($0) == "s11.high-contrast-ignored-system" }).map(eventFields)
        let ignored = (sample?["resolvedSource"] as? String) == "high-contrast-theme"
        verdict = ignored ? "PASS" : "UNVERIFIED"
        actual = "High-contrast preview resolved independently of System: \(ignored)."
        refs = ["events.jsonl", videoRef]
    } else if caseId == "S11-POLICY-WEB" && id == "S11-POLICY-WEB-HIDDEN" {
        let policy = rows.first(where: { eventName($0) == "s11.platform-policy" }).map(eventFields)
        let hidden = (policy?["platform"] as? String) == "web" && (policy?["systemVisible"] as? Bool) == false
        verdict = hidden ? "PASS" : "UNVERIFIED"
        actual = "Web policy fixture hid System without invoking a native reader: \(hidden)."
        refs = ["events.jsonl", videoRef]
    } else if caseId == "S11-SYSTEM-UNAVAILABLE-RESOLVES-BRAND" && id == "S11-SYSTEM-UNAVAILABLE-BRAND" {
        verdict = "UNVERIFIED"
        actual = "System unavailable fallback is selected; a visible brand-resolution capture is required."
        refs = ["events.jsonl", videoRef]
    } else if suffix.contains("CLAMP") {
        let clampRows = rows.filter { eventName($0) == "s11.host-and-token-update" }.map(eventFields)
        let clamped = clampRows.contains { $0["clamped"] as? Bool == true }
        verdict = clamped ? "PASS" : "UNVERIFIED"
        actual = "Observed native updates with an applied contrast clamp=\(clamped)."
        refs = ["recorder/native-readback.json", "events.jsonl", "recorder/screen.png", videoRef]
    } else if suffix.contains("FALLBACK") || suffix.contains("BRAND") {
        actual = "If the reader is unavailable, System is hidden and stored System resolves to the test brand colour."
        refs = ["events.jsonl", "recorder/native-readback.json", videoRef]
    }
    for requiredRef in ["environment.json", "events.jsonl", "recorder/screen.png", videoRef, "video/index.json"] where !refs.contains(requiredRef) {
        refs.append(requiredRef)
    }
    assertions[id] = ["verdict": verdict, "actual": actual, "evidence": refs]
}
let observation: [String: Any] = [
    "caseId": caseId, "platform": "macos", "ready": ready,
    "fallback": "System hidden; stored System resolves to the test brand colour.",
    "assertions": assertions,
]
let json = try JSONSerialization.data(withJSONObject: observation, options: [.prettyPrinted, .sortedKeys])
try json.write(to: recorder.appendingPathComponent("observations.json"))
if selection.0 != 0 || readback.0 != 0 { exit(1) }
