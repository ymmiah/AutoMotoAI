# AutoMoto AI Developer Studio V25/64 — Flutter and React Native

**Development-only milestone.** Based on the V24-merged cumulative Developer Studio branch. No production rollout, Apple/Google Store release, physical device access or main-branch merge.

## Delivered

- Authenticated, non-executing, bounded Flutter/Dart and React Native source inventory: Flutter `pubspec.yaml`/`pubspec.lock`, widgets and source declarations; RN `package.json`, npm/yarn/pnpm lockfiles, Metro config, JS/TS sources and native Android/iOS bridge hints. Per-file SHA-256 and combined manifest/source digests protect explicitly consented execution against stale source revisions.
- Conservative static checks for unsafe Flutter git/path/hosted dependencies, unusual Metro configs, mixed Flutter/RN roots, missing Dart/JS entry points, invalid manifests, links/junctions and oversized files. Lockfiles are supported up to 4 MiB each, with bounded total project scan and excluding generated caches. The source index is heuristic, **not** a Dart/TypeScript semantic compiler.
- Fingerprints for installed Flutter, Dart, Node, npm, ADB/emulator, Xcrun and language/debug server candidates; inspection never invokes these executables. Separate opt-in commands can query installed Flutter, Dart, Node/npm versions, Flutter Doctor and Flutter device targets; device discovery **does not start a device or launch an app**.
- Trust- and consent-gated fixed commands on a SHA-verified **temporary source copy**: `flutter pub get --offline`; Flutter analyse/test/web build following offline pub resolution; `node --check index.js`; standalone React Native bridge `node --test test/bridge.test.cjs`; and `npm ci --offline --ignore-scripts --no-audit --no-fund` when a package-lock is present. No command templates, arbitrary shell strings, user-selected scripts or `npx` with automatic package resolution are accepted by the desktop Studio.
- Flutter/React Native UI with package metadata, toolchain status and human-approved tasks; links reuse existing separately consented Dart/TypeScript LSP and debugger-adapter facilities. All release review drafts target the **single existing AutoMoto Agent**, without automatically submitting, approving or deploying.
- No new runtime app management authority: the desktop Studio never starts a Metro server, launches Android/iOS simulators, installs an APK/IPA, attaches to physical devices, signs builds or deploys. Future stages need separately reviewed controls and toolchain evidence.

## Real acceptance fixtures and CI

- `tests/fixtures/v25-flutter/`: real minimal Flutter widget with stable on-screen `V25_FLUTTER_WEB_PASS` marker, a Flutter widget test and web bootstrap.
- `tests/fixtures/v25-react-native/`: React Native 0.88.1 / React 19.3.0 app with Metro config, `V25_RN_METRO_PASS` JSX marker and isolated `node --test` bridge unit tests. Version pairing is checked against the [React Native release table](https://reactnative.dev/releases/overview); project `node_modules` is never copied or run by the desktop Studio.
- `tests/test_developer_mobile.py`: inert inspection and source checksums, Flutter widgets/React Native Metro detection, malformed YAML/JSON, git dependency/script review, mixed root denial, linked manifests, stale source and executable hash/consent gates, hosted denial and real Node bridge tests. The dedicated Flutter SDK job also exercises real approved offline Flutter pub/analyse/widget/test/web commands.
- `.github/workflows/developer-mobile-v25.yml`: Windows/macOS/Linux API and security tests; Ubuntu/macOS real Flutter 3.47.9 widget tests, analysis and web compilation; Ubuntu Node 24 React Native 0.88.1/Metro bundle and actual JS tests; isolated Android SDK 35 emulator building/installing/launching a Flutter debug APK and capturing a PNG screenshot. CI package downloads occur **only on isolated GitHub runners**. All claims of passing real hardware, simulators or bundling depend on exact-head green jobs, not the existence of a workflow file.
- `tests/scripts/v25_flutter_android_emulator.sh`: **CI-only** APK install/launch/screenshot against an isolated emulator. It checks actual activity startup and a valid screenshot, **not OCR proof of the exact rendered Flutter text**. This is not exposed to the Studio interface.
- `apps/desktop/test/ui-smoke.cjs`: combined Flutter and React Native source evidence, first-class mixed-project safety warnings, no device query or dependency installation and central Agent review-only.

## Scope limits

**No external process is OS/network sandboxed.** Flutter, Dart, npm, compilers, native dependencies and test scripts can read files outside the temp source copy, access secrets, change host SDK caches or contact network, even when `--offline`/`--no-pub`/`--ignore-scripts` is supplied. Offline resolution controls reduce intended package fetching but do not guarantee network isolation. Commands should run only for fully reviewed trusted projects.

Flutter build tooling and platform support vary by installed OS/SDK. The Studio's explicit `flutter devices --machine` command only reports target availability; it does not establish working drivers or permissions. Windows Flutter executables ending in `.bat`/`.cmd` are intentionally not admitted through the safe executable fingerprint path until a separately reviewed wrapper strategy exists.

React Native installation/Metro bundle is tested in isolated CI, not inside the desktop Studio: the Studio supports static RN bridge inspection, Node-side source/tests and offline npm package operations only. A Metro JS bundle **does not prove** RN Android/iOS native app compilation, Hermes execution, device launch, New Architecture compatibility or debugger readiness. Native RN Android/iOS runtime and Flutter iOS runtime acceptance are future quality gates, not verified by this first V25 implementation.

## Rollback and verification

Commit or back up your workspace before approving any external task. Review trust, lockfiles, dependencies and possible hooks; restore unintended host changes from source control/backup. Reverting V25 development commits preserves V1–V24 and existing workspaces. No Store signing or production publication is authorised.

V25 remains **Review**, not Verified, until exact-head 3-OS static tests, real Flutter widget/web tests, Android emulator acceptance, real RN Metro bundle, main app CI including browser/Windows packaging, independent Dart/TypeScript LSP/debugging, accessibility, software supply-chain and mobile signing review, and explicit human sign-off.

## Official references

- [Flutter CLI](https://docs.flutter.dev/reference/flutter-cli)
- [Flutter web build and test](https://docs.flutter.dev/platform-integration/web/building)
- [Flutter web development setup](https://docs.flutter.dev/platform-integration/web/setup)
- [React Native releases](https://reactnative.dev/releases/overview)
- [React Native Hermes](https://reactnative.dev/docs/hermes)
- [Metro getting started](https://metrobundler.dev/docs/getting-started/)
