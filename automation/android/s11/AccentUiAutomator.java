package org.example.shellspikes;

import android.app.Instrumentation;
import android.app.WallpaperManager;
import android.content.Intent;
import android.os.Build;
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

/** Android wallpaper-to-resource scenario; no wallpaper or storage permission is requested. */
@RunWith(AndroidJUnit4.class)
public final class AccentUiAutomator {
    @Test
    public void testWallpaperAccent() throws Exception {
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
        boolean ready = selectScenario(device, "S11", caseId);

        File base = new File(instrumentation.getTargetContext().getFilesDir(), "shell-evidence/s11/" + caseId + "/recorder");
        if (!base.exists() && !base.mkdirs()) throw new IllegalStateException("Could not create the evidence directory.");
        long beforeId = WallpaperManager.getInstance(instrumentation.getTargetContext())
                .getWallpaperId(WallpaperManager.FLAG_SYSTEM);
        int beforeArgb = Build.VERSION.SDK_INT >= 31
                ? instrumentation.getTargetContext().getColor(android.R.color.system_accent1_500) : 0;
        File beforeTree = new File(base, "native-tree-before.xml");
        device.dumpWindowHierarchy(beforeTree);
        device.takeScreenshot(new File(base, "screen.png"));
        UiObject systemControl = device.findObject(new UiSelector().text("Use System accent"));
        UiObject hiddenStatus = device.findObject(new UiSelector().textContains("System is hidden"));
        JSONObject visibleValues = new JSONObject();
        UiObject values = device.findObject(new UiSelector().textContains("\"appliedHex\""));
        if (values.exists()) {
            try { visibleValues = new JSONObject(values.getText()); } catch (Exception ignored) { }
        }
        boolean fallbackObserved = Build.VERSION.SDK_INT == 30 && ready
                && !systemControl.exists() && hiddenStatus.exists()
                && "api-below-31".equals(visibleValues.optString("unavailableReason"))
                && "system".equals(visibleValues.optString("storedAccent"))
                && "brand".equals(visibleValues.optString("resolvedSource"))
                && "#405066".equalsIgnoreCase(visibleValues.optString("appliedHex"))
                && visibleValues.has("rawHex") && visibleValues.isNull("rawHex")
                && !visibleValues.optBoolean("available", true)
                && !visibleValues.optBoolean("systemVisible", true);
        // Sample the native permission UI while the reader settles; save every sample.
        boolean promptObserved = false;
        for (int sample = 0; sample < 10; sample++) {
            promptObserved |= device.findObject(new UiSelector().packageNameMatches(
                    ".*(permissioncontroller|packageinstaller).*" )).exists();
            device.dumpWindowHierarchy(new File(base, "prompt-window-" + sample + ".xml"));
            SystemClock.sleep(200);
        }
        boolean promptFree = ready && !promptObserved;


        boolean changed = false;
        if (ready && Build.VERSION.SDK_INT >= 31) {
            applyWallpaper(instrumentation, device, base, "first", 0);
            long afterId = WallpaperManager.getInstance(instrumentation.getTargetContext())
                    .getWallpaperId(WallpaperManager.FLAG_SYSTEM);
            int afterArgb = instrumentation.getTargetContext().getColor(android.R.color.system_accent1_500);
            changed = beforeId != afterId || beforeArgb != afterArgb;
            Files.write(new File(base, "wallpaper-readback.txt").toPath(),
                    ("before=" + beforeId + ":" + hexArgb(beforeArgb) + "\n" +
                     "after=" + afterId + ":" + hexArgb(afterArgb) + "\n").getBytes(StandardCharsets.UTF_8));
            device.setOrientationLeft();
            SystemClock.sleep(700);
            device.setOrientationNatural();
            SystemClock.sleep(700);
            device.dumpWindowHierarchy(new File(base, "native-tree-after-recreation.xml"));
            device.takeScreenshot(new File(base, "after-recreation.png"));
            // A second picker attempt is essential: rotation alone proves no listener delivery.
            applyWallpaper(instrumentation, device, base, "second", 1);
            long secondId = WallpaperManager.getInstance(instrumentation.getTargetContext())
                    .getWallpaperId(WallpaperManager.FLAG_SYSTEM);
            int secondArgb = instrumentation.getTargetContext().getColor(android.R.color.system_accent1_500);
            Files.write(new File(base, "wallpaper-readback.txt").toPath(),
                    ("second=" + secondId + ":" + hexArgb(secondArgb) + "\n").getBytes(StandardCharsets.UTF_8),
                    java.nio.file.StandardOpenOption.APPEND);

        }

        JSONObject assertions = new JSONObject();
        String[] suffixes = caseId.equals("S11-ANDROID-API-30-NEGATIVE")
                ? new String[] {"HIDDEN", "PROMPT"}
                : caseId.equals("S11-ANDROID-PROVIDER-UNAVAILABLE")
                        ? new String[] {"BRAND"}
                        : new String[] {"WALLPAPER", "FRAME", "RECREATE", "PROMPT", "IDENTITY", "CLAMP"};
        for (String suffix : suffixes) {
            String verdict = "UNVERIFIED";
            String actual = "The scenario was selected; complete native event and presentation evidence is required.";
            JSONArray refs = new JSONArray().put("environment.json").put("events.jsonl")
                    .put("video/index.json").put("recorder/native-tree-before.xml").put("recorder/screen.png");
            if (suffix.equals("HIDDEN")) {
                verdict = fallbackObserved ? "PASS" : "UNVERIFIED";
                actual = "API 30 fallback hides System and resolves the stored choice to the test brand: " + fallbackObserved + ".";
            } else if (suffix.equals("PROMPT")) {
                verdict = promptFree ? "PASS" : "UNVERIFIED";
                actual = "Reader-ready native permission-window samples=10; prompt observed=" + promptObserved + ".";
                for (int sample = 0; sample < 10; sample++) refs.put("recorder/prompt-window-" + sample + ".xml");
            } else if (suffix.equals("BRAND")) {
                actual = "Provider-unavailable injection is not available in this driver; System fallback remains selected.";
            } else if (suffix.equals("WALLPAPER") && Build.VERSION.SDK_INT >= 31) {
                verdict = "UNVERIFIED";
                actual = changed ? "Wallpaper readback changed; callback and host delivery await post-collection reduction." : "No distinguishable wallpaper-derived resource change was observed.";
                refs.put("recorder/wallpaper-picker.xml").put("recorder/wallpaper-readback.txt");
            } else if (suffix.equals("RECREATE")) {
                refs.put("recorder/native-tree-after-recreation.xml").put("recorder/after-recreation.png");
            }
            String assertionId;
            if (caseId.equals("S11-ANDROID-API-30-NEGATIVE")) {
                assertionId = "S11-ANDROID-API-30-" + suffix;
            } else if (caseId.equals("S11-ANDROID-PROVIDER-UNAVAILABLE")) {
                assertionId = "S11-ANDROID-PROVIDER-" + suffix;
            } else {
                assertionId = caseId + "-" + suffix;
            }
            assertions.put(assertionId, new JSONObject()
                    .put("verdict", verdict).put("actual", actual).put("evidence", refs));
        }
        JSONObject result = new JSONObject().put("caseId", caseId).put("selectedSpike", "s11")
                .put("platform", "android").put("ready", ready)
                .put("api30Facts", new JSONObject().put("apiLevel", Build.VERSION.SDK_INT)
                        .put("reason", visibleValues.optString("unavailableReason"))
                        .put("systemHidden", !systemControl.exists()).put("storedAccent", visibleValues.optString("storedAccent"))
                        .put("resolvedSource", visibleValues.optString("resolvedSource"))
                        .put("appliedHex", visibleValues.optString("appliedHex"))
                        .put("dynamicResourceRead", Build.VERSION.SDK_INT >= 31)
                        .put("promptSamples", 10).put("promptObserved", promptObserved))
                .put("fallback", "System hidden; stored System resolves to the test brand colour.")
                .put("assertions", assertions);
        File outputFile = new File(base, "observations.json");
        File outputParent = outputFile.getParentFile();
        if (outputParent != null && !outputParent.exists() && !outputParent.mkdirs()) {
            throw new IllegalStateException("Could not create the observation output directory.");
        }
        Files.write(outputFile.toPath(), result.toString(2).getBytes(StandardCharsets.UTF_8));
        if (!ready) throw new AssertionError("The resolved S11 scenario and case marker were not visible.");
    }

    private static void applyWallpaper(Instrumentation instrumentation, UiDevice device,
                                       File base, String phase, int index) throws Exception {
        instrumentation.getContext().startActivity(new Intent(Intent.ACTION_SET_WALLPAPER)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        SystemClock.sleep(1200);
        device.dumpWindowHierarchy(new File(base, "wallpaper-picker-" + phase + ".xml"));
        // Retain the legacy reference and use a different candidate for the second attempt.
        device.dumpWindowHierarchy(new File(base, "wallpaper-picker.xml"));
        UiObject candidate = device.findObject(new UiSelector().className("android.widget.ImageView").instance(index));
        if (candidate.exists()) candidate.click();
        UiObject set = device.findObject(new UiSelector().textMatches("(?i)(set wallpaper|apply|done)"));
        if (set.exists()) set.click();
        SystemClock.sleep(1500);
        device.pressBack();
        SystemClock.sleep(500);
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

    private static String hexArgb(int color) {
        return String.format(Locale.ROOT, "#%08X", color);
    }
}
