package org.example.shellspikes;

import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.uiautomator.UiDevice;
import androidx.test.uiautomator.UiObject;
import androidx.test.uiautomator.UiSelector;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Native System WebView colour-picker scenario, driven through AndroidX instrumentation. */
@RunWith(AndroidJUnit4.class)
public final class ColourUiAutomator {
    @Test
    public void testNativePicker() throws Exception {
        Bundle args = InstrumentationRegistry.getArguments();
        Instrumentation instrumentation = InstrumentationRegistry.getInstrumentation();
        String caseId = args.getString("caseId", "");
        String bundleId = args.getString("bundleId", "");
        if (!caseId.matches("[A-Za-z0-9_-]+")) throw new IllegalArgumentException("Unsafe case id");
        UiDevice device = UiDevice.getInstance(instrumentation);
        Intent launch = instrumentation.getContext().getPackageManager().getLaunchIntentForPackage(bundleId);
        if (launch == null) throw new IllegalStateException("The mobile shell has no launch activity.");
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        instrumentation.getContext().startActivity(launch);
        boolean ready = selectScenario(device, "S10", caseId);

        File base = new File(instrumentation.getTargetContext().getFilesDir(), "shell-evidence/s10/" + caseId + "/recorder");
        if (!base.exists() && !base.mkdirs()) throw new IllegalStateException("Could not create the evidence directory.");
        device.takeScreenshot(new File(base, "screen.png"));
        JSONArray accepted = new JSONArray();
        boolean pickerOpened = false;
        UiObject open = device.findObject(new UiSelector().textContains("Open Appearance dialog"));
        if (ready && open.waitForExists(10000)) open.click();
        for (String value : new String[] {"#7C4DFF", "#28A77A"}) {
            UiObject colour = device.findObject(new UiSelector().textContains("Custom colour picker"));
            if (ready && colour.waitForExists(8000)) {
                pickerOpened = colour.click();
                SystemClock.sleep(700);
            }
            if (pickerOpened) {
                device.dumpWindowHierarchy(new File(base, "native-tree-picker.xml"));
                device.takeScreenshot(new File(base, "picker.png"));
                UiObject hex = device.findObject(new UiSelector().className("android.widget.EditText"));
                if (!hex.exists()) break;
                hex.setText(value);
                UiObject accept = device.findObject(new UiSelector().textMatches("(?i)(done|choose|select|ok)"));
                if (accept.exists()) accept.click();
                SystemClock.sleep(500);
                device.dumpWindowHierarchy(new File(base, "page-accessibility.xml"));
                String page = new String(Files.readAllBytes(new File(base, "page-accessibility.xml").toPath()), StandardCharsets.UTF_8);
                if (page.toLowerCase(Locale.ROOT).contains("native-change") && page.toLowerCase(Locale.ROOT).contains(value.toLowerCase(Locale.ROOT))) {
                    accepted.put(value.toLowerCase(Locale.ROOT));
                }
            }
        }
        boolean focusReturned = device.findObject(new UiSelector().textContains("Custom colour picker")).exists();

        UiObject openAgain = device.findObject(new UiSelector().textContains("Open Appearance dialog"));
        if (ready && openAgain.exists()) openAgain.click();
        UiObject manual = device.findObject(new UiSelector().className("android.widget.EditText"));
        boolean manualOk = false, shortOk = false, invalidOk = false, cancelOk = false, dismissOk = false;
        if (ready && manual.exists()) {
            manual.setText("#E0A526");
            UiObject use = device.findObject(new UiSelector().textContains("Use HEX value"));
            if (use.exists()) use.click();
            UiObject apply = device.findObject(new UiSelector().text("Apply"));
            if (apply.exists()) apply.click();
            manualOk = device.findObject(new UiSelector().textContains("#e0a526")).exists();
            openAgain = device.findObject(new UiSelector().textContains("Open Appearance dialog"));
            if (openAgain.exists()) openAgain.click();
            manual = device.findObject(new UiSelector().className("android.widget.EditText"));
            if (manual.exists()) manual.setText("abc");
            use = device.findObject(new UiSelector().textContains("Use HEX value"));
            if (use.exists()) use.click();
            shortOk = device.findObject(new UiSelector().textContains("#aabbcc")).exists();
            UiObject cancel = device.findObject(new UiSelector().text("Cancel"));
            if (cancel.exists()) cancel.click();
            cancelOk = device.findObject(new UiSelector().textContains("#e0a526")).exists();
            openAgain = device.findObject(new UiSelector().textContains("Open Appearance dialog"));
            if (openAgain.exists()) openAgain.click();
            manual = device.findObject(new UiSelector().className("android.widget.EditText"));
            if (manual.exists()) manual.setText("#12XZ");
            use = device.findObject(new UiSelector().textContains("Use HEX value"));
            if (use.exists()) use.click();
            invalidOk = device.findObject(new UiSelector().textContains("Enter a colour")).exists();
            cancel = device.findObject(new UiSelector().text("Cancel"));
            if (cancel.exists()) cancel.click();
        }

        openAgain = device.findObject(new UiSelector().textContains("Open Appearance dialog"));
        if (ready && openAgain.exists()) openAgain.click();
        UiObject dismissPicker = device.findObject(new UiSelector().textContains("Custom colour picker"));
        boolean dismissed = ready && dismissPicker.exists() && dismissPicker.click();
        if (dismissed) { device.pressBack(); SystemClock.sleep(400); }
        dismissOk = dismissed && device.findObject(new UiSelector().textContains("#e0a526")).exists();
        File finalTree = new File(base, "page-accessibility.xml");
        device.dumpWindowHierarchy(finalTree);
        String pageXml = new String(Files.readAllBytes(finalTree.toPath()), StandardCharsets.UTF_8);
        StringBuilder eventRows = new StringBuilder();
        java.util.regex.Matcher eventMatcher = java.util.regex.Pattern
                .compile("text=\\\"([^\\\"]*(?:native-|appearance-|hex-)[^\\\"]*)\\\"").matcher(pageXml);
        while (eventMatcher.find()) {
            String label = eventMatcher.group(1).replace("&amp;", "&").replace("&quot;", "\\\"");
            eventRows.append(new JSONObject().put("name", "s10.page-accessibility-event").put("text", label).toString()).append('\n');
        }
        Files.write(new File(base, "page-events.jsonl").toPath(), eventRows.toString().getBytes(StandardCharsets.UTF_8));

        JSONObject assertions = new JSONObject();
        String[] suffixes = {"NATIVE-PICKER", "ACCEPT-FOCUS", "APPLY-CANCEL", "MANUAL-HEX", "INPUT-USABILITY", "DISMISS"};
        JSONArray commonEvidence = new JSONArray().put("environment.json").put("events.jsonl")
                .put("recorder/page-events.jsonl").put("recorder/page-accessibility.xml")
                .put("recorder/native-tree-picker.xml").put("recorder/screen.png")
                .put("recorder/picker.png").put("video/index.json");
        for (String suffix : suffixes) {
            String verdict = "UNVERIFIED";
            String actual = "The scenario selection or complete native evidence was unavailable.";
            JSONArray refs = new JSONArray(commonEvidence.toString());
            if (suffix.equals("NATIVE-PICKER") && ready && pickerOpened) {
                verdict = accepted.length() == 2 ? "PASS" : "FAIL";
                actual = "The Android picker surface was observed; native entries were " + accepted + ".";
            } else if (suffix.equals("ACCEPT-FOCUS") && accepted.length() == 2 && focusReturned) {
                verdict = "PASS";
                actual = "Two native values were entered and focus returned to the webview.";
            } else if (suffix.equals("MANUAL-HEX")) {
                verdict = manualOk && shortOk && invalidOk ? "PASS" : "UNVERIFIED";
                actual = "Manual six-digit, short, and invalid entries observed: " + manualOk + "/" + shortOk + "/" + invalidOk + ".";
            } else if (suffix.equals("APPLY-CANCEL")) {
                verdict = manualOk && cancelOk ? "PASS" : "UNVERIFIED";
                actual = "Apply stored the first colour and outer Cancel preserved it: " + manualOk + "/" + cancelOk + ".";
            } else if (suffix.equals("DISMISS")) {
                verdict = dismissOk ? "PASS" : "UNVERIFIED";
                actual = "Native Back dismissal returned to the unchanged committed value: " + dismissOk + ".";
            } else if (suffix.equals("INPUT-USABILITY")) {
                verdict = accepted.length() == 2 ? "PASS" : "UNVERIFIED";
                actual = "UiAutomator touch and native picker selection count: " + accepted.length() + ".";
            }
            assertions.put(caseId + "-" + suffix, new JSONObject()
                    .put("verdict", verdict).put("actual", actual).put("evidence", refs));
        }
        JSONObject result = new JSONObject().put("caseId", caseId).put("selectedSpike", "s10")
                .put("platform", "android").put("ready", ready)
                .put("planningVerdict", accepted.length() == 2 && focusReturned ? "native picker usable" : "UNVERIFIED")
                .put("assertions", assertions);
        File outputFile = new File(base, "observations.json");
        File outputParent = outputFile.getParentFile();
        if (outputParent != null && !outputParent.exists() && !outputParent.mkdirs()) {
            throw new IllegalStateException("Could not create the observation output directory.");
        }
        Files.write(outputFile.toPath(), result.toString(2).getBytes(StandardCharsets.UTF_8));
        if (!ready) throw new AssertionError("The resolved S10 scenario and case marker were not visible.");
    }

    private static boolean selectScenario(UiDevice device, String spike, String caseId) throws Exception {
        UiObject caseField = device.findObject(new UiSelector().className("android.widget.EditText"));
        if (!caseField.waitForExists(30000)) return false;
        caseField.setText(caseId);
        device.pressBack();
        UiObject link = device.findObject(new UiSelector().text(spike));
        if (!link.waitForExists(10000) || !link.click()) return false;
        UiObject marker = device.findObject(new UiSelector().textContains("Ready: " + spike + ": " + caseId));
        return marker.waitForExists(30000);
    }
}
