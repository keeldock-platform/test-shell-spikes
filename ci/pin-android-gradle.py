#!/usr/bin/env python3
"""Pin the generated Gradle, AGP and Kotlin toolchain before resolving dependencies."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def pin(project, version):
    lock = json.loads((ROOT / 'ci/environment-lock.json').read_text())['android']
    # CLI templates no longer supply this AGP 8 prerequisite. Preserve every
    # other generated property (including cache and release settings).
    gradle_properties = project / 'gradle.properties'
    source = gradle_properties.read_text() if gradle_properties.exists() else ''
    source = re.sub(r'^\s*android\.useAndroidX\s*=.*\n?', '', source, flags=re.M)
    gradle_properties.write_text(source.rstrip() + '\nandroid.useAndroidX=true\n')
    # buildSrc contributes its implementation dependencies to the Rust plugin classpath.
    # Pin both graphs: Gradle otherwise selects buildSrc's newer AGP over the root pin.
    for script in (project / 'build.gradle.kts', project / 'buildSrc/build.gradle.kts'):
        if not script.is_file():
            raise ValueError(f'Generated Android buildscript was not found: {script}')
        source = script.read_text()
        source, agp_count = re.subn(r'com.android.tools.build:gradle:[^"\s)]+',
                                   f"com.android.tools.build:gradle:{lock['androidGradlePlugin']}", source)
        source, kotlin_count = re.subn(r'org.jetbrains.kotlin:kotlin-gradle-plugin:[^"\s)]+',
                                      f'org.jetbrains.kotlin:kotlin-gradle-plugin:{version}', source)
        if not agp_count or (script.parent.name != 'buildSrc' and not kotlin_count):
            raise ValueError(f'Generated toolchain declaration was not found: {script}')
        script.write_text(source)
        print(f'Pinned Android buildscript: {script} AGP={lock["androidGradlePlugin"]} Kotlin={version}')
    wrapper = project / 'gradle/wrapper/gradle-wrapper.properties'
    properties, count = re.subn(r'^distributionUrl=.*$',
                                lambda _: f"distributionUrl=https\\://services.gradle.org/distributions/gradle-{lock['gradle']}-bin.zip",
                                wrapper.read_text(), flags=re.M)
    if not count:
        raise ValueError('Generated Gradle distribution URL was not found')
    properties = re.sub(r'^distributionSha256Sum=.*\n?', '', properties, flags=re.M)
    wrapper.write_text(properties.rstrip() + f"\ndistributionSha256Sum={lock['gradleSha256']}\n")
    app = project / 'app/build.gradle.kts'
    # CLI 2.12.5 emits AGP 9's optimisation DSL. AGP 8 uses the build type's
    # isMinifyEnabled property; preserve release shrinking and the ProGuard rules.
    if app.is_file():
        source, count = re.subn(r'optimization\s*\{\s*enable\s*=\s*true\s*\}',
                                'isMinifyEnabled = true', app.read_text())
        if re.search(r'optimization\s*\{', source):
            raise ValueError('Unrecognised generated Android optimisation DSL')
        app.write_text(source)
        print(f'Android AGP8 optimisation adaptation: {app} blocks={count}')
    # Probe the selected classpath, not only the dependency declarations.
    init = project / 'shell-kotlin.init.gradle'
    init.write_text('''if (System.getenv("SHELL_ANDROID_REFRESH_DEPENDENCIES") == "1") {
    gradle.startParameter.refreshDependencies = true
}
gradle.beforeProject { p ->
    p.buildscript.repositories { google(); mavenCentral(); gradlePluginPortal() }
}
gradle.projectsEvaluated {
    gradle.rootProject.tasks.register("shellDependencyProbe") {
        doLast {
            gradle.rootProject.allprojects { p ->
                def cp = p.buildscript.configurations.findByName("classpath")
                cp?.resolvedConfiguration?.rethrowFailure()
                cp?.resolvedConfiguration?.resolvedArtifacts?.each { a ->
                    println("Resolved classpath: " + p.path + " " + a.moduleVersion.id)
                }
                println("Resolved buildscript: " + p.path)
            }
        }
    }
}
''')
    return init


if __name__ == '__main__':
    lock = json.loads((ROOT / 'ci/environment-lock.json').read_text())
    print(pin(Path(sys.argv[1]), lock['android']['kotlinGradlePlugin']))
