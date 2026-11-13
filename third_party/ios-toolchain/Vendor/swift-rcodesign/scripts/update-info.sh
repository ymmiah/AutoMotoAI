#!/bin/bash

set -euo pipefail

bundle="${1:?usage: update-info.sh <artifact-bundle> [version]}"
version="${2:-0.1.0}"
triples=(
    arm64-apple-macosx
    x86_64-apple-macosx
    arm64-apple-ios
    arm64-apple-ios-simulator
    x86_64-apple-ios-simulator
    aarch64-unknown-linux-gnu
    x86_64-unknown-linux-gnu
)

mkdir -p "$bundle"

available_triples=()
for triple in "${triples[@]}"; do
    [[ -f "$bundle/$triple/librcodesign_ffi.a" ]] || continue
    available_triples+=("$triple")
done

if (( ${#available_triples[@]} == 0 )); then
    echo "No supported librcodesign_ffi.a variants found in $bundle" >&2
    exit 1
fi

{
    cat <<EOF
{
    "schemaVersion": "1.0",
    "artifacts": {
        "RCodesignBinary": {
            "version": "$version",
            "type": "staticLibrary",
            "variants": [
EOF

    for index in "${!available_triples[@]}"; do
        triple="${available_triples[$index]}"
        path="$triple/librcodesign_ffi.a"
        comma=,
        if (( index == ${#available_triples[@]} - 1 )); then
            comma=
        fi

        cat <<EOF
                {
                    "path": "$path",
                    "supportedTriples": ["$triple"],
                    "staticLibraryMetadata": {
                        "headerPaths": ["include"],
                        "moduleMapPath": "include/module.modulemap"
                    }
                }$comma
EOF
    done

    cat <<'EOF'
            ]
        }
    }
}
EOF
} > "$bundle/info.json"
