#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

case "$(uname -s)" in
    Darwin)
        export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-11.0}"
        export IPHONEOS_DEPLOYMENT_TARGET="${IPHONEOS_DEPLOYMENT_TARGET:-15.0}"
        default_targets="aarch64-apple-darwin x86_64-apple-darwin aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios"
        ;;
    Linux) default_targets="$(rustc -vV | sed -n 's/^host: //p')" ;;
    *) echo "Unsupported host platform: $(uname -s)" >&2; exit 1 ;;
esac

if [[ "${1:-}" == --list-targets ]]; then
    printf '%s\n' ${RUST_TARGETS:-$default_targets}
    exit 0
fi

profile="${CARGO_PROFILE:-release}"
output_profile="$profile"
if [[ "$profile" == dev ]]; then output_profile=debug; fi
bundle="out/RCodesignBinary.artifactbundle"

# Override RUST_TARGETS to build only the host slice during local development.
for rust_target in ${RUST_TARGETS:-$default_targets}; do
    case "$rust_target" in
        aarch64-apple-darwin) swift_triple=arm64-apple-macosx; sdk=macosx ;;
        x86_64-apple-darwin) swift_triple=x86_64-apple-macosx; sdk=macosx ;;
        aarch64-apple-ios) swift_triple=arm64-apple-ios; sdk=iphoneos ;;
        aarch64-apple-ios-sim) swift_triple=arm64-apple-ios-simulator; sdk=iphonesimulator ;;
        x86_64-apple-ios) swift_triple=x86_64-apple-ios-simulator; sdk=iphonesimulator ;;
        aarch64-unknown-linux-gnu | x86_64-unknown-linux-gnu) swift_triple="$rust_target"; sdk= ;;
        *) echo "Unsupported target: $rust_target" >&2; exit 1 ;;
    esac

    # staticlib includes the Rust standard library and transitive Rust dependencies.
    # Platform system libraries are declared by Package.swift at the final link.
    if [[ -n "$sdk" ]]; then
        # Select the SDK for native dependencies as well as Rust. In particular,
        # iOS device and simulator libraries must not pick up the host macOS SDK.
        SDKROOT="$(xcrun --sdk "$sdk" --show-sdk-path)" \
            cargo build --locked --profile "$profile" --target "$rust_target"
    else
        cargo build --locked --profile "$profile" --target "$rust_target"
    fi
    mkdir -p "$bundle/$swift_triple"
    archive="$bundle/$swift_triple/librcodesign_ffi.a"
    cp "target/$rust_target/$output_profile/librcodesign_ffi.a" "$archive"
    if [[ "$profile" == release ]]; then
        if [[ -n "$sdk" ]]; then
            xcrun strip -S -x "$archive"
        else
            strip -S -x "$archive"
        fi
    fi
done

mkdir -p "$bundle/include"
cp include/rcodesign.h include/module.modulemap "$bundle/include/"
./scripts/update-info.sh "$bundle"
