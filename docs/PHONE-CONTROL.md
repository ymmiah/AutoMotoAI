# Android phone control

Developer Studio → Extensions & tools → **Android phone control** lets the assistant use an Android phone plugged into this computer. It reads the screen as text and can tap, type, scroll, press Back, Home and Recents, and open apps. Nothing is installed on the phone, and no root is needed.

## Set up (once)

1. Install [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools) so `adb` is on your PATH. AutoMoto also finds it in `ANDROID_HOME` or `ANDROID_SDK_ROOT`, or you can set `AUTOMOTO_ADB` to its full path. A project `.env` can't change this setting.
2. On the phone, open **Settings → About phone** and tap **Build number** 7 times.
3. Open **Developer options** and turn on **USB debugging**.
4. Plug the phone in, unlock it and tap **Allow** on the USB debugging prompt.

## Use it

1. Open the panel, press **Refresh** and pick the phone.
2. Tick the box and press **Turn on phone control**. Control lasts 30 minutes, or until you press **Stop phone control**.
3. Ask in chat, for example "open Settings on my phone and turn on dark mode".

**Show the screen** displays a screenshot in the panel. It is never sent to the assistant.

## What the assistant can do

| Tool | What it does | Asks first |
| --- | --- | --- |
| `phone_status` | Shows whether adb is installed, which phones are plugged in and whether control is on | No |
| `phone_screen` | Reads the screen as numbered text elements with tap positions | No |
| `phone_apps` | Lists the package names of apps you installed | No |
| `phone_tap` | Taps by visible text, by element number or by x and y | Yes |
| `phone_type` | Types into the selected text box | Yes |
| `phone_scroll` | Scrolls up, down, left or right | Yes |
| `phone_key` | Presses back, home, recents, enter, delete or tab | Yes |
| `phone_open` | Opens an app by package name | Yes |

## Safety

- **You switch it on.** Control stays off until you press the button. The assistant cannot press it, because requests from the assistant never carry the button's approval header.
- **It switches itself off.** Control covers one phone and ends after 30 minutes.
- **It stays on this computer.** Hosted servers expose no phone routes or tools.
- **Each action asks first.** Taps, typing, scrolling, key presses and app launches are approval-gated. Screen text is fenced as untrusted, so a message on the screen can't tell the assistant what to do. It also turns off auto-approval for the rest of that run.
- **It won't type passwords.** Typing into a password box is refused, and only plain ASCII text can be typed. Text is quoted for the phone's shell, and adb runs with a fixed argument list and a minimal environment.
- **Every action is logged.** Each one is written to `phone-audit.jsonl` in AutoMoto's data folder. Typed text is recorded only as its length.

## Limits

- Android only for now. iPhone control needs a Mac with iPhone Mirroring and is not built yet.
- Icons without a label show as their resource ID, or not at all. Tap these by element number or position instead.
- Typing supports plain English letters, numbers and symbols only (no emoji or accents). A literal `%s` is typed as a space.
- There's no multi-touch, camera, biometrics or lock-screen PIN. Unlock the phone yourself.
