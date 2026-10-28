#!/usr/bin/env bash
# Generates the Android + iOS platform folders and applies AutoMoto's permissions.
# Run from apps/mobile with the Flutter SDK installed (Xcode needed for iOS builds).
set -euo pipefail
cd "$(dirname "$0")/.."
flutter create --org com.ymmiah --project-name automoto_mobile --platforms=android,ios .
flutter pub get

# Android: allow plain-HTTP to your own LAN server (AutoMoto runs on your PC).
MANIFEST=android/app/src/main/AndroidManifest.xml
grep -q usesCleartextTraffic "$MANIFEST" || \
  perl -0pi -e 's/<application/<application android:usesCleartextTraffic="true"/' "$MANIFEST"
grep -q "android.permission.INTERNET" "$MANIFEST" || \
  perl -0pi -e 's/(\s*)<application/$1<uses-permission android:name="android.permission.INTERNET"\/>$1<application/' "$MANIFEST"

# iOS: camera/photos usage strings + local-network HTTP for the AutoMoto server.
PLIST=ios/Runner/Info.plist
if [ -f "$PLIST" ] && command -v /usr/libexec/PlistBuddy >/dev/null; then
  PB=/usr/libexec/PlistBuddy
  $PB -c "Add :NSCameraUsageDescription string 'Snap a photo for AutoMoto to read or explain.'" "$PLIST" 2>/dev/null || true
  $PB -c "Add :NSPhotoLibraryUsageDescription string 'Pick an image for AutoMoto to read or explain.'" "$PLIST" 2>/dev/null || true
  $PB -c "Add :NSLocalNetworkUsageDescription string 'Connect to your AutoMoto server on this network.'" "$PLIST" 2>/dev/null || true
  $PB -c "Add :NSAppTransportSecurity dict" "$PLIST" 2>/dev/null || true
  $PB -c "Add :NSAppTransportSecurity:NSAllowsLocalNetworking bool true" "$PLIST" 2>/dev/null || true
else
  echo "Not on macOS: add NSCameraUsageDescription, NSPhotoLibraryUsageDescription and"
  echo "NSAppTransportSecurity > NSAllowsLocalNetworking to ios/Runner/Info.plist before building iOS."
fi
echo "Ready: flutter run   (Android)   ·   open ios/Runner.xcworkspace   (iOS)"
