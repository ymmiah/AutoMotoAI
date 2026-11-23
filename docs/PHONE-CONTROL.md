# Phone control (Android and iPhone)

Developer Studio → Extensions & tools → **Phone control** lets the assistant use an Android phone, an iPhone or the iOS Simulator. It reads the screen as text and can tap, type, scroll, press keys and open apps. Use it to get something done on a phone, or to test your own app.

## Android

Nothing is installed on the phone, and no root is needed.

1. Install [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools) so `adb` is on your PATH. AutoMoto also finds it in `ANDROID_HOME` or `ANDROID_SDK_ROOT`, or you can set `AUTOMOTO_ADB` to its full path. A project `.env` can't change this setting.
2. On the phone, open **Settings → About phone** and tap **Build number** 7 times.
3. Open **Developer options** and turn on **USB debugging**.
4. Plug the phone in, unlock it and tap **Allow** on the USB debugging prompt.

## iPhone and iOS Simulator (for testing your app)

iPhone mode uses [WebDriverAgent](https://github.com/appium/WebDriverAgent), the helper app that iPhone test tools such as Appium use. You start it, and AutoMoto connects to it on this computer at `127.0.0.1:8100`. To use another port, set `AUTOMOTO_WDA_PORT` in your real environment.

**Simulator (easiest, no signing):** on a Mac with Xcode, open `WebDriverAgent.xcodeproj` and run the `WebDriverAgentRunner` scheme on a Simulator (**Product → Test**). Or run:

```sh
xcodebuild -project WebDriverAgent.xcodeproj -scheme WebDriverAgentRunner \
  -destination 'platform=iOS Simulator,name=iPhone 16' test
```

**Real iPhone:**

1. Turn on **Settings → Privacy & Security → Developer Mode**.
2. In Xcode, sign `WebDriverAgentRunner` with your team. A free Apple Account works, but its signing expires after 7 days. A paid developer account lasts longer.
3. Plug the iPhone in and run the scheme with `-destination 'id=<your iPhone UDID>'`.
4. Forward port 8100 to this computer:
   - **Mac or Linux:** `iproxy 8100 8100` (from libimobiledevice).
   - **Windows, Mac or Linux:** `pymobiledevice3 usbmux forward 8100 8100`.

Then press **Refresh** in the panel. The iPhone or Simulator appears in the list.

If you build your app in the **iPhone apps** studio, ask the assistant to test it after it's installed. `phone_apps` lists your app's bundle ID. The assistant opens the app, walks the main screens and reports anything that does nothing, hangs, crashes, has cut-off text or has an unlabelled button. This is quick exploratory testing, not a replacement for your XCTest suite.

## Use it

1. Open the panel, press **Refresh** and pick the phone.
2. Tick the box and press **Turn on phone control**. Control lasts 30 minutes, or until you press **Stop phone control**.
3. Ask in chat, for example "open Settings on my phone and turn on dark mode", or "test my MyShop app on the Simulator".

**Show the screen** displays a screenshot in the panel. It is never sent to the assistant.

## What the assistant can do

| Tool | What it does | Asks first |
| --- | --- | --- |
| `phone_status` | Shows which phones and Simulators are ready and whether control is on | No |
| `phone_screen` | Reads the screen as numbered text elements with tap positions | No |
| `phone_apps` | Lists Android package names, or on iPhone your apps' bundle IDs plus built-in ones | No |
| `phone_tap` | Taps by visible text, by element number or by x and y | Yes |
| `phone_type` | Types into the selected text box | Yes |
| `phone_scroll` | Scrolls up, down, left or right | Yes |
| `phone_key` | Presses back, home, recents, enter, delete or tab (iPhone: home, enter, delete, tab) | Yes |
| `phone_open` | Opens an app by Android package name or iPhone bundle ID | Yes |

## Safety

- **You switch it on.** Control stays off until you press the button. The assistant cannot press it, because requests from the assistant never carry the button's approval header.
- **It switches itself off.** Control covers one device and ends after 30 minutes.
- **It stays on this computer.** Hosted servers expose no phone routes or tools. iPhone mode only ever connects to `127.0.0.1`.
- **Each action asks first.** Taps, typing, scrolling, key presses and app launches are approval-gated. Screen text is fenced as untrusted, so a message on the screen can't tell the assistant what to do. It also turns off auto-approval for the rest of that run.
- **It won't type passwords.** Typing into a password box (Android) or secure text field (iPhone) is refused. On Android, text is quoted for the phone's shell, and adb runs with a fixed argument list and a minimal environment.
- **Every action is logged.** Each one is written to `phone-audit.jsonl` in AutoMoto's data folder. Typed text is recorded only as its length.
- **Stop WebDriverAgent when you've finished.** WebDriverAgent has no password of its own, so while it runs, any program on this computer can control that iPhone or Simulator.

## Limits

- **Unlabelled elements:** icons without a label show as their resource ID (Android) or are left out. Tap these by element number or position instead. On iPhone, giving buttons accessibility labels fixes this and helps VoiceOver users too.
- **Android typing:** plain English letters, numbers and symbols only (no emoji or accents), and a literal `%s` is typed as a space. iPhone typing supports any text.
- **One iPhone at a time:** iPhone mode uses one WebDriverAgent port.
- **Not supported:** multi-touch, the camera, biometrics and the lock-screen PIN. Unlock the device yourself.
