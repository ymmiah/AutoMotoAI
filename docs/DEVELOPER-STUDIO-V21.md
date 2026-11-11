# AutoMoto AI — Developer Studio V21/64: Java and JVM Engineering

Status: development pull request based on the V20-merged aggregate development branch. This is not a main-branch or production release.

## Implemented

- Authenticated **local-only, non-executing** inspection of Maven pom.xml and Gradle build.gradle/build.gradle.kts, settings.gradle/settings.gradle.kts, wrapper version declarations, bounded Java/Kotlin files and safe project metadata. Nested and hidden configuration files are not silently trusted.
- Maven pom.xml parsed with defusedxml (external entities refused). Extracts the declared artifact, Java release and bounded dependency coordinates. Framework evidence is clearly labelled heuristic: JUnit 4/Jupiter, Spring/Spring Boot and Kotlin source/framework imports; no assertion of installed frameworks or their vulnerability status.
- Gradle Java toolchain/sourceCompatibility and declared distribution version detection (without fetching or executing gradlew). Comparison against the official Gradle runtime compatibility matrix: Java 17 minimum Gradle 7.3, Java 21 minimum Gradle 8.5, Java 25 minimum Gradle 9.1.0. This comparison is an advisory based on declarations, **not verification of installed JDKs**. Other combinations report not_assessed.
- Bounded, SHA-256 pinned installed java/javac/mvn/gradle tool discovery and optional jdtls evidence. Shell wrappers (.cmd/.bat/.ps1) are not silently executed; unsupported platforms expose a documented unavailable/blocked status.
- Explicitly consented fixed tasks: Java/Javac versions, JDK compilation, one discovered in-project main-based Java smoke test, offline Maven test, offline Gradle build/test and Maven/Gradle version checks. Every execution requires trusted local workspace, new human consent, exact manifest/source/toolchain/executable fingerprints, bounded output, process timeout and a per-Studio execution lock.
- Compiles and tests only a **bounded temporary source copy**, rather than running Maven/Gradle in the original folder. The source copy and build artefacts are deleted after the task. This reduces accidental changes to the original source but is **not an OS, network or filesystem sandbox**: build plugins, Java tests and annotation processors still have the current user's permissions.
- Maven uses --offline and --batch-mode; Gradle uses --offline, --no-daemon and temporary Gradle project/user-home caches. If required dependencies are not already cached locally, runs may fail clearly rather than fetching unapproved dependencies. The application never downloads new tools, invokes mvnw/gradlew wrappers, or installs packages.
- Java LSP navigation is delegated to the existing separately authorised Language Server controls when an approved jdtls instance is available. No new language-server process, native debugger, or independent Studio agent is started. The *same central AutoMoto Agent* only pre-fills a deployment-readiness review requiring a separate user action.

## Real acceptance tests

- tests/test_developer_jvm.py verifies unexecuted source/manifest inventory, JDK 21/25 javac compilation, a real example Java smoke runner, deliberate compiler syntax error, SHA and trust/consent enforcement, malformed or unsafe Maven XML, Gradle/JDK wrapper advisory, offline Maven JUnit 5 tests, Gradle Java build/test and unchanged original files.
- Real Maven JUnit 5 fixture in tests/fixtures/v21-junit with fixed compiler and test-plugin versions and an assertion-based JUnit service test.
- Real Gradle Java fixture in tests/fixtures/v21-gradle using only Gradle's built-in Java plugin for a zero-external-dependency build/test baseline.
- .github/workflows/developer-jvm-v21.yml runs installed JDK 21 on Windows/macOS/Ubuntu and JDK 25 on Ubuntu. It prewarms Maven/JUnit test dependencies **in isolated GitHub CI infrastructure**, prior to running AutoMoto's *offline* Maven acceptance test. It installs Gradle 9.2.1 only in CI, never in users' projects.
- apps/desktop/test/ui-smoke.cjs verifies inert Maven/Java/JUnit/Spring discovery and centrally linked Agent review. Existing platform, Office, security, Docker, docs, Windows app, and prior Go/Rust/C++ acceptance checks remain mandatory.

## Limitations and security boundaries

- Java compilers, annotation processors, Maven/Gradle build scripts, JUnit tests and dependency code may execute arbitrary OS-user code. They can access the network, read secrets and write outside the temporary copy. This implementation does not provide runtime sandboxing, system-level egress filtering or rollback.
- Some complex Maven multi-module, external Gradle plugin, Kotlin compiler, generated-source, module-path, Spring Boot runtime and cached-dependency workflows require additional acceptance. V21 scans Kotlin files but does **not** claim to compile every Kotlin project. Gradle and Maven may require dependencies not cached and will correctly fail offline.
- Gradle wrapper detection does not mean the wrapper was run; Gradle 9.2.1 CI compatibility is not proof of compatibility with other versions. Maven on Windows often resolves to a .cmd launcher; intentionally blocked instead of interpreting an arbitrary shell wrapper.
- The JVM scanner does not validate binary compatibility, transitive dependency security, TLS, JDK provenance, Maven/plugin supply chain, or Spring Boot deployment security. Framework hints are evidence, not installation or coverage guarantees.
- The temporary copy includes only approved bounded source files and recognised manifest paths; complex resource directories, code generation and subprojects may require additional implementation. Do not claim all Maven/Gradle projects work from this subset.
- The app never creates a new agent, silently approves execution, publishes or deploys to production.

## Recovery and release gates

Inspection does not modify project files. Back up or commit trusted sources before consenting to external tools: even when the project is staged, unsandboxed tools may write elsewhere. Recover from version control or a separate backup. Revert V21 development-only commits to restore the V1–V20 baseline and preserve existing workspace state and the central Agent.

Before V21 can be called Verified, require exact-head GitHub CI (including real JDK 21/25/JUnit/Gradle acceptance), human Java LSP/IDE navigation and JUnit/Spring quality checks, independent vulnerability/dependency review, accessibility and release approval. Successful CI alone does not authorise release into main or production.

## Official references

- Java platform documentation: https://docs.oracle.com/en/java/javase/25/
- Maven command-line reference: https://maven.apache.org/ref/current/maven-embedder/cli.html
- Gradle Java compatibility: https://docs.gradle.org/current/userguide/compatibility.html
- Gradle offline and CLI options: https://docs.gradle.org/current/userguide/gradle_command_line.html
- JUnit 5 User Guide: https://junit.org/junit5/docs/current/user-guide/
