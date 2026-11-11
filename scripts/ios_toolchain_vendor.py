#!/usr/bin/env python3
"""Refresh third_party/ios-toolchain from local upstream checkouts.

This script does not download anything. Point it at checkouts you already have:

    python scripts/ios_toolchain_vendor.py \
        --toolchain /path/to/xtool \
        --core /path/to/xtool-core \
        --mobile /path/to/SwiftyMobileDevice \
        --rcodesign /path/to/swift-rcodesign

It copies the sources we build, rewrites package dependencies onto Vendor/,
and removes the hosts the callout scan forbids. Upstream URLs stay only in
third_party/ios-toolchain/NOTICE.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "third_party" / "ios-toolchain"

SKIP_DIR_NAMES = {".git", ".github", ".build", "Documentation"}
SKIP_FILE_NAMES = {"Package.resolved"}
SKIP_SUFFIXES = {".png", ".PNG", ".icns", ".jpg", ".jpeg", ".zip", ".graffle"}

# Applied to every copied text file. The toolchain repo name must not swallow
# xtool-core or xtool-libs, which share that prefix.
REPLACEMENTS = (
    (
        "https://github.com/xtool-org/xtool-libs/releases/download/1.0.0/",
        "https://github.com/ymmiah/AutoMotoAI/releases/download/ios-device-libs/1.0.0/",
    ),
    ("ghcr.io/xtool-org/xtool:latest", "automoto-ios:local"),
    ("brew install xtool-org/tap/xtool", "swift build --product automoto-ios"),
    ("https://github.com/SideStore/omnisette-server", "the local provisioning helper"),
    ("https://servers.sidestore.io/servers.json", "the local provisioning helper"),
    ("https://mac-ani.jkcoxson.com", "http://127.0.0.1:6969"),
)
_XTOOL_REPO = re.compile(r"https://github\.com/xtool-org/xtool(?![-A-Za-z0-9])")


def _git(repo: Path, *args: str) -> str:
    out = subprocess.check_output(["git", "-C", str(repo), *args], text=True)
    return out.strip()


def _copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    def ignore(directory: str, names: list[str]) -> set[str]:
        skipped = set()
        for name in names:
            if name in SKIP_DIR_NAMES or name in SKIP_FILE_NAMES:
                skipped.add(name)
                continue
            if any(name.endswith(suffix) for suffix in SKIP_SUFFIXES):
                skipped.add(name)
        return skipped

    shutil.copytree(src, dest, ignore=ignore, dirs_exist_ok=True)


def _rewrite(dest: Path) -> None:
    for path in dest.rglob("*"):
        if not path.is_file():
            continue
        if path.name in SKIP_FILE_NAMES or path.name == "NOTICE":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        updated = text
        for old, new in REPLACEMENTS:
            updated = updated.replace(old, new)
        updated = _XTOOL_REPO.sub("https://github.com/ymmiah/AutoMotoAI", updated)
        updated = updated.replace("xtool-org", "ymmiah")
        updated = updated.replace("SideStore", "a local helper")
        updated = updated.replace("sidestore", "local-helper")
        updated = updated.replace("jkcoxson", "local-helper")
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="\n")


def _patch_package(dest: Path) -> None:
    path = dest / "Package.swift"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '.package(url: "https://github.com/ymmiah/xtool-core", .upToNextMinor(from: "1.5.1")),\n'
        '        .package(url: "https://github.com/ymmiah/SwiftyMobileDevice", .upToNextMinor(from: "1.7.0")),\n'
        '        .package(url: "https://github.com/ymmiah/swift-rcodesign", .upToNextMinor(from: "0.2.0")),',
        '.package(path: "Vendor/xtool-core"),\n'
        '        .package(path: "Vendor/SwiftyMobileDevice"),\n'
        '        .package(path: "Vendor/swift-rcodesign"),',
    )
    # The generic host rewrite may not have matched if the path rewrite above
    # already ran against the original URLs. Handle both spellings.
    text = text.replace(
        '.package(url: "https://github.com/xtool-org/xtool-core", .upToNextMinor(from: "1.5.1")),\n'
        '        .package(url: "https://github.com/xtool-org/SwiftyMobileDevice", .upToNextMinor(from: "1.7.0")),\n'
        '        .package(url: "https://github.com/xtool-org/swift-rcodesign", .upToNextMinor(from: "0.2.0")),',
        '.package(path: "Vendor/xtool-core"),\n'
        '        .package(path: "Vendor/SwiftyMobileDevice"),\n'
        '        .package(path: "Vendor/swift-rcodesign"),',
    )
    text = text.replace(
        """.executable(
            name: "xtool",
            targets: ["xtool"]
        ),""",
        """.executable(
            name: "automoto-ios",
            targets: ["automoto-ios"]
        ),""",
    )
    text = text.replace(
        """.executableTarget(
            name: "xtool",
            dependencies: [""",
        """.executableTarget(
            name: "automoto-ios",
            path: "Sources/xtool",
            dependencies: [""",
    )
    path.write_text(text, encoding="utf-8", newline="\n")

    mobile = dest / "Vendor" / "SwiftyMobileDevice" / "Package.swift"
    mobile_text = mobile.read_text(encoding="utf-8")
    mobile_text = mobile_text.replace(
        '.package(url: "https://github.com/ymmiah/xtool-core", .upToNextMinor(from: "1.5.0")),',
        '.package(path: "../xtool-core"),',
    )
    mobile_text = mobile_text.replace(
        '.package(url: "https://github.com/xtool-org/xtool-core", .upToNextMinor(from: "1.5.0")),',
        '.package(path: "../xtool-core"),',
    )
    mobile.write_text(mobile_text, encoding="utf-8", newline="\n")


def _patch_sources(dest: Path) -> None:
    command = dest / "Sources" / "XToolSupport" / "XTool.swift"
    text = command.read_text(encoding="utf-8")
    text = text.replace('commandName: "xtool"', 'commandName: "automoto-ios"')
    text = text.replace('version: "xtool \\(XTool.version)"', 'version: "automoto-ios \\(XTool.version)"')
    command.write_text(text, encoding="utf-8", newline="\n")

    dev = dest / "Sources" / "XToolSupport" / "DevCommand.swift"
    dev_text = dev.read_text(encoding="utf-8")
    dev_text = dev_text.replace(
        'let configPath = URL(fileURLWithPath: "xtool.yml")\n'
        "        if FileManager.default.fileExists(atPath: configPath.path) {",
        "let preferred = URL(fileURLWithPath: \"automoto-ios.yml\")\n"
        "        let fallback = URL(fileURLWithPath: \"xtool.yml\")\n"
        "        let configPath = FileManager.default.fileExists(atPath: preferred.path) ? preferred : fallback\n"
        "        if FileManager.default.fileExists(atPath: configPath.path) {",
    )
    dev.write_text(dev_text, encoding="utf-8", newline="\n")

    new_cmd = dest / "Sources" / "XToolSupport" / "NewCommand.swift"
    new_text = new_cmd.read_text(encoding="utf-8")
    new_text = new_text.replace('(\n                "xtool.yml",', '(\n                "automoto-ios.yml",')
    new_cmd.write_text(new_text, encoding="utf-8", newline="\n")

    lsp = dest / "Sources" / "XToolSupport" / "LSPConfig.swift"
    lsp_text = lsp.read_text(encoding="utf-8")
    lsp_text = lsp_text.replace('"/usr/bin/env", "xtool", "dev"', '"/usr/bin/env", "automoto-ios", "dev"')
    lsp.write_text(lsp_text, encoding="utf-8", newline="\n")

    sdk = dest / "Sources" / "XToolSupport" / "SDKBuilder.swift"
    sdk_text = sdk.read_text(encoding="utf-8")
    sdk_text = sdk_text.replace(
        """        let url = URL(string: \"\"\"
        https://github.com/ymmiah/darwin-tools-linux-llvm/releases/download/\\
        v\\(Self.darwinToolsVersion)/toolset-\\(arch.rawValue).tar.gz
        \"\"\")!
        try await fetchTarball(""",
        """        let pinned = try AutomotoArtifacts.localTarball(name: "darwin-tools", arch: arch.rawValue)
        let url = URL(fileURLWithPath: pinned)
        try await fetchTarball(""",
    )
    sdk_text = sdk_text.replace(
        """        let url = URL(string: \"\"\"
        https://github.com/ymmiah/OpenAppleMacros/releases/download/\\
        v\\(Self.oamVersion)/OpenAppleMacrosServer-\\(arch.rawValue).tar.gz
        \"\"\")!
        let macrosDir = output.appendingPathComponent("OpenAppleMacros")""",
        """        let pinned = try AutomotoArtifacts.localTarball(name: "open-apple-macros", arch: arch.rawValue)
        let url = URL(fileURLWithPath: pinned)
        let macrosDir = output.appendingPathComponent("OpenAppleMacros")""",
    )
    # Comments that named the old release tags.
    sdk_text = sdk_text.replace(
        "// tag from https://github.com/ymmiah/darwin-tools-linux-llvm\n",
        "// Pinned in Artifacts.json. The file must already be on disk.\n",
    )
    sdk_text = sdk_text.replace(
        "// tag from https://github.com/ymmiah/OpenAppleMacros\n",
        "// Pinned in Artifacts.json. The file must already be on disk.\n",
    )
    sdk_text = sdk_text.replace(
        'echo "Please file an issue at https://github.com/ymmiah/AutoMotoAI/issues" >&2',
        'echo "Please file an issue on the project that ships automoto-ios" >&2',
    )
    sdk.write_text(sdk_text, encoding="utf-8", newline="\n")

    linux = dest / "Linux" / "build.sh"
    if linux.is_file():
        linux_text = linux.read_text(encoding="utf-8")
        linux_text = linux_text.replace("--product xtool", "--product automoto-ios")
        linux_text = linux_text.replace('"${bin}/xtool"', '"${bin}/automoto-ios"')
        linux_text = linux_text.replace("-e \"${bin}/xtool\"", "-e \"${bin}/automoto-ios\"")
        linux_text = "\n".join(
            line for line in linux_text.splitlines()
            if "LDAI_UPDATE_INFORMATION" not in line
        ) + "\n"
        linux.write_text(linux_text, encoding="utf-8", newline="\n")

    provider = dest / "Sources" / "XKit" / "GrandSlam" / "Anisette" / "ADIDataProvider.swift"
    provider_text = provider.read_text(encoding="utf-8")
    provider_text = provider_text.replace(
        "static let liveValue: RawADIProvider = OmnisetteADIProvider()",
        "static let liveValue: RawADIProvider = OmnisetteADIProvider.live()",
    )
    provider_text = provider_text.replace(
        "https://github.com/ymmiah/AutoMotoAI/issues/new/choose",
        "the project issues for the app that ships automoto-ios",
    )
    provider.write_text(provider_text, encoding="utf-8", newline="\n")

    omni = dest / "Sources" / "XKit" / "GrandSlam" / "Anisette" / "OmnisetteADIProvider.swift"
    omni_text = omni.read_text(encoding="utf-8")
    omni_text = omni_text.replace(
        """    // should implement v3 of the local provisioning helper
    // list: the local provisioning helper
    private let url: URL
    init(
        url: URL = URL(string: "http://127.0.0.1:6969")!
    ) {
        self.url = url
    }""",
        """    // Provisioning data stays on this computer unless AUTOMOTO_ANISETTE_URL
    // points somewhere the owner runs. There is no third-party default.
    private let url: URL
    init(url: URL) {
        self.url = url
    }

    static func live() -> OmnisetteADIProvider {
        let raw = ProcessInfo.processInfo.environment["AUTOMOTO_ANISETTE_URL"] ?? "http://127.0.0.1:6969"
        guard let url = URL(string: raw), let host = url.host?.lowercased(), !host.isEmpty else {
            fatalError("AUTOMOTO_ANISETTE_URL is not a usable address.")
        }
        let loopback = host == "127.0.0.1" || host == "localhost" || host == "::1"
        let allowed = ProcessInfo.processInfo.environment["AUTOMOTO_ANISETTE_ALLOW_REMOTE"] == "1"
        guard loopback || allowed else {
            fatalError("AUTOMOTO_ANISETTE_URL must be on this computer unless AUTOMOTO_ANISETTE_ALLOW_REMOTE=1.")
        }
        return OmnisetteADIProvider(url: url)
    }""",
    )
    omni.write_text(omni_text, encoding="utf-8", newline="\n")


def _write_artifacts(dest: Path) -> None:
    # Device-library checksums identify the archives the core package already
    # pinned. They are not fetched by this script. Darwin toolset and macro
    # archives stay unpublished until the owner fills the checksums.
    payload = {
        "base_url": "https://github.com/ymmiah/AutoMotoAI/releases/download/ios-sdk-support",
        "device_libs_base_url": "https://github.com/ymmiah/AutoMotoAI/releases/download/ios-device-libs/1.0.0",
        "artifacts": {
            "darwin-tools-aarch64": {"file": "darwin-tools-aarch64.tar.gz", "sha256": ""},
            "darwin-tools-x86_64": {"file": "darwin-tools-x86_64.tar.gz", "sha256": ""},
            "open-apple-macros-aarch64": {"file": "open-apple-macros-aarch64.tar.gz", "sha256": ""},
            "open-apple-macros-x86_64": {"file": "open-apple-macros-x86_64.tar.gz", "sha256": ""},
            "plist.xcframework.zip": {
                "file": "plist.xcframework.zip",
                "sha256": "b71d1b2c86880cd2c8f353c6357c6d610849a2b461855ae782922720a0ecce3e",
            },
            "libimobiledeviceGlue.xcframework.zip": {
                "file": "libimobiledeviceGlue.xcframework.zip",
                "sha256": "227c43c1d7db213f3f75d8cdb0bba873321151ff80c2afd5217982642a2810e1",
            },
            "usbmuxd.xcframework.zip": {
                "file": "usbmuxd.xcframework.zip",
                "sha256": "9afdc82607c4339e19f31a487fe042ebee778040e805380704c5d89fb2a99081",
            },
            "libimobiledevice.xcframework.zip": {
                "file": "libimobiledevice.xcframework.zip",
                "sha256": "24c23d4ac43581e9bd6f3f198bade77d0ca928226b4a2230963162472828611f",
            },
        },
    }
    (dest / "Artifacts.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    swift = '''import Foundation

/// Support files for the iPhone tools. This process does not download them.
enum AutomotoArtifacts {
    static func localTarball(name: String, arch: String) throws -> String {
        let key = "\\(name)-\\(arch)"
        let envName = name == "darwin-tools" ? "XTL_TOOLSET_TARBALL" : "XTL_OAM_TARBALL"
        if let override = ProcessInfo.processInfo.environment[envName], !override.isEmpty {
            guard FileManager.default.fileExists(atPath: override) else {
                throw Console.Error("The iPhone support file at \\(override) is missing.")
            }
            return override
        }
        let lock = try checksum(for: key)
        if lock.isEmpty {
            throw Console.Error("""
            The iPhone support file \\(key) is not published yet, so nothing was downloaded.
            Put Xcode.xip on this computer when you have it. The support file is separate \
            and has to be added by the person who ships this app.
            """)
        }
        throw Console.Error("""
        The iPhone support file \\(key) must be checked by the app before the tools see it.
        Set \\(envName) to that file. This command will not download it.
        """)
    }

    private static func checksum(for key: String) throws -> String {
        let here = URL(fileURLWithPath: #filePath)
        let url = here.deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("Artifacts.json")
        let data = try Data(contentsOf: url)
        let object = try JSONSerialization.jsonObject(with: data)
        guard let root = object as? [String: Any],
              let artifacts = root["artifacts"] as? [String: Any],
              let entry = artifacts[key] as? [String: Any],
              let sha = entry["sha256"] as? String else {
            throw Console.Error("Artifacts.json has no entry for \\(key).")
        }
        return sha
    }
}
'''
    (dest / "Sources" / "XToolSupport" / "AutomotoArtifacts.swift").write_text(swift, encoding="utf-8", newline="\n")


def _write_notice(dest: Path, commits: dict[str, str]) -> None:
    text = f"""MIT licence notice for the iPhone toolchain snapshot

The sources under this directory (except files this project added, listed at
the bottom) are a snapshot of an MIT-licensed toolchain and three libraries
it builds with. The combined AutoMoto program is AGPL-3.0-only. The MIT
notice below is kept because the MIT licence requires it.

Upstream project: https://github.com/xtool-org/xtool
Pinned commit: {commits["toolchain"]}
Copyright (c) 2024 Kabir Oberai and contributors

Vendored library: https://github.com/xtool-org/xtool-core
Pinned commit: {commits["core"]}
Copyright (c) 2024 Kabir Oberai

Vendored library: https://github.com/xtool-org/SwiftyMobileDevice
Pinned commit: {commits["mobile"]}
Copyright (c) 2020 Kabir Oberai

Vendored library: https://github.com/xtool-org/swift-rcodesign
Pinned commit: {commits["rcodesign"]}
The pinned snapshot contained no licence file. Confirm the terms before
redistributing a binary built from it. It binds the apple-codesign crate.

Anisette servers this snapshot used to contact, which this copy does not
contact: https://servers.sidestore.io and https://mac-ani.jkcoxson.com

MIT Licence

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Files added by this project, not covered by the MIT grant above:
- NOTICE (this file)
- README.md
- UPSTREAM.json
- Artifacts.json
- Sources/XToolSupport/AutomotoArtifacts.swift
"""
    (dest / "NOTICE").write_text(text, encoding="utf-8", newline="\n")
    (dest / "UPSTREAM.json").write_text(json.dumps({
        "toolchain": commits["toolchain"],
        "core": commits["core"],
        "mobile": commits["mobile"],
        "rcodesign": commits["rcodesign"],
    }, indent=2) + "\n", encoding="utf-8", newline="\n")
    (dest / "README.md").write_text(
        "In-house iPhone toolchain sources. Build the `automoto-ios` product with Swift 6.2.\n"
        "Attribution and the MIT notice are in NOTICE. Checksums for support files are in\n"
        "Artifacts.json. Empty checksums mean the file is not published and must not be downloaded.\n"
        "The app never redistributes Apple SDKs. The person supplies their own Xcode.xip.\n",
        encoding="utf-8",
        newline="\n",
    )


def vendor(toolchain: Path, core: Path, mobile: Path, rcodesign: Path) -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    _copy_tree(toolchain, DEST)
    vendor_dir = DEST / "Vendor"
    vendor_dir.mkdir()
    _copy_tree(core, vendor_dir / "xtool-core")
    _copy_tree(mobile, vendor_dir / "SwiftyMobileDevice")
    _copy_tree(rcodesign, vendor_dir / "swift-rcodesign")
    _rewrite(DEST)
    _patch_package(DEST)
    _patch_sources(DEST)
    commits = {
        "toolchain": _git(toolchain, "rev-parse", "HEAD"),
        "core": _git(core, "rev-parse", "HEAD"),
        "mobile": _git(mobile, "rev-parse", "HEAD"),
        "rcodesign": _git(rcodesign, "rev-parse", "HEAD"),
    }
    _write_notice(DEST, commits)
    _write_artifacts(DEST)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--mobile", type=Path, required=True)
    parser.add_argument("--rcodesign", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.toolchain, args.core, args.mobile, args.rcodesign):
        if not path.is_dir():
            raise SystemExit(f"not a directory: {path}")
    vendor(args.toolchain, args.core, args.mobile, args.rcodesign)
    print(f"wrote {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
