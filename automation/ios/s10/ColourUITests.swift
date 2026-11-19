import XCTest

final class ColourUITests: XCTestCase {
    func testNativeColourInput() throws {
        let caseId = ProcessInfo.processInfo.environment["SHELL_CASE_ID"] ?? ""
        try captureDisplayProbe()
        let app = XCUIApplication()
        app.launchEnvironment = ProcessInfo.processInfo.environment.filter {
            $0.key.hasPrefix("SHELL_")
        }
        app.launch()
        let ready = !caseId.isEmpty && selectScenario(app, spike: "S10", caseId: caseId)

        // Keep the case-relative evidence names in the XCTest result bundle. The coordinator
        // exports these named attachments into the case artifact after xcodebuild finishes.
        func attach(_ name: String, data: Data, type: String) throws {
            let attachment = XCTAttachment(data: data, uniformTypeIdentifier: type)
            attachment.name = name
            attachment.lifetime = .keepAlways
            self.add(attachment)
        }
        func attachText(_ name: String, _ text: String) throws {
            try attach(name, data: Data(text.utf8), type: "public.plain-text")
        }

        var assertions: [String: Any] = [:]
        let caseMarker = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS[c] %@", "Ready: S10: \(caseId)"))
            .firstMatch
        let selected = ready && caseMarker.waitForExistence(timeout: 30)
        let open = app.buttons["Open Appearance dialog"]
        if selected && open.waitForExistence(timeout: 10) { open.tap() }

        let pickerControl = app.descendants(matching: .colorWell)
            .matching(NSPredicate(format: "label == %@", "Custom colour picker"))
            .firstMatch
        var accepted: [String] = []
        var nativeTree = app.debugDescription
        var screenshots: [String: Data] = ["screens/ios-initial.png": XCUIScreen.main.screenshot().pngRepresentation]
        for value in ["#7C4DFF", "#28A77A"] {
            if selected && pickerControl.waitForExistence(timeout: 8) { pickerControl.tap() }
            // The page also has a field named HEX behind the native sheet.
            // iOS exposes the native hex field on the Sliders tab.
            let sliders = app.buttons["Sliders"]
            if sliders.waitForExistence(timeout: 3) && sliders.isHittable { sliders.tap() }
            let hexField = app.textFields.matching(NSPredicate(
                format: "label CONTAINS[c] %@ AND label != %@", "hex", "HEX")).firstMatch
            nativeTree = app.debugDescription
            if selected && hexField.waitForExistence(timeout: 8) && hexField.isHittable {
                hexField.clearAndEnterText(value.replacingOccurrences(of: "#", with: ""))
                screenshots["screens/ios-picker-\(accepted.count + 1).png"] = XCUIScreen.main.screenshot().pngRepresentation
                let accept = app.buttons.matching(NSPredicate(format:
                    "label CONTAINS[c] %@ OR label CONTAINS[c] %@ OR label CONTAINS[c] %@",
                    "Done", "Choose", "Select")).firstMatch
                if accept.exists { accept.tap() }
                let event = app.descendants(matching: .any)
                    .matching(NSPredicate(format: "label CONTAINS[c] %@ AND label CONTAINS[c] %@",
                                          "native-change", value.lowercased())).firstMatch
                if event.waitForExistence(timeout: 3) { accepted.append(value.lowercased()) }
            }
        }
        try attachText("recorder/native-tree-picker.txt", nativeTree)

        // Return from the native sheet and the existing Appearance dialog
        // before starting the independent manual-input sequence.
        let nativeDone = app.buttons["Done"]
        if nativeDone.exists && nativeDone.isHittable { nativeDone.tap() }
        let outerCancel = app.buttons["Cancel"]
        if outerCancel.exists && outerCancel.isHittable { outerCancel.tap() }
        let hexInput = app.textFields["HEX"]
        var manualOk = false
        var shortHexOk = false
        var invalidOk = false
        var cancelOk = false
        var dismissalPerformed = false
        if selected && open.exists { open.tap() }
        if selected && hexInput.waitForExistence(timeout: 5) {
            hexInput.clearAndEnterText("#E0A526")
            app.buttons["Use HEX value"].tap(); app.buttons["Apply"].tap()
            manualOk = app.staticTexts.containing(NSPredicate(format: "label CONTAINS[c] %@", "#e0a526")).firstMatch.exists
            if open.waitForExistence(timeout: 5) && open.isHittable { open.tap() }
            guard hexInput.waitForExistence(timeout: 5) && hexInput.isHittable else {
                try attachText("recorder/manual-input-failure.txt", app.debugDescription)
                XCTFail("Appearance HEX input did not reopen after Apply")
                return
            }
            hexInput.clearAndEnterText("abc"); app.buttons["Use HEX value"].tap()
            shortHexOk = app.staticTexts.containing(NSPredicate(format: "label CONTAINS[c] %@", "#aabbcc")).firstMatch.exists
            app.buttons["Cancel"].tap()
            cancelOk = app.staticTexts.containing(NSPredicate(format: "label CONTAINS[c] %@", "#e0a526")).firstMatch.exists
            if open.waitForExistence(timeout: 5) && open.isHittable { open.tap() }
            hexInput.clearAndEnterText("#12XZ"); app.buttons["Use HEX value"].tap()
            invalidOk = app.staticTexts.containing(NSPredicate(format: "label CONTAINS[c] %@", "Enter a colour")).firstMatch.exists
            app.buttons["Cancel"].tap()
        }
        if selected && open.exists { open.tap() }
        if selected && pickerControl.exists {
            pickerControl.tap()
            let nativeCancels = app.buttons.matching(identifier: "Cancel")
            if nativeCancels.firstMatch.waitForExistence(timeout: 2),
               let nativeCancel = nativeCancels.allElementsBoundByIndex.last {
                nativeCancel.tap()
                dismissalPerformed = true
            }
        }
        let dismissOk = app.staticTexts.containing(NSPredicate(format: "label CONTAINS[c] %@", "#e0a526")).firstMatch.exists
        screenshots["screens/ios-picker-dismiss.png"] = XCUIScreen.main.screenshot().pngRepresentation

        let pageTree = app.debugDescription
        try attachText("recorder/page-accessibility.txt", pageTree)
        let eventLines = pageTree.components(separatedBy: .newlines).filter {
            let value = $0.lowercased()
            return value.contains("native-") || value.contains("appearance-") || value.contains("hex-")
        }
        var eventRows = ""
        for line in eventLines {
            let row: [String: Any] = [
                "monotonicTimeNs": UInt64(ProcessInfo.processInfo.systemUptime * 1_000_000_000),
                "name": "s10.page-accessibility-event", "text": line,
            ]
            let data = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
            eventRows += String(decoding: data, as: UTF8.self) + "\n"
        }
        try attachText("events.jsonl", eventRows)
        for (name, data) in screenshots { try attach(name, data: data, type: "public.png") }

        let pickerVisible = nativeTree.localizedCaseInsensitiveContains("color") || nativeTree.localizedCaseInsensitiveContains("colour")
        let focusReturned = pickerControl.exists && pickerControl.isHittable
        let ids = ["NATIVE-PICKER", "ACCEPT-FOCUS", "APPLY-CANCEL", "MANUAL-HEX", "INPUT-USABILITY", "DISMISS"]
        for suffix in ids {
            let id = "\(caseId)-\(suffix)"
            var verdict = "UNVERIFIED"
            var actual = "The native scenario and case selection or complete capture evidence was unavailable."
            var refs = ["environment.json", "events.jsonl", "recorder/native-tree-picker.txt",
                        "recorder/page-accessibility.txt", "screens/ios-initial.png",
                        "screens/ios-picker-1.png", "video/index.json"]
            if suffix == "NATIVE-PICKER" && selected && pickerVisible {
                verdict = accepted.count == 2 ? "PASS" : "FAIL"
                actual = "The simulator picker was observed; native HEX entries recorded: \(accepted)."
            } else if suffix == "ACCEPT-FOCUS" && accepted.count == 2 && focusReturned {
                verdict = "PASS"
                actual = "Two native picker values were entered and focus returned to the webview control."
            } else if suffix == "MANUAL-HEX" {
                verdict = manualOk && shortHexOk && invalidOk ? "PASS" : "UNVERIFIED"
                actual = "Six-digit and short HEX actions observed: \(manualOk)/\(shortHexOk); invalid entry preserved state: \(invalidOk)."
            } else if suffix == "APPLY-CANCEL" {
                verdict = manualOk && cancelOk ? "PASS" : "UNVERIFIED"
                actual = "Apply stored the sample and outer Cancel preserved it after a separate draft: \(manualOk)/\(cancelOk)."
            } else if suffix == "DISMISS" {
                verdict = dismissOk && dismissalPerformed ? "PASS" : "UNVERIFIED"
                actual = "A supported native cancel route ran=\(dismissalPerformed); the committed sample stayed unchanged=\(dismissOk)."
                refs.append("screens/ios-picker-dismiss.png")
            } else if suffix == "INPUT-USABILITY" {
                verdict = accepted.count == 2 && pickerVisible ? "PASS" : "UNVERIFIED"
                actual = "XCUITest used native taps and text entry; native selections observed=\(accepted.count)."
                refs.append("screens/ios-picker-2.png")
            }
            assertions[id] = ["verdict": verdict, "actual": actual, "evidence": refs]
        }
        let observation: [String: Any] = [
            "caseId": caseId, "selectedSpike": "s10", "platform": "ios", "ready": selected,
            "planningVerdict": accepted.count == 2 && focusReturned ? "native picker usable" : (selected && !pickerVisible ? "hex field only" : "UNVERIFIED"),
            "assertions": assertions,
        ]
        let json = try JSONSerialization.data(withJSONObject: observation, options: [.prettyPrinted, .sortedKeys])
        try attach("recorder/observations.json", data: json, type: "public.json")
        XCTAssertTrue(selected, "The resolved S10 scenario and case marker were not visible.")
    }

    private func selectScenario(_ app: XCUIApplication, spike: String, caseId: String) -> Bool {
        let caseField = app.textFields["Synthetic case ID"]
        guard caseField.waitForExistence(timeout: 20) else { return false }
        if !caseField.isHittable { app.swipeDown() }
        guard caseField.isHittable else { return false }
        caseField.tap()
        let keyboard = app.keyboards.firstMatch
        if !keyboard.waitForExistence(timeout: 5) {
            caseField.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        }
        let keyboardReady = keyboard.waitForExistence(timeout: 5)
        let focusProbe = XCTAttachment(string: app.debugDescription)
        focusProbe.name = "scenario-keyboard-focus"
        focusProbe.lifetime = .keepAlways
        add(focusProbe)
        guard keyboardReady else {
            XCTFail("Synthetic case ID did not acquire a software keyboard after native taps")
            return false
        }
        caseField.clearAndEnterText(caseId, focus: false)
        // WKWebView's accessibility value can lag the completed text-entry event.
        let retainedValue = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            caseField.value as? String == caseId
        }, object: nil)
        let retained = XCTWaiter.wait(for: [retainedValue], timeout: 5) == .completed
        let valueProbe = XCTAttachment(string: "requested=\(caseId); AXValue=\(String(describing: caseField.value)); retained=\(retained)\n" + app.debugDescription)
        valueProbe.name = "scenario-entered-value"
        valueProbe.lifetime = .keepAlways
        add(valueProbe)
        guard retained else {
            XCTFail("Synthetic case ID did not retain the entered scenario; AXValue=\(String(describing: caseField.value))")
            return false
        }
        for label in ["Return", "Go", "Done"] {
            let returnKey = app.keyboards.buttons[label]
            if returnKey.exists { returnKey.tap(); break }
        }
        let link = app.links[spike]
        guard link.waitForExistence(timeout: 10) else { return false }
        link.tap()
        return app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS[c] %@", "Ready: \(spike): \(caseId)"))
            .firstMatch.waitForExistence(timeout: 30)
    }
}

private extension XCUIElement {
    func clearAndEnterText(_ text: String, focus: Bool = true) {
        if focus {
            guard waitForExistence(timeout: 5), isHittable else {
                XCTFail("Text entry target is not hittable: \(label)")
                return
            }
            tap()
            let keyboard = XCUIApplication().keyboards.firstMatch
            if !keyboard.waitForExistence(timeout: 5) {
                coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
            }
            guard keyboard.waitForExistence(timeout: 5) else {
                XCTFail("Text entry target did not acquire a keyboard: \(label)")
                return
            }
        }
        if let current = value as? String, !current.isEmpty {
            typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: current.count))
        }
        typeText(text)
    }
}
