# Android and iOS — what only the owner can do

The app UI is the same web interface on a narrow screen: large tap targets, a sidebar that
closes after you pick a page, and the chat column filling the screen. Phones do not run the
offline GGUF models. They talk to an AutoMoto server you already run.

The Flutter project in `apps/mobile` is the store client. CI builds:

- Android **debug APK** and **debug AAB** on `ubuntu-latest` (no upload key required)
- iOS **simulator** build on `macos-latest` when a macOS runner is available (`--no-codesign`)

A debug package cannot be shipped. These are the steps that need your accounts.

## Google Play (Android)

1. Create or open the app in <https://play.google.com/console> with the owner Google account.
2. Application ID: `com.ymmiah.automoto_mobile` (from `apps/mobile/tool/bootstrap.sh`).
3. Create an upload key on your PC. Do not commit the keystore or the passwords.
4. Enroll Play App Signing so Google holds the app signing key.
5. Build a release bundle locally: `flutter build appbundle --release` after `tool/bootstrap.sh`.
6. Upload the `.aab` to an internal testing track first.
7. Fill the store listing, content rating, privacy policy (`docs/PRIVACY.md`) and data-safety form.
   Local mode does not send chats to AutoMoto. A server URL the user types is their own server.
8. You submit the track. CI does not.

## Apple App Store (iOS)

1. Enrol in the Apple Developer Program with the owner Apple ID.
2. In Xcode, open `apps/mobile/ios/Runner.xcworkspace` after `tool/bootstrap.sh` on a Mac.
3. Set the team and a bundle id you own, for example `com.ymmiah.automotoMobile`.
4. Create the App Store Connect record. Add the privacy policy URL and screenshots from a
   device or simulator you run yourself.
5. Archive with a distribution certificate and upload with Xcode or `altool`. CI's simulator
   build is not that archive, and it does not use your certificate.
6. Answer App Privacy. The app stores the server URL and token in the Keychain.
7. You press Submit. CI does not.

## Tauri mobile

The Windows app is Tauri 2 with `decorations: false` and its own caption bar. That caption
bar is for Windows. A future Tauri Android or iOS shell can load the same web UI, which is
already responsive. The Flutter client is the project CI builds today. Adding a Tauri mobile
target still needs the same Apple and Google accounts as above, plus the platform SDKs on
your machine.
