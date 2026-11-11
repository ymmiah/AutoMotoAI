# swift-rcodesign

Swift bindings to [apple-codesign](https://github.com/indygreg/apple-platform-rs/tree/main/apple-codesign).

WARNING: VERY VIBE CODED

The Rust crate builds a static library containing its Rust dependencies. Like
[xadi](https://github.com/ymmiah/xadi), `scripts/build.sh` packages it in a
SwiftPM static-library artifact bundle. Consumers of a published package need
Swift 6.2+, but do not need Rust. Supported platforms are macOS 11+ and glibc
Linux on arm64 and x86_64, iOS 15+ on arm64 devices, and the iOS Simulator on
arm64 and x86_64.

## API

```swift
import Foundation
import RCodesign

let xml = Data("<plist><dict><key>get-task-allow</key><true/></dict></plist>".utf8)
try RCodesign.sign(
    at: URL(fileURLWithPath: "/path/to/App.app"),
    identity: .adHoc,
    options: .init(entitlements: ["": xml])
)

let certificate = try Data(contentsOf: URL(fileURLWithPath: "/path/to/certificate.der"))
let privateKey = try Data(contentsOf: URL(fileURLWithPath: "/path/to/private-key.pem"))
try RCodesign.sign(
    at: URL(fileURLWithPath: "/path/to/App.app"),
    identity: .certificate(certificateDER: certificate, privateKeyPEM: privateKey),
    options: .init(entitlements: ["": xml, "PlugIns/Widget.appex": xml])
)
```

The API provides ad-hoc and certificate-backed signing with XML or binary
entitlements dictionaries. Private keys must be a single unencrypted PKCS#1 RSA
or PKCS#8 PEM block and must match the DER certificate. Apple CA certificates and
team IDs are derived by apple-codesign; no timestamp server is contacted.
Embedded provisioning profiles are preserved. apple-codesign generates embedded
DER entitlements internally when signing.

Signing is recursive by default. Entitlements are keyed by bundle-relative path:
use `""` for the root and separate entries for extensions. Each bundle should
receive its own provisioned entitlements; the example reuses `xml` only for
brevity. Paths must exist and have no empty, `.` or `..` components. Set
`shallow: true` for a single bundle; this rejects nested entitlement entries.

It deliberately exposes upstream signing behavior rather than implementing
Apple's codesign command-line syntax:
existing metadata is imported automatically, bundle identifiers come from the
Info.plist, and shallow mode skips nested bundles but may sign embedded standalone
Mach-O files. In-place signing can leave partial changes on failure. A separate
output URL can be supplied to preserve the input.

Read a bundle or Mach-O executable's entitlements with:

```swift
let entitlements: Data? = try RCodesign.entitlements(at: appURL)
```

The result is an XML plist dictionary, or `nil` when the executable is unsigned
or has no entitlements. An empty dictionary remains a non-nil plist. Universal
binaries use the first architecture in file order. XML entitlements take precedence;
XML bytes are preserved, and DER is decoded when XML is absent. Reading does not verify the signature or trust,
and malformed inputs throw rather than being treated as absent entitlements.

`include/rcodesign.h` documents the C ABI and allocation contracts. The Swift
wrapper frees Rust error allocations and throws owned errors. Rust unwinding
panics are caught before returning through C. Selective metadata preservation
is not exposed yet. The ABI is experimental until version 1.0.

## Development

Install Rust with rustup and Swift 6.2+. `make lint` also requires SwiftLint. The toolchain is pinned in
`rust-toolchain.toml`; `Cargo.lock` pins the dependency graph. On macOS, install
the macOS, iOS, and iOS Simulator targets once:

```sh
rustup target add --toolchain 1.95.0 $(./scripts/build.sh --list-targets)
make test
make lint
```

On macOS, builds require Xcode with the iOS SDKs and produce all five Apple
slices. Linux builds the native glibc architecture and requires a C compiler and
linker.
For faster local iteration on Apple Silicon:

```sh
RUST_TARGETS=aarch64-apple-darwin CARGO_PROFILE=dev make test
```

Build the artifact bundle with `make build` before invoking SwiftPM from a source
checkout. `make test-without-building` tests an existing bundle. Generated
artifacts are ignored by Git.

## Releases

As in xadi, `./scripts/release.sh <major|minor|patch|v1.2.3>` pushes a `source-*` tag.
CI builds all seven platform variants, runs tests on macOS and Linux, uploads an
artifact bundle to the source tag's GitHub release, and publishes a `release`
branch and `v*` tag whose
manifest references that download. The remote GitHub repository must be configured
before releasing. No artifacts need to be committed to the source branch.
