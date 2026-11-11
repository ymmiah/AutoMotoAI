# Make an iPhone app

You tell the assistant what the app should do, or you give it a ZIP. It writes the app, builds it, and can put it on your iPhone. You do not have to read the code. You press one button before anything goes to Apple.

The name on the screen comes from one setting (`AUTOMOTO_BRAND_NAME`). These steps say "the assistant" so they stay right if that name changes.

## What you need

* A **Windows 10 or 11 PC with WSL**, or a **Mac**, or a **Linux** computer. The Microsoft Store copy cannot build iPhone apps. Phones cannot build them either.
* A **real iPhone**. There is no pretend iPhone on Windows or Linux.
* **Xcode.xip**, which you download once from Apple. The assistant does not have a copy and will not download one.
* For the App Store, or for a test install that lasts more than 7 days: a **paid Apple Developer account**.
* An **App Store Connect API key** you create once, if you want to send the app to Apple.

## 1. On your iPhone

1. Open **Settings**.
2. Tap **Privacy & Security**.
3. Tap **Developer Mode**. Turn it on. The phone may restart. Turn it on again if it asks.
4. Plug the phone into the computer with a cable.
5. Unlock the phone. Tap **Trust** when it asks. Enter the phone passcode.

## 2. On a Windows PC

The Store app cannot do this. Use the engine from the [install guide](INSTALL.md) (Local mode).

1. Install **WSL**. In PowerShell:

   ```powershell
   wsl --install
   ```

   Restart if Windows asks. Open **Ubuntu** from the Start menu and finish its first questions.
2. Inside Ubuntu, install Swift 6.2 from [swift.org](https://www.swift.org/install/).
3. In the project folder, inside Ubuntu, build the iPhone command:

   ```bash
   swift build --package-path third_party/ios-toolchain --product automoto-ios
   ```

   If it says the support files are not published yet, stop. Nothing was downloaded. Those files are added later by the person who ships the app. You can still write the project.
4. Put the `automoto-ios` program where the assistant can run it inside WSL.

USB from Windows into WSL is fiddly. If the phone does not show up, the assistant will say no iPhone is connected. That is a WSL limit, not a hidden success.

## 3. On a Mac

1. Download **Xcode.xip** from Apple's developer downloads. Open it so **Xcode.app** exists, or keep the `.xip` and point the assistant at that file.
2. Install Swift 6.2 if `swift` is not already there.
3. Build the command:

   ```bash
   swift build --package-path third_party/ios-toolchain --product automoto-ios
   ```

4. Plug in the iPhone and trust the computer (step 1).

## 4. On Linux

Same build command as Windows step 3, in a normal terminal, not in WSL. You still need your own **Xcode.xip**. Linux cannot run an iPhone simulator. The phone is plugged in over USB.

## 5. The Apple key

Do this once. Do not paste the key into the chat, an issue, or a screenshot.

1. Sign in at [App Store Connect](https://appstoreconnect.apple.com) → **Users and Access** → **Integrations** → **App Store Connect API**.
2. Create a key. Download the `.p8` file. You can download it only once.
3. Move that file into the secrets folder:
   * Mac or Linux: `~/.automoto/secrets/`
   * Windows: `C:\Users\<you>\.automoto\secrets\`
4. Make it private. On Mac or Linux:

   ```bash
   chmod 600 ~/.automoto/secrets/*.p8
   ```

5. In Developer Studio, on the **iPhone app** panel, store three things: the **key id**, the **issuer id**, and the **path** to the `.p8` file. The page stores them in the same private `.env` as your other keys. It does not show the key back.

## 6. Ask for the app

Open a chat and say what you want, for example:

> Make an iPhone app that counts taps.

Or attach a ZIP of a project you already have.

The assistant writes the files and tells you the folder name. It does not paste the source unless you ask to see it.

## 7. Build and install

Ask it to build, then to install on the phone. The phone must be unlocked, trusted, and in Developer Mode.

If this computer cannot build, the assistant says why (Store app, no WSL, tools not built, no phone). It does not pretend the app was installed.

## 8. The App Store page

Ask for the store page. You get a draft: name, description, the privacy words you gave, and a list of screenshots Apple asks for (a 6.7 inch iPhone picture and a 6.5 inch iPhone picture). Add those pictures yourself. The assistant does not invent them.

Read the draft in Developer Studio, under **iPhone app**.

## 9. Send it

1. Tick **I have read this page, including the screenshot list**.
2. Press **Send to Apple**.

Until you press that button, nothing is uploaded. Approving a normal chat step is not enough. The assistant cannot press the button.

The first time, Apple may say the app does not exist yet. Create the app once on the App Store Connect website (same bundle id), then press the button again.

Apple still reviews the app. A send is not an approval.

## Offline

With Offline mode on, the assistant can still create the project from your words or your ZIP, using the AI on this computer. It will not contact Apple. Turn Offline mode off when you are ready to send.

## What this computer does not do

* It does not download Xcode for you.
* It does not contact the project this toolchain was forked from.
* It does not phone a third-party provisioning server. The helper stays on this computer (`127.0.0.1`) unless you point it at one you run and turn that on.
* It does not put secrets in the chat log.
