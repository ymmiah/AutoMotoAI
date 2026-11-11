#!/usr/bin/env bash
set -euo pipefail
# V23 acceptance on an isolated GitHub emulator runner ONLY.
# This script is NOT invoked by the desktop Studio.
project="tests/fixtures/v23-android"
gradle -p "$project" --offline --no-daemon --console=plain :app:assembleDebug
apk="$project/app/build/outputs/apk/debug/app-debug.apk"
test -s "$apk"
adb wait-for-device
adb install -r "$apk"
result="$(adb shell am start -W -n com.automoto.v23/.MainActivity)"
printf '%s\n' "$result"
grep -q "Status: ok" <<<"$result"
sleep 4
adb shell uiautomator dump /sdcard/v23-window.xml
adb shell cat /sdcard/v23-window.xml | grep -q V23_ANDROID_RUNNING
printf '%s\n' "V23_ANDROID_EMULATOR_UI_PASS"
