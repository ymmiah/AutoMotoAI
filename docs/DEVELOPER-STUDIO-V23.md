# Developer Studio V23/64 — Kotlin/JVM and Android

**Development-only milestone.** V23 is based on the V22-merged aggregate development branch. It does not modify `main`, release an app, publish an APK/AAB, run an emulator automatically, or create a second Agent.

## Functionality implemented

- Authenticated, local-only, **non-executing** inspection of bounded Kotlin/Java and Android XML files, Gradle Kotlin/Groovy DSL build and settings declarations, AndroidManifest.xml, declared Gradle wrapper version, Android Gradle Plugin (AGP) and Kotlin plugin versions.
- Kotlin lexical packages and declarations plus Jetpack Compose import/annotation evidence. This is a static heuristic, **not** an installed Compose compiler, semantic Kotlin language server or a completed Compose app build.
- Read-only Android SDK discovery from validated Android SDK home directories: installed platform names, build tools, ADB and emulator presence. No SDK packages or licences are installed/accepted. Inspection does not connect to a device, call adb, list AVDs, launch an emulator, install an APK or run project code.
- Conservative declared AGP/Gradle version advisory using recognised version pairs. Unknown versions are `not_assessed`, never silently approved. A compatibility advisory is not proof of installed Gradle/Android versions. Gradle wrapper scripts are **never executed**.
- SHA-256 fingerprints of installed Gradle, Java, Kotlin compiler/language server and ADB/emulator candidates. Only an explicitly approved installed Gradle, Java or ADB executable may run a fixed version task.
- Explicitly approved, local-trust-only Gradle tasks for Kotlin/JVM build/test and `:app:assembleDebug`/`:app:testDebugUnitTest` on a supported single-module Android project. Commands use a **bounded temporary source copy**, `--offline`, no Gradle wrapper and a temporary Gradle home. A read-only local Gradle dependency cache may be referenced when present; missing cache results in an ordinary failed build, not a network download initiated by the app. Exact manifest/source/executable/toolset hashes are checked again before execution.
- The panel links to existing language server and DAP controls only. Kotlin LSP availability is explicitly conditional; native Android device debugging is **not** supplied by V23. The same single central AutoMoto Agent receives an optional release-readiness **review-only** draft; no deployment, device installation or publication is authorised automatically.

## Real acceptance suites

- `tests/test_developer_android.py`: inert Kotlin project inspection, Android manifest and AGP/Gradle version checks, Compose heuristics, no false emulator/device actions, malformed XML, links, unsafe Gradle settings, stale project/tool fingerprints, trust and consent checks, hosted denial, Kotlin/JVM build/test, Android debug APK assembly and Android JVM unit tests.
- `tests/fixtures/v23-kotlin`: actual Kotlin 2.2.21/JDK 17 project with arithmetic assertions, Gradle 8.13 and a Kotlin/JUnit Platform test.
- `tests/fixtures/v23-android`: real Android 35, AGP 8.13.2, Kotlin 2.2.21, Gradle 8.13 debug application, Android activity text marker and Android JVM unit test. No Compose runtime dependency is implied by this sample.
- `.github/workflows/developer-android-v23.yml`: installed Gradle/JDK compilation and Kotlin tests on Ubuntu, macOS and Windows; Android SDK 35 debug APK/units on Linux; real headless Android emulator installation/launch and UI marker verification on an isolated GitHub runner. **CI is allowed to download SDK and build dependencies on its isolated runner; the local AutoMoto Studio is not.** The dedicated emulator job uses a third-party GitHub Action and requires independent supply-chain review before production acceptance.
- `tests/scripts/v23_android_emulator.sh`: uses ADB *only* in isolated CI after an explicit emulator job has started; installs, starts and checks the app's `V23_ANDROID_RUNNING` UI marker. No equivalent desktop Studio device action exists.
- `apps/desktop/test/ui-smoke.cjs`: inert Android/Compose metadata, unchanged source and shared Agent review with no device access.

## Security and platform limitations

**Gradle build scripts, compiler plugins and tests are NOT OS/network sandboxed.** They can read secrets, modify files outside the temporary source copy and contact external hosts as the local OS user. Offline Gradle resolves only cached dependencies; it does not provide network isolation for arbitrary build-script code. SHA checks mitigate stale project state but do not prove software is safe or eliminate all races.

Only a bounded, single root Kotlin/JVM project or `:app` Android project is accepted for V23 execution. Complex multi-module builds, Compose binaries, KSP/KAPT, NDK, Kotlin Multiplatform, signed release builds, device farms, Play Store uploads, Android Studio IDE services, and all Kotlin LSP/debugger features require separate implementation and evidence. Windows Gradle `.bat` launchers are intentionally blocked by the backend; Windows CI still verifies a real Kotlin project with a trusted CI Gradle invocation, **not** the Windows AutoMoto backend's ability to run a batch launcher. Emulator availability and hardware acceleration vary by host. CI evidence is valid only once the corresponding exact-head job is green.

## Rollback and release gates

Inspection does not modify project files. Before consenting to any build, commit or back up the workspace because arbitrary external build code can still affect other files. Reverting V23 development commits restores V1–V22, its central Agent bridge and existing user workspaces. No `main` merge or public app deployment is authorised solely by a green build.

To mark V23 Verified, require exact-head 3-OS Kotlin acceptance, SDK/Android build/test and real emulator launch evidence, full existing CI and Windows packaging, real Kotlin LSP/Android debugging/manual device checks, independent accessibility, security, SDK licence and third-party action review, and explicit human release approval.

## Verified official compatibility references

- Kotlin Gradle/Android plugin compatibility: https://kotlinlang.org/docs/gradle-configure-project.html
- AGP/Gradle compatibility: https://developer.android.com/build/releases/about-agp
- JDK requirements for Android builds: https://developer.android.com/build/jdks
- Compose Compiler Gradle plugin: https://developer.android.com/develop/ui/compose/setup-compose-dependencies-and-compiler
- Android emulator test tooling: https://developer.android.com/studio/run/emulator
