import XCTest

final class AccentUITests: XCTestCase {
    func testPolicyFixture() throws {
        let caseId = ProcessInfo.processInfo.environment["SHELL_CASE_ID"] ?? ""
        let app = XCUIApplication()
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
        let ready = selected && readyMarker.exists
        let system = app.buttons["Use System accent"]
        let brand = app.buttons["Use brand accent"]
        let status = app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", "System is hidden")).firstMatch
        let hidden = ready && (!system.exists || !system.isHittable) && brand.isHittable && status.exists
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
                "verdict": hidden ? "PASS" : "UNVERIFIED",
                "actual": hidden ? "The policy fixture hid System and kept the brand control available." : "The native policy fixture did not expose complete accessibility evidence.",
                "evidence": ["environment.json", "events.jsonl", "recorder/native-tree.txt",
                             "screens/ios-policy.png", "video/index.json"],
            ]],
        ]
        let json = try JSONSerialization.data(withJSONObject: observation, options: [.prettyPrinted, .sortedKeys])
        try attach("recorder/observations.json", data: json, type: "public.json")
        XCTAssertTrue(ready, "The resolved S11 policy case marker was not visible.")
    }

    private func selectScenario(_ app: XCUIApplication, spike: String, caseId: String) -> Bool {
        let caseField = app.textFields["Synthetic case ID"]
        guard caseField.waitForExistence(timeout: 20) else { return false }
        caseField.tap()
        caseField.clearAndEnterText(caseId)
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
    func clearAndEnterText(_ text: String) {
        tap()
        if let current = value as? String, !current.isEmpty {
            typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: current.count))
        }
        typeText(text)
    }
}
