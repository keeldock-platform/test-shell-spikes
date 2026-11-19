#!/usr/bin/env python3
"""Pin the generated Gradle, AGP and Kotlin toolchain before resolving dependencies."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def pin(project, version):
    lock = json.loads((ROOT / 'ci/environment-lock.json').read_text())['android']
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
    # Probe the selected classpath, not only the dependency declarations.
    init = project / 'shell-kotlin.init.gradle'
    init.write_text('''gradle.beforeProject { p ->
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
