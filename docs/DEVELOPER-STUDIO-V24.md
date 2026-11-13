# Developer Studio V24/64 — Swift, SwiftUI and iOS

**Development-only milestone.** Based on V23 merged into the cumulative Developer Studio branch. No production rollout, main-branch merge, Apple device signing, TestFlight or App Store upload.

## Shipped implementation

- Authenticated **non-executing** local inspection of bounded `Package.swift`, `Package.resolved`, one `.xcodeproj/project.pbxproj`, a shared `.xcscheme`, Swift/SwiftUI and Objective-C `.m`, `.mm`, `.h` source. Every included file is a no-follow, size-limited read with a SHA-256 manifest/source fingerprint. Path traversal and linked root SwiftPM manifests are denied.
- Static Swift declarations/imports and SwiftUI source hints; Objective-C interfaces, implementations and protocols. No Swift parser, macro expansion, Xcode project evaluation, build script, package manifest, LSP or simulator is invoked during inspection. The information is **heuristic**, not a semantic compilation result.
- SwiftPM declared executable and local target dependencies; reject known external package, binary, plugin, macro and unsafe-flag declarations for the narrow first-version approved build path. A Swift package manifest is executable Swift code, so this filter does **not** attest that it is safe. Any declared dynamic or unusual project feature requires independent review.
- Recognise one simple shared-scheme iOS Xcode project, declared bundle ID and deployment target. Refuse build admission for detected shell script phases, remote Swift packages, provisioning/signing configuration, workspaces and ambiguous multi-project states. Read-only inspection still shows warnings.
- Installed `swift`, `swiftc`, `sourcekit-lsp`, `xcodebuild`, `xcrun` and LLDB candidates are SHA-256 fingerprinted without executing them. Actual compiler and Xcode versions require separately approved `--version`/`-version` tasks, rather than inferred results.
- Consent-gated local-only fixed tasks: Swift/Swift compiler versions, SwiftPM build, SwiftPM XCTest, SwiftPM executable smoke; macOS-only Xcode version, simulator *listing* and unsigned iOS Simulator build. Every request requires trusted project root, fixed task arguments, exact source/project/tool hash checks, user acceptance of unsandboxed-process risk and time/output bounds. Tools operate against a SHA-checked, automatically removed project copy with separate scratch/cache/derived-data directories. SwiftPM requests disable automatic dependency resolution; Xcode simulator builds use `CODE_SIGNING_ALLOWED=NO` and `-disableAutomaticPackageResolution`.
- Existing independently approved SourceKit-LSP and LLDB controls are reused. V24 discovery does not start them or grant new debugger rights. The same **single central AutoMoto Agent** can receive a release-readiness review draft. That draft does not authorise publishing or deployment.
- The desktop app does **not** boot a simulator, install an IPA/app, use `simctl install`/`launch`, attach a device, accept Xcode licence prompts, sign a release, or publish to TestFlight/App Store.

## Real acceptance

- `tests/fixtures/v24-swiftpm/`: dependency-free Swift 5.9-tools-version manifest with a library, executable smoke marker `V24_SWIFTPM_SMOKE_PASS`, and real XCTest arithmetic/marker assertions.
- `tests/fixtures/v24-ios/`: single-target Xcode project, shared `V24iOS` build scheme, SwiftUI `@main` app and visible simulator marker `V24_IOS_SIMULATOR_PASS` with accessibility identifier. No credentials or signing profiles.
- `tests/fixtures/v24-objc/`: Objective-C interface and implementation for static inspection. Does not claim real Objective-C compilation in this version.
- `tests/test_developer_swift.py`: static Swift/Objective-C/Xcode/SwiftUI evidence and no-execution assertions on Windows and Linux; authentication, trust, stale SHA, linked manifests, prohibited SwiftPM packages/plugins and Xcode shell-script gates; real Swift compiler/SwiftPM XCTest/smoke and consent-gated Xcode simulator build when the dedicated macOS SDK is installed.
- `.github/workflows/developer-swift-v24.yml`: macOS real SwiftPM build/test/run, real Xcode project/unsigned simulator build and simulator installation/launch/screenshot evidence, plus Windows/Linux read-only and security tests. No claim of macOS simulator availability without an exact-head green job.
- `tests/scripts/v24_ios_simulator.sh`: **CI-only** simulator boot, installation, launch and screenshot, followed by simulator shutdown. It never runs from the desktop app. A screenshot validates a real frame and the successful CLI launch; it is not a full accessibility audit or automated OCR assertion of the on-screen marker.
- `apps/desktop/test/ui-smoke.cjs`: Swift/SwiftUI/SourceKit-LSP/SwiftPM static discovery, source-preservation and shared Agent review without external actions.

## Scope and security disclosures

Swift source editing and read-only project inspection work on macOS, Linux and Windows through the existing Studio editor. **Xcode and iOS Simulator execution require supported macOS with full Xcode, installed iOS runtime and signing-independent simulator prerequisites.** SwiftPM compilation requires an installed, approved Swift compiler on the host; Windows/Linux do not inherit Apple's Xcode tooling. Device testing and App Store readiness are not established by simulator evidence.

**Running SwiftPM or Xcode is not OS, filesystem or network sandboxed.** Swift Package.swift is evaluated as code during builds. Source files, compiler plugins, build targets, native libraries and tests can read local secrets, write outside the temporary copy and contact the network. Offline resolution controls reduce expected dependency downloads; they cannot stop malicious build scripts or arbitrary code from contacting the network. SHA fingerprinting reduces accidental stale-input execution but does not remove all TOCTOU risks or certify code integrity. Do not run untrusted repositories.

A narrow first-version approved path covers a dependency-free Swift package or one simple iOS Xcode project with a shared scheme and no build scripts, custom signing or remote packages. CocoaPods, Carthage, external Swift packages, xcworkspace graph resolution, Objective-C compilation, Swift macros, complex SPM plug-ins, entitlements, provisioning, physical devices, release signing, UI automation/accessibility certification and app distribution are excluded until separately tested and approved.

## Recovery, testing and admission

Commit or back up the original workspace before consenting to tool execution. If a script/test changes files outside the temporary copy, restore them from normal VCS/backup. Reverting V24 development commits preserves V1–V23, workspace data and the central Agent. Do not merge into `main` or publish an iOS app based solely on CI.

V24 remains **Review**, not Verified, until exact-head dedicated macOS Xcode/SwiftPM and simulator CI, Windows/Linux inspection checks, full core UI/security/Windows packaging regression, independent SourceKit-LSP/LLDB manual operation, signing/supply-chain/accessibility review, and explicit human sign-off.

## Authoritative technical references

- [Swift Package Manager](https://docs.swift.org/main/documentation/packagemanagerdocs/)
- [Swift run command](https://docs.swift.org/latest/documentation/packagemanagerdocs/swiftrun/)
- [Apple Xcode command-line tool reference](https://developer.apple.com/documentation/xcode/xcode-command-line-tool-reference)
- [Apple building and running on simulators/devices](https://developer.apple.com/documentation/xcode/running-your-app-on-simulated-or-physical-devices)
- [Apple Swift package CI package resolution](https://developer.apple.com/documentation/xcode/building-swift-packages-or-apps-that-use-them-in-continuous-integration-workflows)
