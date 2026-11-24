# Developer Studio V43: device and simulator tools

V43 answers four beginner questions honestly:
- Can this computer run an Android emulator or the iPhone Simulator?
- Is my phone, emulator or simulator really connected?
- Is a USB board plugged in?
- Is app signing set up?

It **never starts an emulator or simulator, never opens a serial port, never reads key files, and never says "ready" for something this computer can't do.**

The desktop main screen is unchanged. V43 lives in **Tools → Devices & emulators**, on desktop, tablet and phone.

## What you see

1. **Check this computer.** One card per check, each with a plain status: **Ready**, **Probably ready**, **Not set up**, **Needs setup**, **Needs permission**, **Not possible here**, **Not verified** or **Not checked**. Each card says what to do, with a copyable command when there is one (for example `sudo usermod -aG kvm $USER`) or an official guide link.
   - **Hardware virtualization:**
     - Linux: `/dev/kvm` exists and your user can use it.
     - macOS: Apple silicon, or `sysctl kern.hv_support`.
     - Windows: **not checked**, with the instructions shown instead.
   - **Android Emulator on this computer:**
     - Checks the SDK, the emulator package, virtual devices, and system images that match your processor.
     - **Linux on ARM is "Not possible here"**, because Google doesn't publish the emulator for it.
     - **Windows on ARM is "Not verified"**.
     - It's never Ready while a piece is missing or virtualization is unusable.
   - **iPhone Simulator:**
     - **"Not possible here"** on Windows and Linux.
     - On a Mac it checks that full Xcode is installed and selected, not only the Command Line Tools.
   - **USB boards and serial hardware:** lists Arduino/ESP32/Pico-style ports with their names. It flags the `dialout` permission on Linux. Ports are never opened.
   - **Signing:**
     - Android debug key present. Release signing set up in Gradle, **flagging passwords written into Gradle files without showing them**.
     - Key and certificate files inside the project are flagged and never opened.
     - On a Mac: counts of Apple signing identities and provisioning profiles (names not shown). On Windows: signtool for sideloaded MSIX.
2. **Find devices.** Lists Android phones and emulators (adb) and, on a Mac, iPhone simulators. Everything starts as **Seen, not verified**.
3. **Verify.**
   - **Android:** asks the device for its model, Android version, API level and processor. It also has to echo back a random code, so a stale or fake entry can't pass.
   - **Unauthorized phones:** you're told to tap *Allow USB debugging*.
   - **Offline devices:** you get a copyable `adb kill-server`.
   - **Simulator:** verified only when it's actually booted. Otherwise you get a copyable `xcrun simctl boot … && open -a Simulator`, because AutoMoto doesn't start it.
   - A verification lasts one hour.

## Safety

- Only fixed, read-only commands with absolute paths: `xcrun simctl list devices --json`, `security find-identity -v -p codesigning`, `sysctl -n kern.hv_support`, plus the existing guarded adb runner (`getprop` and `echo` only). The environment is reduced, with a 15 s timeout.
- Device IDs are validated: adb serial pattern, simulator UDID pattern. A device must be listed right now before it can be verified.
- Gradle files over 256 KB and symlinks are skipped. Secret values are never returned. Keystores, `.p12`, `.mobileprovision`, `.p8` and `.pem` files are listed by path only.
- `anything_started: false` is returned on every response.

## API

All routes are under `/api/developer/studio/devices` and need the session token.

| Route | What it does |
| --- | --- |
| `GET /diagnose?project=` | The `project` is optional and enables the project signing checks. Returns host, virtualization, android_emulator, ios_simulator, serial_hardware and signing. |
| `GET /list` | Devices, each with `seen_not_verified` or `verified`. |
| `POST /verify` | `{kind: android or ios_simulator, id}`. Returns `409` for the simulator on a non-Mac. |

## Tests and CI

- `tests/test_developer_devices.py` simulates these hosts:
  - Linux arm64 (unsupported, even with an SDK)
  - Windows arm64 (not verified)
  - Linux without KVM, and with KVM but no permission
  - a ready emulator, and a mismatched system image
  - macOS without Xcode
- It also covers:
  - hidden Gradle passwords in both Kotlin and Groovy syntax
  - keystores
  - serial permissions
  - Android verify: success, wrong echo, unauthorized, offline and refusals
  - simulators: Booted vs Shutdown, refused off a Mac
  - an **unmocked** diagnosis of the real runner
- `.github/workflows/developer-devices-v43.yml` runs on Ubuntu and Windows. It adds **Ubuntu on ARM** and macOS 15 when V43 files change, so the real-host test proves "Not possible here" on Linux ARM and the Mac paths on macOS.
- `apps/desktop/test/developer-studio-e2e.cjs`: the Check and Find devices flows, and the iPhone Simulator showing *Not possible here* off a Mac.

## Limitations

- **No real phone, emulator or simulator is connected in CI.** Android verification is tested with a simulated adb, and simulator verification with simulated `simctl` output.
- Windows virtualization (WHPX/Hyper-V) is not checked.
- "Ready" means the pieces are present, not that a build or launch will succeed.
- Real iPhones are listed through Phone control. V43 doesn't verify them.
- Serial ports: Windows names come from the registry. Linux shows `/dev/serial/by-id` names.
- Apple signing shows counts only, not names or expiry dates.

## Recovery

- Follow each card's **What to do** line, then press **Check this computer** again.
- A device that won't verify: unlock it, accept the USB debugging prompt, or replug it; then press **Find devices** and **Verify** again.
