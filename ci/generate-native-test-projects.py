#!/usr/bin/env python3
"""Generate unsigned XCTest UI targets for the shared native test sources."""

from __future__ import annotations

import hashlib
import os
import plistlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "ShellSpikeNativeTests"


def project_for(platform: str, suite: str) -> Path:
    if platform not in {"macos", "ios"} or suite not in {"s01", "s10", "s11"}:
        raise ValueError("platform must be macos|ios and suite must be s01|s10|s11")
    if (platform, suite) not in {("macos", "s01"), ("ios", "s10"), ("ios", "s11")}:
        raise ValueError("the requested native test suite is not available on this platform")
    test_target_name, source = {
        "s01": ("TrafficLightsUITests", "automation/macos/s01/TrafficLightsUITests.swift"),
        "s10": ("ColourUITests", "automation/ios/s10/ColourUITests.swift"),
        "s11": ("AccentUITests", "automation/ios/s11/AccentUITests.swift"),
    }[suite]
    sources = [source]
    project_name = f"{PROJECT_NAME}-{suite}"
    directory = ROOT / "target" / "native-tests" / platform / suite
    project = directory / f"{project_name}.xcodeproj"
    project.mkdir(parents=True, exist_ok=True)

    def oid(name: str) -> str:
        return hashlib.sha1(f"shell-spikes:{platform}:{name}".encode()).hexdigest()[:24].upper()

    def quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'

    def array(values: list[str]) -> str:
        return "( " + ", ".join(values) + ", )"

    bundle_path = Path(os.environ["SHELL_APP_PATH"])
    plist_path = bundle_path / ("Contents/Info.plist" if platform == "macos" else "Info.plist")
    with plist_path.open("rb") as stream:
        bundle_id = plistlib.load(stream)["CFBundleIdentifier"]
    if not isinstance(bundle_id, str) or not bundle_id:
        raise ValueError("Built bundle has no CFBundleIdentifier")
    if platform == "macos" and os.environ.get("S01_APP_BUNDLE_ID", bundle_id) != bundle_id:
        raise ValueError("S01_APP_BUNDLE_ID disagrees with the built bundle")

    app_target = oid("app-target")
    test_target = oid(f"test-target-{test_target_name}")
    app_product = oid("app-product")
    test_product = oid("test-product")
    root_group = oid("root-group")
    source_group = oid("source-group")
    product_group = oid("product-group")
    project_object = oid("project")
    app_phase = oid("app-copy-phase")
    test_sources_phase = oid("test-sources-phase")
    test_framework_phase = oid("test-framework-phase")
    test_resources_phase = oid("test-resources-phase")
    proxy = oid("app-proxy")
    dependency = oid("app-dependency")
    framework_ref = oid("xctest-framework")
    framework_build = oid("xctest-framework-build")

    objects: list[str] = []

    def add(identifier: str, name: str, body: str) -> None:
        objects.append(f"\t\t{identifier} /* {name} */ = {{\n{body}\n\t\t}};")

    def config(identifier: str, name: str, settings: dict[str, str]) -> None:
        values = "\n".join(f"\t\t\t\t{key} = {value};" for key, value in settings.items())
        add(identifier, name, f"\t\t\tisa = XCBuildConfiguration;\n\t\t\tbuildSettings = {{\n{values}\n\t\t\t}};\n\t\t\tname = {name};")

    source_refs: list[str] = []
    source_builds: list[str] = []
    for index, source in enumerate(sources):
        file_ref = oid(f"source-ref-{index}")
        build_ref = oid(f"source-build-{index}")
        source_refs.append(file_ref)
        source_builds.append(build_ref)
        add(file_ref, Path(source).name, f"\t\t\tisa = PBXFileReference;\n\t\t\tlastKnownFileType = sourcecode.swift;\n\t\t\tpath = {quote('../../../../' + source)};\n\t\t\tsourceTree = \"<group>\";")
        add(build_ref, Path(source).name, f"\t\t\tisa = PBXBuildFile;\n\t\t\tfileRef = {file_ref} /* {Path(source).name} */;")

    xctest_platform = "MacOSX" if platform == "macos" else "iPhoneSimulator"
    xctest_frameworks = f"$(DEVELOPER_DIR)/Platforms/{xctest_platform}.platform/Developer/Library/Frameworks"
    add(framework_ref, "XCTest.framework", f"\t\t\tisa = PBXFileReference;\n\t\t\tlastKnownFileType = wrapper.framework;\n\t\t\tname = XCTest.framework;\n\t\t\tpath = {quote('Platforms/' + xctest_platform + '.platform/Developer/Library/Frameworks/XCTest.framework')};\n\t\t\tsourceTree = DEVELOPER_DIR;")
    add(framework_build, "XCTest.framework in Frameworks", f"\t\t\tisa = PBXBuildFile;\n\t\t\tfileRef = {framework_ref} /* XCTest.framework */;")
    app_name = "Test Shell" if platform == "macos" else "Test Shell Mobile"
    app_bundle = f"{app_name}.app"
    test_bundle = f"{test_target_name}.xctest"
    add(app_product, app_bundle, f"\t\t\tisa = PBXFileReference;\n\t\t\texplicitFileType = wrapper.application;\n\t\t\tincludeInIndex = 0;\n\t\t\tpath = {quote(app_bundle)};\n\t\t\tsourceTree = BUILT_PRODUCTS_DIR;")
    add(test_product, test_bundle, f"\t\t\tisa = PBXFileReference;\n\t\t\texplicitFileType = wrapper.cfbundle;\n\t\t\tincludeInIndex = 0;\n\t\t\tpath = {quote(test_bundle)};\n\t\t\tsourceTree = BUILT_PRODUCTS_DIR;")
    add(source_group, "Native UI test sources", f"\t\t\tisa = PBXGroup;\n\t\t\tchildren = {array(source_refs)};\n\t\t\tname = Sources;\n\t\t\tsourceTree = \"<group>\";")
    add(product_group, "Products", f"\t\t\tisa = PBXGroup;\n\t\t\tchildren = {array([app_product, test_product])};\n\t\t\tname = Products;\n\t\t\tsourceTree = \"<group>\";")
    add(root_group, "Main Group", f"\t\t\tisa = PBXGroup;\n\t\t\tchildren = {array([source_group, product_group])};\n\t\t\tsourceTree = \"<group>\";")

    plist_relative = "Contents/Info.plist" if platform == "macos" else "Info.plist"
    script = "set -eu\n" + f'''
if [ -z "$SHELL_APP_PATH" ]; then exit 78; fi
actual_id=$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$SHELL_APP_PATH/{plist_relative}")
[ "$actual_id" = "{bundle_id}" ] || exit 78
mkdir -p "$TARGET_BUILD_DIR"
/usr/bin/ditto "$SHELL_APP_PATH" "$TARGET_BUILD_DIR/$FULL_PRODUCT_NAME"
'''
    # Xcode owns the app directory. Declare only the copied plist so validation
    # waits for the copy without competing with Xcode's MkDir task.
    add(app_phase, "Copy prebuilt Tauri app bundle", f"\t\t\tisa = PBXShellScriptBuildPhase;\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = ( );\n\t\t\tinputPaths = ( );\n\t\t\tname = \"Copy prebuilt test shell\";\n\t\t\talwaysOutOfDate = 1;\n\t\t\toutputPaths = ( \"$(TARGET_BUILD_DIR)/$(INFOPLIST_PATH)\", );\n\t\t\trunOnlyForDeploymentPostprocessing = 0;\n\t\t\tshellPath = /bin/sh;\n\t\t\tshellScript = {quote(script)};")
    add(test_sources_phase, "Sources", f"\t\t\tisa = PBXSourcesBuildPhase;\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = {array(source_builds)};\n\t\t\trunOnlyForDeploymentPostprocessing = 0;")
    add(test_framework_phase, "Frameworks", f"\t\t\tisa = PBXFrameworksBuildPhase;\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = ( {framework_build} /* XCTest.framework in Frameworks */, );\n\t\t\trunOnlyForDeploymentPostprocessing = 0;")
    add(test_resources_phase, "Resources", "\t\t\tisa = PBXResourcesBuildPhase;\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = ( );\n\t\t\trunOnlyForDeploymentPostprocessing = 0;")
    add(proxy, "PBXContainerItemProxy", f"\t\t\tisa = PBXContainerItemProxy;\n\t\t\tcontainerPortal = {project_object} /* Project object */;\n\t\t\tproxyType = 1;\n\t\t\tremoteGlobalIDString = {app_target};\n\t\t\tremoteInfo = ShellSpikeNativeHost;")
    add(dependency, "PBXTargetDependency", f"\t\t\tisa = PBXTargetDependency;\n\t\t\ttarget = {app_target} /* ShellSpikeNativeHost */;\n\t\t\ttargetProxy = {proxy} /* PBXContainerItemProxy */;")

    app_config_ids = [oid("app-debug"), oid("app-release")]
    test_config_ids = [oid("test-debug"), oid("test-release")]
    project_config_ids = [oid("project-debug"), oid("project-release")]
    app_settings = {
        "CODE_SIGNING_ALLOWED": "NO", "GENERATE_INFOPLIST_FILE": "NO",
        "ENABLE_USER_SCRIPT_SANDBOXING": "NO",
        "PRODUCT_BUNDLE_IDENTIFIER": quote(bundle_id),
        "PRODUCT_NAME": quote(app_name), "SKIP_INSTALL": "NO",
        "SUPPORTED_PLATFORMS": quote("macosx" if platform == "macos" else "iphoneos iphonesimulator"),
        "WRAPPER_EXTENSION": "app",
    }
    if platform == "macos":
        app_settings.update({"MACOSX_DEPLOYMENT_TARGET": "13.0", "SDKROOT": "macosx"})
    else:
        app_settings.update({"IPHONEOS_DEPLOYMENT_TARGET": "16.0", "SDKROOT": "iphoneos", "TARGETED_DEVICE_FAMILY": quote("1,2")})
    test_settings = {
        "CODE_SIGNING_ALLOWED": "NO", "GENERATE_INFOPLIST_FILE": "YES",
        "PRODUCT_BUNDLE_IDENTIFIER": quote(f"org.example.shellspikes.tests.{suite}"),
        "PRODUCT_NAME": quote("$(TARGET_NAME)"), "SWIFT_VERSION": "5.0",
        "TEST_TARGET_NAME": "ShellSpikeNativeHost", "TARGETED_DEVICE_FAMILY": quote("1,2"),
        "FRAMEWORK_SEARCH_PATHS": quote(f"$(inherited) {xctest_frameworks}"),
    }
    if platform == "macos":
        test_settings.update({"MACOSX_DEPLOYMENT_TARGET": "13.0", "SDKROOT": "macosx", "SUPPORTED_PLATFORMS": quote("macosx")})
    else:
        test_settings.update({"IPHONEOS_DEPLOYMENT_TARGET": "16.0", "SDKROOT": "iphoneos", "SUPPORTED_PLATFORMS": quote("iphoneos iphonesimulator")})
    for identifier, name in zip(app_config_ids, ("Debug", "Release")):
        config(identifier, name, app_settings)
    for identifier, name in zip(test_config_ids, ("Debug", "Release")):
        config(identifier, name, test_settings)
    for identifier, name in zip(project_config_ids, ("Debug", "Release")):
        config(identifier, name, {"CLANG_ENABLE_MODULES": "YES", "SWIFT_VERSION": "5.0"})

    app_config_list = oid("app-config-list")
    test_config_list = oid("test-config-list")
    project_config_list = oid("project-config-list")
    add(app_config_list, "Build configuration list for app", f"\t\t\tisa = XCConfigurationList;\n\t\t\tbuildConfigurations = {array(app_config_ids)};\n\t\t\tdefaultConfigurationIsVisible = 0;\n\t\t\tdefaultConfigurationName = Release;")
    add(test_config_list, "Build configuration list for tests", f"\t\t\tisa = XCConfigurationList;\n\t\t\tbuildConfigurations = {array(test_config_ids)};\n\t\t\tdefaultConfigurationIsVisible = 0;\n\t\t\tdefaultConfigurationName = Release;")
    add(project_config_list, "Build configuration list for project", f"\t\t\tisa = XCConfigurationList;\n\t\t\tbuildConfigurations = {array(project_config_ids)};\n\t\t\tdefaultConfigurationIsVisible = 0;\n\t\t\tdefaultConfigurationName = Release;")
    add(app_target, "ShellSpikeNativeHost", f"\t\t\tisa = PBXNativeTarget;\n\t\t\tbuildConfigurationList = {app_config_list};\n\t\t\tbuildPhases = ( {app_phase} /* Copy prebuilt app */, );\n\t\t\tbuildRules = ( );\n\t\t\tdependencies = ( );\n\t\t\tname = ShellSpikeNativeHost;\n\t\t\tproductName = {quote(app_name)};\n\t\t\tproductReference = {app_product};\n\t\t\tproductType = \"com.apple.product-type.application\";")
    add(test_target, test_target_name, f"\t\t\tisa = PBXNativeTarget;\n\t\t\tbuildConfigurationList = {test_config_list};\n\t\t\tbuildPhases = ( {test_sources_phase}, {test_framework_phase}, {test_resources_phase}, );\n\t\t\tbuildRules = ( );\n\t\t\tdependencies = ( {dependency} /* ShellSpikeNativeHost */, );\n\t\t\tname = {test_target_name};\n\t\t\tproductName = {test_target_name};\n\t\t\tproductReference = {test_product};\n\t\t\tproductType = \"com.apple.product-type.bundle.ui-testing\";")
    add(project_object, "Project object", f"\t\t\tisa = PBXProject;\n\t\t\tattributes = {{\n\t\t\t\tBuildIndependentTargetsInParallel = NO;\n\t\t\t\tLastUpgradeCheck = 1600;\n\t\t\t\tTargetAttributes = {{\n\t\t\t\t\t{app_target} = {{ CreatedOnToolsVersion = 16.0; }};\n\t\t\t\t\t{test_target} = {{ CreatedOnToolsVersion = 16.0; TestTargetID = {app_target}; }};\n\t\t\t\t}};\n\t\t\t}};\n\t\t\tbuildConfigurationList = {project_config_list};\n\t\t\tcompatibilityVersion = \"Xcode 14.0\";\n\t\t\tdevelopmentRegion = en;\n\t\t\tmainGroup = {root_group};\n\t\t\tproductRefGroup = {product_group};\n\t\t\tprojectDirPath = \"\";\n\t\t\tprojectRoot = \"\";\n\t\t\ttargets = {array([app_target, test_target])};")

    pbx = "// !$*UTF8*$!\n{\n\tarchiveVersion = 1;\n\tclasses = {};\n\tobjectVersion = 56;\n\tobjects = {\n" + "\n".join(objects) + "\n\t};\n\trootObject = " + project_object + " /* Project object */;\n}\n"
    (project / "project.pbxproj").write_text(pbx, encoding="utf-8")
    scheme_dir = project / "xcshareddata" / "xcschemes"
    scheme_dir.mkdir(parents=True, exist_ok=True)
    scheme = f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1600" version="1.7">
  <BuildAction parallelizable="NO" buildImplicitDependencies="YES">
    <BuildActionEntries>
      <BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="NO" buildForArchiving="NO" buildForAnalyzing="YES">
        <BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{app_target}" BuildableName="{app_bundle}" BlueprintName="ShellSpikeNativeHost" ReferencedContainer="container:{project_name}.xcodeproj"/>
      </BuildActionEntry>
      <BuildActionEntry buildForTesting="YES" buildForRunning="NO" buildForProfiling="NO" buildForArchiving="NO" buildForAnalyzing="YES">
        <BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{test_target}" BuildableName="{test_bundle}" BlueprintName="{test_target_name}" ReferencedContainer="container:{project_name}.xcodeproj"/>
      </BuildActionEntry>
    </BuildActionEntries>
  </BuildAction>
  <TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="NO">
    <EnvironmentVariables>
      <EnvironmentVariable key="SHELL_SPIKE_ID" value="$(SHELL_SPIKE_ID)" isEnabled="YES"/>
      <EnvironmentVariable key="SHELL_CASE_ID" value="$(SHELL_CASE_ID)" isEnabled="YES"/>
      <EnvironmentVariable key="SHELL_EVIDENCE_DIR" value="$(SHELL_EVIDENCE_DIR)" isEnabled="YES"/>
      <EnvironmentVariable key="SHELL_MOBILE_EVIDENCE_SUBPATH" value="$(SHELL_MOBILE_EVIDENCE_SUBPATH)" isEnabled="YES"/>
      <EnvironmentVariable key="SHELL_MOBILE_BUNDLE_ID" value="$(SHELL_MOBILE_BUNDLE_ID)" isEnabled="YES"/>
      <EnvironmentVariable key="SHELL_IOS_XCRESULT_PATH" value="$(SHELL_IOS_XCRESULT_PATH)" isEnabled="YES"/>
      <EnvironmentVariable key="S01_APP_BUNDLE_ID" value="$(S01_APP_BUNDLE_ID)" isEnabled="YES"/>
      <EnvironmentVariable key="S01_ARTIFACT_DIR" value="$(S01_ARTIFACT_DIR)" isEnabled="YES"/>
      <EnvironmentVariable key="S01_PERMISSION_PROMPT_PREFLIGHT" value="$(S01_PERMISSION_PROMPT_PREFLIGHT)" isEnabled="YES"/>
    </EnvironmentVariables>
    <Testables><TestableReference skipped="NO" parallelizable="NO"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{test_target}" BuildableName="{test_bundle}" BlueprintName="{test_target_name}" ReferencedContainer="container:{project_name}.xcodeproj"/></TestableReference></Testables>
  </TestAction>
  <LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" enableGPUFrameCaptureMode="0" allowLocationSimulation="YES">
    <BuildableProductRunnable runnableDebuggingMode="0"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{app_target}" BuildableName="{app_bundle}" BlueprintName="ShellSpikeNativeHost" ReferencedContainer="container:{project_name}.xcodeproj"/></BuildableProductRunnable>
  </LaunchAction>
  <ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="NO" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{app_target}" BuildableName="{app_bundle}" BlueprintName="ShellSpikeNativeHost" ReferencedContainer="container:{project_name}.xcodeproj"/></BuildableProductRunnable></ProfileAction>
  <AnalyzeAction buildConfiguration="Debug"/>
  <ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
'''
    (scheme_dir / f"{project_name}.xcscheme").write_text(scheme, encoding="utf-8")
    return project


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: generate-native-test-projects.py macos|ios s01|s10|s11")
    print(project_for(sys.argv[1], sys.argv[2]))
