import XCTest

final class AccentUITests: XCTestCase {
    func testPolicyFixture() throws {
        let caseId = ProcessInfo.processInfo.environment["SHELL_CASE_ID"] ?? ""
        try captureDisplayProbe()
        let app = XCUIApplication()
        app.launchEnvironment = ProcessInfo.processInfo.environment.filter {
            $0.key.hasPrefix("SHELL_")
        }
        app.launch()
        let selected = !caseId.isEmpty && selectScenario(app, spike: "S11", caseId: caseId)

        // Keep the case-relative evidence names in the XCTest result bundle. The coordinator
        // exports these named attachments into the case artifact after xcodebuild finishes.
        func attach(_ name: String, data: Data, type: String) throws {
            let attachment = XCTAttachment(data: data, uniformTypeIdentifier: type)
            attachment.name = name
            attachment.lifetime = .keepAlways
            self.add(attachment)
        }

        let readyMarker = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS[c] %@", "Ready: S11: \(caseId)"))
            .firstMatch
        let ready = selected && readyMarker.waitForExistence(timeout: 30)
        let system = app.buttons["Use System accent"]
        let brand = app.buttons["Use brand accent"]
        let status = app.descendants(matching: .any).matching(NSPredicate(
            format: "label CONTAINS[c] %@ AND label CONTAINS %@ AND label CONTAINS %@",
            "System is hidden", "stored=system", "resolved=brand")).firstMatch
        let statusObserved = status.waitForExistence(timeout: 10)
        if brand.exists && !brand.isHittable { app.swipeUp() }
        let hidden = ready && (!system.exists || !system.isHittable) && brand.isHittable && statusObserved
        let screenshot = XCUIScreen.main.screenshot().pngRepresentation
        let nativeTree = app.debugDescription
        try attach("screens/ios-policy.png", data: screenshot, type: "public.png")
        try attach("recorder/native-tree.txt", data: Data(nativeTree.utf8), type: "public.plain-text")

        let assertionId = caseId + "-HIDDEN"
        let observation: [String: Any] = [
            "caseId": caseId,
            "selectedSpike": "s11",
            "platform": "ios",
            "ready": ready,
            "fallback": "System hidden; stored System resolves to the test brand colour.",
            "assertions": [assertionId: [
                "verdict": hidden ? "PASS" : (ready ? "FAIL" : "UNVERIFIED"),
                "actual": hidden ? "The policy fixture hid System and kept the brand control available." : "The native policy fixture did not expose complete accessibility evidence.",
                "evidence": ["environment.json", "events.jsonl", "recorder/native-tree.txt",
                             "screens/ios-policy.png", "video/index.json"],
            ]],
        ]
        let json = try JSONSerialization.data(withJSONObject: observation, options: [.prettyPrinted, .sortedKeys])
        try attach("recorder/observations.json", data: json, type: "public.json")
        XCTAssertTrue(ready, "The resolved S11 policy case marker was not visible.")
        XCTAssertTrue(hidden, "The policy must hide System and expose stored=system; resolved=brand with the brand control available.")
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
        if focus { tap() }
        if let current = value as? String, !current.isEmpty {
            typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: current.count))
        }
        typeText(text)
    }
}
