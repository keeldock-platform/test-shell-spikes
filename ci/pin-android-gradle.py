#!/usr/bin/env python3
"""Pin the generated Gradle, AGP and Kotlin toolchain before resolving dependencies."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def pin(project, version):
    lock = json.loads((ROOT / 'ci/environment-lock.json').read_text())['android']
    root_script = project / 'build.gradle.kts'
    source = root_script.read_text()
    source, count = re.subn(r'org.jetbrains.kotlin:kotlin-gradle-plugin:[^"\s)]+',
                            f'org.jetbrains.kotlin:kotlin-gradle-plugin:{version}', source)
    if not count:
        raise ValueError('Generated Kotlin buildscript declaration was not found')
    source, count = re.subn(r'com.android.tools.build:gradle:[^"\s)]+',
                            f"com.android.tools.build:gradle:{lock['androidGradlePlugin']}", source)
    if not count:
        raise ValueError('Generated Android buildscript declaration was not found')
    root_script.write_text(source)
    wrapper = project / 'gradle/wrapper/gradle-wrapper.properties'
    properties, count = re.subn(r'^distributionUrl=.*$',
                                lambda _: f"distributionUrl=https\\://services.gradle.org/distributions/gradle-{lock['gradle']}-bin.zip",
                                wrapper.read_text(), flags=re.M)
    if not count:
        raise ValueError('Generated Gradle distribution URL was not found')
    properties = re.sub(r'^distributionSha256Sum=.*\n?', '', properties, flags=re.M)
    wrapper.write_text(properties.rstrip() + f"\ndistributionSha256Sum={lock['gradleSha256']}\n")
    # Gradle 8.14 uses its published Kotlin DSL graph instead of the unavailable 9.6 graph.
    init = project / 'shell-kotlin.init.gradle'
    init.write_text('''gradle.beforeProject { p ->
    p.buildscript.repositories { google(); mavenCentral(); gradlePluginPortal() }
}
gradle.projectsEvaluated {
    gradle.rootProject.tasks.register("shellDependencyProbe") {
        doLast {
            gradle.rootProject.allprojects { p ->
                p.buildscript.configurations.findByName("classpath")?.resolvedConfiguration?.rethrowFailure()
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
