import AppKit
import CoreGraphics
import Foundation
import ImageIO

private struct PixelFrame {
    let width: Int
    let height: Int
    let rgba: [UInt8]

    func color(x: Int, y: Int) -> (Double, Double, Double)? {
        guard x >= 0, y >= 0, x < width, y < height else { return nil }
        let offset = (y * width + x) * 4
        return (Double(rgba[offset]) / 255, Double(rgba[offset + 1]) / 255, Double(rgba[offset + 2]) / 255)
    }
}

private struct Marker {
    let sequence: Int
    let phase: Int
}

private struct NativeTimelineEntry {
    let timestampNanoseconds: Int64
    let sequence: Int
    let kind: String
    let snapshot: [String: Any]
}

private struct FullscreenTransition {
    let timestampNanoseconds: Int64
    let sequence: Int
    let target: Bool
    let settledTimestampNanoseconds: Int64?
}

private struct AssertionRow: Encodable {
    let id: String
    let caseId: String
    let expected: String
    let actual: String
    let verdict: String
    let evidence: [String]
}

private func readJSONLines(_ url: URL) throws -> [[String: Any]] {
    let content = try String(contentsOf: url, encoding: .utf8)
    return try content.split(whereSeparator: \.isNewline).map { line in
        guard let data = String(line).data(using: .utf8),
              let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw NSError(domain: "S01", code: 1, userInfo: [NSLocalizedDescriptionKey: "invalid JSONL row in \(url.lastPathComponent)"])
        }
        return value
    }
}

private func numbers(_ value: Any?, count: Int = 4) -> [Double]? {
    guard let values = value as? [NSNumber], values.count == count else { return nil }
    return values.map(\.doubleValue)
}

private func loadPixels(_ url: URL) -> PixelFrame? {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { return nil }
    let width = image.width
    let height = image.height
    var bytes = [UInt8](repeating: 0, count: width * height * 4)
    let info = CGBitmapInfo.byteOrder32Big.union(CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue))
    let rendered = bytes.withUnsafeMutableBytes { buffer -> Bool in
        guard let context = CGContext(
            data: buffer.baseAddress,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: info.rawValue
        ) else { return false }
        context.translateBy(x: 0, y: CGFloat(height))
        context.scaleBy(x: 1, y: -1)
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        return true
    }
    return rendered ? PixelFrame(width: width, height: height, rgba: bytes) : nil
}

private func trafficLightPixel(_ color: (Double, Double, Double)) -> Bool {
    let (red, green, blue) = color
    let redLight = red > 0.50 && red > green * 1.35 && red > blue * 1.25
    let yellowLight = red > 0.58 && green > 0.34 && red > green * 1.08 && green > blue * 1.30
    let greenLight = green > 0.36 && green > red * 1.18 && green > blue * 0.90
    return redLight || yellowLight || greenLight
}

private func decodeMarker(
    pixels: PixelFrame,
    contentRect: [Double],
    displayRect: [Double],
    displayPixels: [Double]
) -> Marker? {
    guard displayRect[2] > 0, displayRect[3] > 0, displayPixels[0] > 0, displayPixels[1] > 0 else { return nil }
    let scaleX = displayPixels[0] / displayRect[2]
    let scaleY = displayPixels[1] / displayRect[3]
    let contentLeftPx = (contentRect[0] - displayRect[0]) * scaleX
    let contentTopPx = (displayRect[1] + displayRect[3] - contentRect[1] - contentRect[3]) * scaleY
    // s01.js fixes the 136pt marker 8pt from the viewport's right and top.
    // The 26 monochrome cells start 5pt from the panel left and 24pt from top.
    let codeLeftPx = contentLeftPx + (contentRect[2] - 139) * scaleX
    let codeTopPx = contentTopPx + 24 * scaleY
    var sequence = 0
    var phase = 0
    for bit in 0..<26 {
        let sampleX = Int((codeLeftPx + (Double(bit) * 4 + 1.5) * scaleX).rounded())
        let sampleY = Int((codeTopPx + 4 * scaleY).rounded())
        guard let color = pixels.color(x: sampleX, y: sampleY) else { return nil }
        let dark = color.0 < 0.45 && color.1 < 0.45 && color.2 < 0.45
        if bit < 24 {
            sequence = (sequence << 1) | (dark ? 1 : 0)
        } else {
            phase = (phase << 1) | (dark ? 1 : 0)
        }
    }
    return Marker(sequence: sequence, phase: phase)
}

private func mappedPixel(
    xAppKit: Double,
    yAppKit: Double,
    displayRect: [Double],
    displayPixels: [Double]
) -> (Double, Double) {
    let scaleX = displayPixels[0] / displayRect[2]
    let scaleY = displayPixels[1] / displayRect[3]
    let x = (xAppKit - displayRect[0]) * scaleX
    let y = (displayRect[1] + displayRect[3] - yAppKit) * scaleY
    return (x, y)
}

private func lightPixels(
    pixels: PixelFrame,
    centerX: Double,
    rowTopY: Double,
    rowHeightPx: Double,
    diameterPx: Double
) -> [(Int, Int)] {
    let xRadius = max(5, Int((diameterPx / 2 + 2).rounded(.up)))
    let minX = max(0, Int(centerX.rounded()) - xRadius)
    let maxX = min(pixels.width - 1, Int(centerX.rounded()) + xRadius)
    let minY = max(0, Int(rowTopY.rounded()))
    let maxY = min(pixels.height - 1, Int((rowTopY + rowHeightPx).rounded()))
    guard minX <= maxX, minY <= maxY else { return [] }
    var found: [(Int, Int)] = []
    for y in minY...maxY {
        for x in minX...maxX {
            if let color = pixels.color(x: x, y: y), trafficLightPixel(color) {
                found.append((x, y))
            }
        }
    }
    return found
}

private func readBoolean(_ value: Any?) -> Bool? {
    (value as? NSNumber)?.boolValue
}

private func run() throws {
    guard CommandLine.arguments.count == 3 else {
        fputs("usage: analyze_capture.swift <artifact-directory> <case-file>\n", stderr)
        exit(64)
    }
    let artifact = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
    let caseFile = URL(fileURLWithPath: CommandLine.arguments[2])
    let caseDocument = try JSONSerialization.jsonObject(with: Data(contentsOf: caseFile)) as? [String: Any]
    let declaredRows = caseDocument?["assertions"] as? [[String: Any]] ?? []
    var declaredAssertions: [(id: String, expected: String)] = []
    for row in declaredRows {
        guard let id = row["id"] as? String, !id.isEmpty else { continue }
        let expected = row["expected"] as? String ?? ""
        declaredAssertions.append((id, expected))
    }
    guard !declaredAssertions.isEmpty else {
        throw NSError(domain: "S01", code: 2, userInfo: [NSLocalizedDescriptionKey: "case file has no declared S01 assertions"])
    }
    let eventsURL = artifact.appendingPathComponent("events.jsonl")
    let uiEventsURL = artifact.appendingPathComponent("ui-events.jsonl")
    let indexURL = artifact.appendingPathComponent("video/capture-index.jsonl")
    let outputURL = artifact.appendingPathComponent("assertions.json")
    let nativeEvents = try readJSONLines(eventsURL)
    let uiEvents = try readJSONLines(uiEventsURL)
    let frameIndex = try readJSONLines(indexURL)
    var snapshots: [Int: [String: Any]] = [:]
    var nativeTimeline: [NativeTimelineEntry] = []
    var fullscreenTransitions: [FullscreenTransition] = []
    var creationSequenceIds = Set<Int>()
    for event in nativeEvents {
        guard let sequence = (event["sequenceId"] as? NSNumber)?.intValue else { continue }
        let kind = event["kind"] as? String ?? ""
        if kind == "creation-position-snapshot" { creationSequenceIds.insert(sequence) }
        if kind == "fullscreen-transition-intent",
           let target = readBoolean(event["requestedFullscreen"]),
           let timestamp = (event["monotonicNanoseconds"] as? NSNumber)?.int64Value {
            fullscreenTransitions.append(FullscreenTransition(timestampNanoseconds: timestamp, sequence: sequence, target: target, settledTimestampNanoseconds: nil))
        }
        guard let native = event["native"] as? [String: Any] else { continue }
        if ["creation-position-snapshot", "creation-position-verified", "native-reposition-returned", "fullscreen-native-state-poll", "fullscreen-native-state-settled", "fullscreen-exit-preposition"].contains(kind) {
            snapshots[sequence] = native
            if let timestamp = (event["monotonicNanoseconds"] as? NSNumber)?.int64Value {
                nativeTimeline.append(NativeTimelineEntry(timestampNanoseconds: timestamp, sequence: sequence, kind: kind, snapshot: native))
            }
        }
    }
    nativeTimeline.sort { $0.timestampNanoseconds < $1.timestampNanoseconds }
    fullscreenTransitions.sort { $0.timestampNanoseconds < $1.timestampNanoseconds }
    fullscreenTransitions = fullscreenTransitions.map { transition in
        let settledAt = nativeTimeline.first {
            $0.sequence == transition.sequence
                && $0.timestampNanoseconds >= transition.timestampNanoseconds
                && readBoolean($0.snapshot["isFullscreen"]) == transition.target
        }?.timestampNanoseconds
        return FullscreenTransition(
            timestampNanoseconds: transition.timestampNanoseconds,
            sequence: transition.sequence,
            target: transition.target,
            settledTimestampNanoseconds: settledAt
        )
    }
    func nativeEntry(at timestampNanoseconds: Int64) -> NativeTimelineEntry? {
        nativeTimeline.last { $0.timestampNanoseconds <= timestampNanoseconds }
    }
    var caseBySequence: [Int: String] = [:]
    for event in uiEvents where (event["kind"] as? String) == "state-settled" || (event["kind"] as? String) == "S1-13-settled" {
        if let sequence = (event["visibleSequence"] as? NSNumber)?.intValue,
           let caseId = event["caseId"] as? String {
            caseBySequence[sequence] = caseId
        }
    }
    var fullscreenCaseBySequence: [Int: String] = [:]
    for event in uiEvents where (event["kind"] as? String) == "action" {
        guard let expected = event["expected"] as? String,
              expected.contains("fullscreen="),
              let visibleSequence = (event["visibleSequence"] as? NSNumber)?.intValue,
              let caseId = event["caseId"] as? String else { continue }
        fullscreenCaseBySequence[visibleSequence + 1] = caseId
    }

    var output: [AssertionRow] = []
    func add(_ id: String, _ caseId: String, _ expected: String, _ actual: String, _ verdict: String, _ pointer: String) {
        output.append(AssertionRow(id: id, caseId: caseId, expected: expected, actual: actual, verdict: verdict, evidence: [pointer]))
    }
    func addMany(_ id: String, _ caseId: String, _ expected: String, _ actual: String, _ verdict: String, _ pointers: [String]) {
        output.append(AssertionRow(id: id, caseId: caseId, expected: expected, actual: actual, verdict: verdict, evidence: pointers))
    }

    let orderedSequences = snapshots.keys.sorted()
    let baselineFrames = orderedSequences.first.flatMap { snapshots[$0]?["lights"] as? [[String: Any]] } ?? []
    let baselineXByName = Dictionary(uniqueKeysWithValues: baselineFrames.compactMap { light -> (String, Double)? in
        guard let name = light["name"] as? String,
              let frame = numbers(light["appkitFrame"]) else { return nil }
        return (name, frame[0])
    })
    for sequence in creationSequenceIds {
        let native = snapshots[sequence]
        let frames = native?["lights"] as? [[String: Any]] ?? []
        let measured = frames.compactMap { light -> String? in
            guard let name = light["name"] as? String,
                  let frame = numbers(light["appkitFrame"]),
                  let center = (light["centerYFromContentTop"] as? NSNumber)?.doubleValue else { return nil }
            return "\(name) frame=[\(frame.map { String(format: "%.2f", $0) }.joined(separator: ","))] centre=\(String(format: "%.2f", center))pt"
        }
        let verdict = measured.count == 3 ? "PASS" : "UNVERIFIED"
        let actual = measured.isEmpty ? "no pre-reposition AppKit frame data" : measured.joined(separator: "; ")
        add("S01-CREATION-POSITION", "S01-CREATION", "Record all three AppKit frames from the creation-time x14/y14 config before runtime reposition", actual, verdict, "events.jsonl")
    }
    for sequence in orderedSequences {
        guard let native = snapshots[sequence] else { continue }
        let caseId = caseBySequence[sequence] ?? (creationSequenceIds.contains(sequence) ? "S01-CREATION" : "S01-sequence-\(sequence)")
        let pointer = "events.jsonl"
        guard let frames = native["lights"] as? [[String: Any]], frames.count == 3 else {
            add("S01-CENTER-ROW1", caseId, "Three native button centres within 1 logical point of row-1 centre", "native snapshot does not contain three button frames", "UNVERIFIED", pointer)
            add("S01-NATIVE-GEOMETRY-SUPPLEMENTAL", caseId, "Native x positions, diameters and gaps are measured", "native snapshot does not contain three button frames", "UNVERIFIED", pointer)
            continue
        }
        guard let expectedCenter = (native["expectedCenterYFromContentTop"] as? NSNumber)?.doubleValue else {
            add("S01-CENTER-ROW1", caseId, "Three native button centres within 1 logical point of row-1 centre", "native snapshot has no row-1 centre target", "UNVERIFIED", pointer)
            continue
        }
        let errors = frames.compactMap { light -> Double? in
            guard let center = (light["centerYFromContentTop"] as? NSNumber)?.doubleValue else { return nil }
            return abs(center - expectedCenter)
        }
        if errors.count == 3 {
            let maximum = errors.max() ?? .infinity
            add("S01-CENTER-ROW1", caseId, "Three native button centres within 1 logical point of row-1 centre", "maximum AppKit frame error \(String(format: "%.3f", maximum))pt", maximum <= 1 ? "PASS" : "FAIL", pointer)
        } else {
            add("S01-CENTER-ROW1", caseId, "Three native button centres within 1 logical point of row-1 centre", "native snapshot does not contain three centre measurements", "UNVERIFIED", pointer)
        }

        var supplementalFailures: [String] = []
        var orderedButtonFrames: [(String, [Double])] = []
        for light in frames {
            guard let name = light["name"] as? String,
                  let frame = numbers(light["appkitFrame"]) else {
                supplementalFailures.append("missing frame")
                continue
            }
            orderedButtonFrames.append((name, frame))
            if abs(frame[2] - 12) > 1 || abs(frame[3] - 12) > 1 {
                supplementalFailures.append("\(name) diameter \(frame[2])x\(frame[3])pt")
            }
            if let baselineX = baselineXByName[name], abs(frame[0] - baselineX) > 1 {
                supplementalFailures.append("\(name) x changed by more than 1pt")
            }
        }
        orderedButtonFrames.sort { $0.1[0] < $1.1[0] }
        if orderedButtonFrames.count == 3 {
            for index in 0..<2 {
                let current = orderedButtonFrames[index].1
                let next = orderedButtonFrames[index + 1].1
                let gap = next[0] - (current[0] + current[2])
                if abs(gap - 8) > 1 { supplementalFailures.append("native gap \(String(format: "%.2f", gap))pt") }
            }
        }
        let supplementalActual = supplementalFailures.isEmpty ? "12pt button frames, 8pt gaps, and stable x positions" : supplementalFailures.joined(separator: "; ")
        add("S01-NATIVE-GEOMETRY-SUPPLEMENTAL", caseId, "12pt buttons, 8pt gaps, and stable initial x positions", supplementalActual, supplementalFailures.isEmpty ? "PASS" : "FAIL", pointer)
    }

    var previousFrameNumber: Int?
    var previousTimestamp: Int64?
    var timestampDeltas: [Int64] = []
    var analyzedFrames = 0
    var s1_13CasesSeen = Set<String>()
    var sequenceFrameCounts: [Int: Int] = [:]
    var sequenceOldFlash: [Int: Bool] = [:]
    var sequencePixelsUnresolved: [Int: Bool] = [:]
    var scaleSequencesReported = Set<Int>()
    var markerStreamStarted = false
    var previousFrameExpectedCenter: Double?
    var fullscreenTransitionFrames: [Int: Int] = [:]
    var fullscreenTransitionUnresolvedFrames: [Int: Int] = [:]
    var cadenceFailure = false
    var cadenceUnresolved = false
    var decodedImageFrames = 0
    var captureFrameFailures = 0
    var decodedMarkerFrames = 0
    var markerFailures = 0
    var nativeTimingFailures = 0
    for row in frameIndex {
        guard let frameNumber = (row["frameNumber"] as? NSNumber)?.intValue,
              let timestamp = (row["timestampNanoseconds"] as? NSNumber)?.int64Value else {
            cadenceUnresolved = true
            add("S01-CAPTURE-CADENCE", "S01-CAPTURE", "Every frame has an index and monotonic timestamp", "capture index lacks frameNumber or timestampNanoseconds", "UNVERIFIED", "video/capture-index.jsonl")
            continue
        }
        if let previousFrameNumber, frameNumber != previousFrameNumber + 1 {
            cadenceFailure = true
            add("S01-CAPTURE-CADENCE", "S01-CAPTURE", "No dropped frame indices", "frame index gap before frame \(frameNumber)", "FAIL", "video/capture-index.jsonl#frame=\(frameNumber)")
        }
        if let previousTimestamp {
            let delta = timestamp - previousTimestamp
            timestampDeltas.append(delta)
            if delta <= 0 || delta > 18_500_000 || delta < 10_000_000 {
                cadenceFailure = true
                add("S01-CAPTURE-CADENCE", "S01-CAPTURE", "Consecutive timestamped 60 fps frames without a duplicated or dropped interval", "frame interval \(delta) ns", "FAIL", "video/capture-index.jsonl#frame=\(frameNumber)")
            }
        }
        previousFrameNumber = frameNumber
        previousTimestamp = timestamp

        let frameIndexPointer = "video/capture-index.jsonl"
        guard let relativePath = row["relativePath"] as? String,
              !relativePath.hasPrefix("/"), !relativePath.contains(".."),
              let contentRect = numbers(row["windowContentRectAppkit"]),
              let displayRect = numbers(row["displayFrameAppkit"]),
              let displayPixels = numbers(row["displayPixelSize"], count: 2),
              let backingScale = (row["backingScaleFactor"] as? NSNumber)?.doubleValue,
              backingScale > 0 else {
            if !markerStreamStarted { continue }
            captureFrameFailures += 1
            markerFailures += 1
            add("S01-CAPTURE-FRAME", "S01-CAPTURE", "Every frame has a safe relative image path and display mapping", "frame index row is missing required mapping fields", "UNVERIFIED", frameIndexPointer)
            continue
        }
        guard let pixels = loadPixels(artifact.appendingPathComponent(relativePath)) else {
            if !markerStreamStarted { continue }
            captureFrameFailures += 1
            markerFailures += 1
            add("S01-CAPTURE-FRAME", "S01-CAPTURE", "Every indexed frame image is readable", "could not decode \(relativePath)", "UNVERIFIED", frameIndexPointer)
            continue
        }
        guard let marker = decodeMarker(pixels: pixels, contentRect: contentRect, displayRect: displayRect, displayPixels: displayPixels),
              marker.sequence > 0 else {
            if !markerStreamStarted { continue }
            decodedImageFrames += 1
            markerFailures += 1
            add("S01-MARKER-CORRELATION", "S01-CAPTURE", "Visible S01 sequence and phase decode from every transition frame", "could not decode the visible sequence marker", "UNVERIFIED", frameIndexPointer)
            continue
        }
        markerStreamStarted = true
        decodedImageFrames += 1
        decodedMarkerFrames += 1
        let framePointer = relativePath
        let activeTransition = fullscreenTransitions.last { transition in
            transition.timestampNanoseconds <= timestamp
                && (transition.settledTimestampNanoseconds.map { timestamp <= $0 } ?? true)
        }
        guard let nativeEvent = nativeEntry(at: timestamp) else {
            nativeTimingFailures += 1
            add("S01-NATIVE-TIMING", "S01-CAPTURE", "Every S01 frame maps to the latest preceding native-state event in the same monotonic clock", "no native snapshot timestamped at or before this frame", framePointer)
            continue
        }
        let native = nativeEvent.snapshot
        let transitionCaseId = activeTransition.flatMap { fullscreenCaseBySequence[$0.sequence] ?? caseBySequence[$0.sequence] }
        let observedSequence = max(marker.sequence, nativeEvent.sequence)
        var caseId = caseBySequence[observedSequence]
            ?? fullscreenCaseBySequence[observedSequence]
            ?? transitionCaseId
            ?? caseBySequence[marker.sequence]
            ?? (creationSequenceIds.contains(observedSequence) ? "S01-CREATION" : nil)
            ?? "S01-sequence-\(observedSequence)"
        if let activeTransition {
            fullscreenTransitionFrames[activeTransition.sequence, default: 0] += 1
        }
        if let activeTransition, readBoolean(native["isFullscreen"]) != activeTransition.target {
            let latestPoll = nativeTimeline.last {
                $0.sequence == activeTransition.sequence
                    && $0.kind == "fullscreen-native-state-poll"
                    && $0.timestampNanoseconds >= activeTransition.timestampNanoseconds
                    && $0.timestampNanoseconds <= timestamp
            }
            let pollAge = latestPoll.map { timestamp - $0.timestampNanoseconds }
            if latestPoll == nil || (pollAge ?? .max) > 50_000_000 {
                fullscreenTransitionUnresolvedFrames[activeTransition.sequence, default: 0] += 1
                nativeTimingFailures += 1
                addMany("S01-FULLSCREEN-ANIMATION", transitionCaseId ?? caseId, "Native full-screen state is timestamp-resolved during every captured animation interval", "no native state poll within 50ms of frame timestamp", "UNVERIFIED", ["events.jsonl", framePointer])
                continue
            }
            caseId = transitionCaseId ?? caseId
        }
        analyzedFrames += 1
        let pointer = framePointer
        sequenceFrameCounts[observedSequence, default: 0] += 1
        let isFullscreen = readBoolean(native["isFullscreen"]) ?? false
        let phaseIsSettled = marker.phase == 2
        let row1Height = (native["row1Height"] as? NSNumber)?.doubleValue ?? 0
        let expectedCenter = (native["expectedCenterYFromContentTop"] as? NSNumber)?.doubleValue ?? row1Height / 2
        let scaleX = displayPixels[0] / displayRect[2]
        let scaleY = displayPixels[1] / displayRect[3]
        let contentLeftPx = (contentRect[0] - displayRect[0]) * scaleX
        let contentTopPx = (displayRect[1] + displayRect[3] - contentRect[1] - contentRect[3]) * scaleY

        if scaleSequencesReported.insert(observedSequence).inserted {
            let nativeScale = (native["backingScaleFactor"] as? NSNumber)?.doubleValue
            let compatible = nativeScale.map { abs($0 - scaleX) <= 0.05 && abs($0 - scaleY) <= 0.05 } ?? false
            let actualScale = nativeScale.map { "window backing scale \(String(format: "%.2f", $0)); capture mapping \(String(format: "%.3f", scaleX))x\(String(format: "%.3f", scaleY))" } ?? "native snapshot has no backing scale"
            addMany("S01-BACKING-SCALE", caseId, "Native backing scale and capture display-pixel mapping are recorded and compatible", actualScale, compatible ? "PASS" : "UNVERIFIED", ["events.jsonl", framePointer])
        }

        if isFullscreen {
            if phaseIsSettled { s1_13CasesSeen.insert(caseId) }
            var colored = 0
            let roiLeft = max(0, Int(contentLeftPx.rounded()))
            let roiRight = min(pixels.width - 1, Int((contentLeftPx + 78 * scaleX).rounded()))
            let roiTop = max(0, Int(contentTopPx.rounded()))
            let roiBottom = min(pixels.height - 1, Int((contentTopPx + row1Height * scaleY).rounded()))
            let roiValid = roiLeft <= roiRight && roiTop <= roiBottom
            if roiValid {
                for y in roiTop...roiBottom {
                    for x in roiLeft...roiRight where pixels.color(x: x, y: y).map(trafficLightPixel) == true {
                        colored += 1
                    }
                }
            }
            let expectedFullscreen = phaseIsSettled
                ? "0 native traffic-light pixels after full-screen state settles"
                : "0 native traffic-light pixels in every correlated full-screen transition frame"
            let roiVerdict = roiValid ? (colored == 0 ? "PASS" : "FAIL") : "UNVERIFIED"
            let roiActual = roiValid
                ? "\(colored) traffic-light-classified pixels; marker phase \(marker.phase)"
                : "calibrated 78px titlebar region falls outside the indexed frame"
            add("S1-13", caseId, "\(expectedFullscreen) in the calibrated 78px titlebar control region", roiActual, roiVerdict, pointer)
            previousFrameExpectedCenter = expectedCenter
            continue
        }

        guard let contentFrames = native["lights"] as? [[String: Any]], contentFrames.count == 3 else {
            add("S01-CENTER-ROW1", caseId, "Three native AppKit button frames", "native snapshot lacks three button frames", "UNVERIFIED", pointer)
            continue
        }

        var centers: [Double] = []
        var missingLight = false
        let previousNativeLights = snapshots[observedSequence - 1]?["lights"] as? [[String: Any]] ?? []
        for light in contentFrames {
            guard let name = light["name"] as? String,
                  let contentFrame = numbers(light["contentFrame"]),
                  let centerFromTop = (light["centerYFromContentTop"] as? NSNumber)?.doubleValue else {
                missingLight = true
                continue
            }
            let centerXAppKit = contentRect[0] + contentFrame[0] + contentFrame[2] / 2
            let centerYAppKit = contentRect[1] + contentRect[3] - centerFromTop
            let (centerXpx, _) = mappedPixel(xAppKit: centerXAppKit, yAppKit: centerYAppKit, displayRect: displayRect, displayPixels: displayPixels)
            let (leftPx, topPx) = mappedPixel(xAppKit: contentRect[0], yAppKit: contentRect[1] + contentRect[3], displayRect: displayRect, displayPixels: displayPixels)
            let rowTopPx = topPx
            let diameterPx = max(contentFrame[2], contentFrame[3]) * scaleY
            let found = lightPixels(pixels: pixels, centerX: centerXpx, rowTopY: rowTopPx, rowHeightPx: row1Height * scaleY, diameterPx: diameterPx)
            if found.isEmpty {
                missingLight = true
                continue
            }
            let meanY = Double(found.reduce(0) { $0 + $1.1 }) / Double(found.count)
            let targetY = contentTopPx + expectedCenter * scaleY
            let currentError = abs(meanY - targetY) / scaleY
            centers.append(currentError)
            let priorNativeCenter = previousNativeLights.first { ($0["name"] as? String) == name }
                .flatMap { ($0["centerYFromContentTop"] as? NSNumber)?.doubleValue }
            let priorExpectedCandidates = [previousFrameExpectedCenter, priorNativeCenter].compactMap { $0 }
            for previousExpected in Set(priorExpectedCandidates) where abs(previousExpected - expectedCenter) > 0.5 {
                let previousTargetY = contentTopPx + previousExpected * scaleY
                let previousError = abs(meanY - previousTargetY) / scaleY
                if previousError <= 1 && currentError > 1 {
                    sequenceOldFlash[observedSequence] = true
                } else if previousError <= 1 && currentError <= 1 {
                    // At a sub-diameter shift, a blended/stale capture can
                    // overlap both accepted centre tolerances. Do not claim
                    // that a single centroid proves which native image was
                    // presented in that frame.
                    sequencePixelsUnresolved[observedSequence] = true
                }
            }
        }
        if missingLight || centers.count != 3 {
            sequencePixelsUnresolved[observedSequence] = true
            add("S01-CENTER-ROW1", caseId, "Three visible native lights with measured centres", "pixel classifier found \(centers.count) of 3 lights; visibility/colour could not be resolved", "UNVERIFIED", pointer)
        } else {
            let maximumError = centers.max() ?? .infinity
            add("S01-CENTER-ROW1", caseId, "Each native light centre within 1 logical point of row-1 centre", "maximum per-light pixel-centroid error \(String(format: "%.3f", maximumError)) logical points", maximumError <= 1 ? "PASS" : "FAIL", pointer)
        }
        previousFrameExpectedCenter = expectedCenter
    }

    for (sequence, caseId) in caseBySequence {
        let native = snapshots[sequence]
        guard readBoolean(native?["isFullscreen"]) != true else { continue }
        let frameCount = sequenceFrameCounts[sequence] ?? 0
        if frameCount == 0 {
            add("S01-NO-OLD-POSITION-FLASH", caseId, "No old-position light pixels after the visible sequence changes", "no correlated capture frames for sequence \(sequence)", "UNVERIFIED", "video/capture-index.jsonl")
            continue
        }
        let flashed = sequenceOldFlash[sequence] ?? false
        let unresolved = sequencePixelsUnresolved[sequence] ?? false
        let verdict = flashed ? "FAIL" : unresolved ? "UNVERIFIED" : "PASS"
        let actual = flashed
            ? "stale or overlapping old-position light pixels found"
            : unresolved
                ? "one or more correlated frames did not resolve all three native lights"
                : "no old-position pixels across \(frameCount) correlated frames"
        addMany("S01-NO-OLD-POSITION-FLASH", caseId, "No old-position light pixels after the visible sequence changes", actual, verdict, ["events.jsonl", "video/capture-index.jsonl"])
    }
    for transition in fullscreenTransitions {
        let count = fullscreenTransitionFrames[transition.sequence] ?? 0
        let unresolved = fullscreenTransitionUnresolvedFrames[transition.sequence] ?? 0
        let caseId = fullscreenCaseBySequence[transition.sequence] ?? caseBySequence[transition.sequence] ?? "S01-sequence-\(transition.sequence)"
        let verdict = count == 0 || unresolved > 0 ? "UNVERIFIED" : "PASS"
        let actual = count == 0
            ? "no timestamp-correlated capture frame in the transition interval"
            : unresolved > 0
                ? "\(unresolved) of \(count) transition frames lacked a recent native state poll"
                : "all \(count) transition frames mapped to recent native state; full-screen pixel assertions are reported separately"
        addMany("S01-FULLSCREEN-ANIMATION", caseId, "Every full-screen transition frame is captured and mapped to native state", actual, verdict, ["events.jsonl", "video/capture-index.jsonl"])
    }
    for requiredCase in ["S1-13-comfortable-rows", "S1-13-compact-rows", "S1-13-comfortable-capsules", "S1-13-compact-capsules"] where !s1_13CasesSeen.contains(requiredCase) {
        add("S1-13", requiredCase, "Settled full-screen frames show zero native traffic-light pixels", "no correlated settled full-screen frames for this density/layout", "UNVERIFIED", "video/capture-index.jsonl")
    }

    let cadenceVerdict = cadenceFailure ? "FAIL" : (cadenceUnresolved || timestampDeltas.isEmpty ? "UNVERIFIED" : "PASS")
    let cadenceActual = frameIndex.isEmpty
        ? "capture index is empty"
        : cadenceFailure
            ? "one or more frame numbers or timestamp intervals are out of sequence"
            : cadenceUnresolved || timestampDeltas.isEmpty
                ? "capture index lacks enough complete timestamps to verify cadence"
                : "all \(frameIndex.count) indexed frames are consecutive with valid monotonic intervals"
    add("S01-CAPTURE-CADENCE", "S01-CAPTURE", "Timestamped consecutive full-desktop frames without dropped or duplicated intervals", cadenceActual, cadenceVerdict, "video/capture-index.jsonl")

    let imageVerdict = decodedImageFrames == 0 ? "UNVERIFIED" : (captureFrameFailures == 0 ? "PASS" : "UNVERIFIED")
    let imageActual = decodedImageFrames == 0
        ? "no readable S01 frame images were correlated"
        : captureFrameFailures == 0
            ? "decoded \(decodedImageFrames) S01 frame images with usable display mappings"
            : "\(captureFrameFailures) S01 frame images or display mappings were unresolved"
    add("S01-CAPTURE-FRAME", "S01-CAPTURE", "Every indexed S01 frame has a safe path, readable pixels and usable display mapping", imageActual, imageVerdict, "video/capture-index.jsonl")

    let markerVerdict = decodedMarkerFrames == 0 ? "UNVERIFIED" : (markerFailures == 0 ? "PASS" : "UNVERIFIED")
    let markerActual = decodedMarkerFrames == 0
        ? "no visible sequence markers decoded"
        : markerFailures == 0
            ? "decoded sequence and phase markers in \(decodedMarkerFrames) frames"
            : "decoded \(decodedMarkerFrames) markers with \(markerFailures) unresolved frame correlations"
    add("S01-MARKER-CORRELATION", "S01-CAPTURE", "Transition frames decode and correlate to the native event stream", markerActual, markerVerdict, "video/capture-index.jsonl")

    let timingVerdict = analyzedFrames == 0 ? "UNVERIFIED" : (nativeTimingFailures == 0 ? "PASS" : "UNVERIFIED")
    let timingActual = analyzedFrames == 0
        ? "no frame mapped to a timestamped native snapshot"
        : nativeTimingFailures == 0
            ? "mapped \(analyzedFrames) frames to preceding native-state events"
            : "\(nativeTimingFailures) frames lacked a resolvable native-state time or poll"
    add("S01-NATIVE-TIMING", "S01-CAPTURE", "Every correlated capture frame maps to native events on the same monotonic clock", timingActual, timingVerdict, "events.jsonl")
    if !caseBySequence.isEmpty {
        let unmatched = caseBySequence.keys.filter { sequenceFrameCounts[$0] == nil }
        for sequence in unmatched {
            let caseId = caseBySequence[sequence] ?? "S01-sequence-\(sequence)"
            add("S01-MARKER-CORRELATION", caseId, "Every settled UI state maps to timestamped full-desktop frames", "no frame carries visible sequence \(sequence)", "UNVERIFIED", "video/capture-index.jsonl")
        }
    }
    if timestampDeltas.isEmpty == false {
        let mean = Double(timestampDeltas.reduce(0, +)) / Double(timestampDeltas.count)
        let measuredHz = 1_000_000_000 / mean
        add("S01-CAPTURE-FPS", "S01-CAPTURE", "Measured capture cadence at least 59 fps", "\(String(format: "%.3f", measuredHz)) fps from frame timestamps", measuredHz >= 59 ? "PASS" : "FAIL", "video/capture-index.jsonl")
    } else {
        add("S01-CAPTURE-FPS", "S01-CAPTURE", "Measured capture cadence at least 59 fps", "fewer than two timestamped frames", "UNVERIFIED", "video/capture-index.jsonl")
    }

    let rowsByID = Dictionary(grouping: output, by: \.id)
    let declaredIDs = Set(declaredAssertions.map { $0.id })
    let unexpectedIDs = Set(output.map { $0.id }).subtracting(declaredIDs).sorted()
    let aggregated: [AssertionRow] = declaredAssertions.map { declaration in
        let observations = rowsByID[declaration.id] ?? []
        let verdict: String
        if observations.contains(where: { $0.verdict == "FAIL" }) {
            verdict = "FAIL"
        } else if observations.isEmpty || observations.contains(where: { $0.verdict != "PASS" }) || !unexpectedIDs.isEmpty {
            verdict = "UNVERIFIED"
        } else {
            verdict = "PASS"
        }
        let observationText = observations.isEmpty
            ? "UNVERIFIED: analyzer produced no observation for declared assertion \(declaration.id)"
            : observations.map { "\($0.caseId): \($0.verdict) — \($0.actual)" }.joined(separator: " | ")
        let actual = unexpectedIDs.isEmpty
            ? observationText
            : "\(observationText); undeclared analyzer IDs: \(unexpectedIDs.joined(separator: ", "))"
        let evidence = Array(Set(observations.flatMap(\.evidence))).sorted()
        return AssertionRow(
            id: declaration.id,
            caseId: "S01-CAPTURE",
            expected: declaration.expected,
            actual: actual,
            verdict: verdict,
            evidence: evidence
        )
    }
    let data = try JSONEncoder().encode(["results": aggregated])
    try data.write(to: outputURL, options: .atomic)
    let failed = aggregated.filter { $0.verdict == "FAIL" }.count
    let unverified = aggregated.filter { $0.verdict == "UNVERIFIED" }.count
    print("S01 capture assertions: \(aggregated.count); fail=\(failed); unverified=\(unverified)")
}

do {
    try run()
} catch {
    fputs("S01 capture analysis error: \(error)\n", stderr)
    exit(1)
}

