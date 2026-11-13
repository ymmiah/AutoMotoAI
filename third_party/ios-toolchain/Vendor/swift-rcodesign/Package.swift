// swift-tools-version: 6.2

import PackageDescription

let package = Package(
    name: "swift-rcodesign",
    platforms: [.macOS(.v11), .iOS(.v15)],
    products: [
        .library(name: "RCodesign", targets: ["RCodesign"])
    ],
    targets: [
        .target(
            name: "RCodesign",
            dependencies: ["RCodesignBinary"],
            linkerSettings: [
                .linkedFramework("Security", .when(platforms: [.macOS, .iOS])),
                .linkedFramework("CoreFoundation", .when(platforms: [.macOS, .iOS])),
                .linkedLibrary("iconv", .when(platforms: [.macOS, .iOS])),
                .linkedLibrary("dl", .when(platforms: [.linux])),
                .linkedLibrary("pthread", .when(platforms: [.linux])),
                .linkedLibrary("m", .when(platforms: [.linux])),
                .linkedLibrary("rt", .when(platforms: [.linux])),
                .linkedLibrary("util", .when(platforms: [.linux]))
            ]
        ),
        .binaryTarget(
            name: "RCodesignBinary",
            path: "out/RCodesignBinary.artifactbundle"
        ),
        .testTarget(name: "RCodesignTests", dependencies: ["RCodesign"])
    ]
)
