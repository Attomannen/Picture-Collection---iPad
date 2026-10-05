// swift-tools-version: 5.9
// Open this folder in Xcode (File > Open) or in Swift Playgrounds on iPad.
import PackageDescription
import AppleProductTypes

let package = Package(
    name: "PicBoard",
    platforms: [.iOS("17.0")],
    products: [
        .library(name: "PicBoardCore", targets: ["PicBoardCore"]),
        .iOSApplication(
            name: "PicBoard",
            targets: ["App"],
            bundleIdentifier: "com.example.picboard",
            displayVersion: "0.1",
            bundleVersion: "1",
            appIcon: .placeholder(icon: .photo),
            accentColor: .presetColor(.blue),
            supportedDeviceFamilies: [.pad, .phone],
            supportedInterfaceOrientations: [
                .portrait,
                .landscapeRight,
                .landscapeLeft,
                .portraitUpsideDown(.when(deviceFamilies: [.pad]))
            ]
        )
    ],
    targets: [
        .executableTarget(name: "App", dependencies: ["PicBoardCore"], path: "Sources/App"),
        .target(name: "PicBoardCore", path: "Sources/Core"),
        .testTarget(name: "CoreTests", dependencies: ["PicBoardCore"], path: "Tests/CoreTests")
    ]
)
