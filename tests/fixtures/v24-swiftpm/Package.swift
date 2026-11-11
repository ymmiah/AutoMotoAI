// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "V24Swift",
    products: [
        .library(name: "V24Core", targets: ["V24Core"]),
        .executable(name: "V24CLI", targets: ["V24CLI"])
    ],
    dependencies: [],
    targets: [
        .target(name: "V24Core"),
        .executableTarget(name: "V24CLI", dependencies: ["V24Core"]),
        .testTarget(name: "V24CoreTests", dependencies: ["V24Core"])
    ]
)
