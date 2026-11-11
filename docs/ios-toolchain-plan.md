# iPhone tools inside Developer Studio

This is the plan for a built-in iPhone toolchain and a no-code path: a person describes an app or hands over a ZIP, and the assistant writes the project, builds it, installs it on their iPhone, and sends it to App Store Connect only after they press the button.

The product name comes from `automoto/brand.py` (`AUTOMOTO_BRAND_NAME` / `AUTOMOTO_BRAND_SHORT`). This document says "the assistant" for that product. "AutoMoto" is a temporary name.

The toolchain is a fork of [xtool](https://github.com/xtool-org/xtool) (MIT, copyright Kabir Oberai and contributors). We keep that notice in `third_party/ios-toolchain/NOTICE`. The combined program stays AGPL-3.0-only, plus the commercial licence. MIT code can sit inside an AGPL program when the MIT notice is kept. We do not ask the upstream project for anything at runtime.

## What the person actually does

They do not see a tool list and they do not see source unless they ask. They either type what the app should do, or they attach a ZIP. The assistant uses the Developer Studio registry. Plain sentences show progress ("Building the iPhone app", "Sending the app to Apple").

Before any of that works, a one-time wizard says, in order:

1. This computer can build for an iPhone, or it cannot, and why.
2. Download **Xcode.xip once from Apple**. We never host Apple's SDK.
3. On the iPhone, turn on Developer Mode and tap Trust for this computer.
4. A paid Apple Developer account is required for the App Store, and to keep a test install from expiring after 7 days.
5. Create an App Store Connect API key once. It is stored in the existing secret file (`~/.automoto/.env` and `~/.automoto/secrets/`), not in the chat, not in `settings.json`, and not in git.
6. There is no iPhone simulator on Windows or Linux. Testing is a real iPhone.
7. Windows runs the tools inside WSL. The Microsoft Store package cannot.

The App Store page (name, description, privacy answers, screenshot checklist) is a draft. Nothing is uploaded until the person ticks the box and presses **Send to Apple** in Developer Studio. The assistant cannot press that button. Approving a normal tool prompt is not enough.

## Architecture

```
assistant prompt
    -> studio registry (automoto/developer_ios_studio_tools.py)
        -> automoto/developer_ios.py  (wizard, files, listing, approval, Apple API)
            -> vendored toolchain binary `automoto-ios`
               third_party/ios-toolchain  (forked sources, not a network dependency)
            -> App Store Connect HTTPS only, after the button
```

The registry already loads every `automoto/*_studio_tools.py` and applies one safety policy. The iPhone actions are a new module of that kind, the same pattern as `developer_studio_tools.py` on main and the language modules on the open Developer Studio branches (a local-only router plus a studio spec, no second plugin system). `tools.py` and `planner.py` are not edited.

High-level actions:

| Action | What the person hears | Approval |
|---|---|---|
| `ios_wizard` | Explaining the iPhone steps | Read only |
| `ios_setup` | Checking the iPhone tools | Asks first. May read a local Xcode.xip. Does not download if the checksum is empty. |
| `ios_device` | Looking for your iPhone | Asks first. Needs the computer the phone is plugged into. |
| `ios_create` | Creating the iPhone app | Asks first. Writes a project from a prompt or a ZIP. The reply names files and does not paste source. |
| `ios_build` | Building the iPhone app | Asks first. |
| `ios_install` | Installing the app on your iPhone | Asks first. |
| `ios_listing` | Writing the App Store page | Asks first. Writes a draft. Does not send it. |
| `ios_publish` | Sending the app to Apple | Asks first, and still refuses until the on-screen button has been pressed for this exact draft. |

Hosted multi-user servers never see these tools (`hosted_ok` is false). Offline mode drops `ios_publish` because it has to reach Apple. Setup, build and install stay available when the Xcode.xip and the support files are already on disk.

Secrets the assistant is allowed to *name*, never to *receive*:

| Variable | What it is |
|---|---|
| `AUTOMOTO_ASC_KEY_ID` | App Store Connect key id |
| `AUTOMOTO_ASC_ISSUER_ID` | Issuer id |
| `AUTOMOTO_ASC_KEY_PATH` | Path to the `.p8` file under `~/.automoto/secrets/` |
| `AUTOMOTO_APPLE_ID` | Apple ID email, optional, for the person's own notes |
| `AUTOMOTO_ANISETTE_URL` | Optional. Defaults to `http://127.0.0.1:6969`. Remote hosts are ignored unless `AUTOMOTO_ANISETTE_ALLOW_REMOTE=1`, and the known third-party anisette hosts are refused even then. |

The private key is never logged, never returned by the API, and never sent anywhere except Apple.

## The forked toolchain

`third_party/ios-toolchain/` is our copy of the sources we need:

- the toolchain itself, pinned commit in `UPSTREAM.json`
- `Vendor/xtool-core`, `Vendor/SwiftyMobileDevice`, `Vendor/swift-rcodesign` as path dependencies, not as GitHub URLs

Changes from the upstream snapshot:

- The command name is `automoto-ios`.
- Swift package dependencies that pointed at the upstream organisation now point at the `Vendor/` directories.
- macOS binary frameworks that the core package used to download are repointed at our own release URL (`ios-device-libs`) with the same checksums. Linux and Windows builds of that package use system libraries and do not download them. Those files are not in this repository. Publishing them is an owner step. This pull request does not publish a release.
- SDK support files (the Linux Darwin LLVM toolset and the Apple-macro helper) are described in `Artifacts.json`. An empty checksum means "not published". The Python launcher refuses to download. The Swift code refuses to download as well and only unpacks a local file the launcher has already checked. We never redistribute Apple's SDK. The person supplies `Xcode.xip`.
- The anisette helper defaults to this computer. It does not know the old default servers.
- Issue links, the AppImage update check, and the container tag that pointed at the upstream organisation now point at this project or are removed.
- A project file may be `automoto-ios.yml`. `xtool.yml` still works so older projects open.

`python -m automoto.ios_toolchain_scan` fails the build if the vendored tree mentions the upstream organisation or the two anisette hosts anywhere except `NOTICE`.

### Upstream sync

`scripts/ios_toolchain_sync.py` and `.github/workflows/ios-toolchain-sync.yml` compare the pinned commits with upstream and can open a pull request. The monthly schedule does nothing unless the repository variable `IOS_TOOLCHAIN_SYNC` is `1`. A manual run still does not open a pull request unless its input says so. Nothing in the workflow merges.

### Support-file builds

`.github/workflows/ios-toolchain-artifacts.yml` is manual only. It checks the lockfile and the callout scan. It does not download those files and it does not create a GitHub Release. Building the LLVM toolset, the macro server, and the device libraries, then attaching them to a release on this repository, is a later owner step. Until the checksums in `Artifacts.json` are filled in, setup tells the person the support files are not published yet.

## How each current deployment behaves

| Deployment | What happens |
|---|---|
| Windows desktop, installer or local engine | The engine looks for WSL. If WSL is there, the toolchain is meant to run inside it. If WSL is missing, the wizard says so and does not pretend to build. |
| Microsoft Store MSIX (`runFullTrust`, identity `ymmiah.AutoMotoAI`) | The desktop shell sets `AUTOMOTO_DESKTOP_PACKAGE=msix` when Windows reports a packaged process. The wizard stops. A Store package cannot host this toolchain or drive WSL for it. The rest of the app is unchanged. Use the engine on a PC with WSL, or a Mac or Linux computer. |
| Web / local server (`automoto serve` on the person's computer) | Same rules as the computer it runs on. The Developer Studio page shows the wizard and the Send button. |
| Hosted multi-user server, including first-admin setup | The iPhone tools are not registered for hosted sessions. The page is local-only, same as the rest of Developer Studio. Signing in, the first admin, and other studios are untouched. |
| Offline / local model | Creating a project, checking a saved Xcode.xip, building and installing do not need the network. Sending to Apple is removed while offline. Support-file downloads are skipped and explained. |
| Mac and Linux (the engine already runs there; the desktop apps are later) | The toolchain is a native `automoto-ios` on that computer. A real iPhone is still required. There is no simulator. |

The Python helper inside the Windows app is still the same engine. This feature does not change the MSIX identity, the updater, or the first-admin flow.

## App Store signing and upload

Distribution signing is a step in front of the upload. The launcher asks `automoto-ios` to sign for the store, passing certificate *paths*, never key material, in the argument list. On a machine without that binary, the step stops with a plain sentence. Tests use a double that marks itself as a double. A double is not accepted as an Apple signature outside the test.

Upload uses the App Store Connect API and an API key the person created:

1. Find the app by bundle id. Apple does not let this API create the first app record. If it is missing, we stop and tell the person to add the app once on the App Store Connect website.
2. Create or reuse the version, and write the approved name, subtitle, description and keywords.
3. `POST /v1/buildUploads`, `POST /v1/buildUploadFiles`, `PUT` the IPA to the operation URLs Apple returned (those hosts must be `apple.com`), `PATCH` the file as uploaded. The API bearer token is not copied onto the file host.
4. Attach the build and `POST /v1/reviewSubmissions`, then `PATCH` `submitted: true`.

Step 4 runs only for the draft the person just approved. Editing the draft deletes the approval. Tests check this sequence against a fake Apple. A real key, a real IPA and a real review still have to be tried on hardware we do not have here.

## Apple limits we will not hide

- We do not ship Xcode, the iOS SDK, or a simulator.
- Developer Mode and Trust are on the iPhone, in Settings. We cannot flip them remotely.
- Free Apple IDs make a development install expire after 7 days. The App Store needs the paid program.
- The first App Store record for a new bundle id is created by the person on Apple's website.
- Apple reviews the app. We cannot promise acceptance. The screenshot checklist is a reminder, not a picture we invent.
- Privacy answers are whatever the person typed. We do not guess "we collect nothing" and send that.
- Windows cannot talk to the phone except through WSL and a working USB passthrough. That is a real setup, and it can fail. The message says so.

## Risks

| Risk | What we do |
|---|---|
| The fork phones upstream | The scan test, path dependencies, empty checksums, and a localhost anisette default. |
| A model uploads without the person noticing | `ios_publish` is approval-gated by the registry, and the Apple call also requires the panel button for that listing hash. Agent-internal calls cannot set the button header. |
| Secrets in logs or `settings.json` | Settings already reject secret-like keys. The iPhone routes accept a path, store it in the existing `.env`, and never echo the `.p8`. |
| AGPL plus MIT plus device-library binaries | MIT text is in `NOTICE`. The device-library zips are LGPL-family native libraries and are **not** in this tree. Rebuilding and shipping them needs a licence check by the owner before a release. `swift-rcodesign`'s snapshot has no licence file. That is an open decision. |
| Checksums of the old macOS device libraries | They identify bytes. Runtime fetches, once the owner publishes, go to this repository's releases, not upstream. Rebuilding will change the checksums. Do not publish until the owner wants a release. |
| This environment cannot run Apple's tools | Contract tests and fakes. The pull request states what was not run on a Mac, an iPhone, or a paid account. |
| Windows CI (CRLF, scrubbed environment, generators) | Vendored text is `eol=lf`. Tests do not hash mixed newlines, do not need `SWIFT` or `PATH` entries, and do not run CMake. |

## Phases

1. This plan.
2. Vendor the fork, MIT notice, callout removal, scan test.
3. Registry module, wizard, and deployment messages, with Linux tests.
4. Create, build, install, listing, distribution-sign command, and approval-gated upload, with a fake Apple.
5. Disabled upstream sync, manual artifact check, guides, and the Store-package signal from the Windows shell.

All of those land on one branch and one pull request. Later work, not in this pull request: actually building `automoto-ios` on a Swift 6.2 machine, filling `Artifacts.json` after the owner builds the support files, and a trial on a real iPhone and a paid account.
