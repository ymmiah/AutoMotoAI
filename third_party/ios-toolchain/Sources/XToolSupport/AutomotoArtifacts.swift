import Foundation

/// Support files for the iPhone tools. This process does not download them.
enum AutomotoArtifacts {
    static func localTarball(name: String, arch: String) throws -> String {
        let key = "\(name)-\(arch)"
        let envName = name == "darwin-tools" ? "XTL_TOOLSET_TARBALL" : "XTL_OAM_TARBALL"
        if let override = ProcessInfo.processInfo.environment[envName], !override.isEmpty {
            guard FileManager.default.fileExists(atPath: override) else {
                throw Console.Error("The iPhone support file at \(override) is missing.")
            }
            return override
        }
        let lock = try checksum(for: key)
        if lock.isEmpty {
            throw Console.Error("""
            The iPhone support file \(key) is not published yet, so nothing was downloaded.
            Put Xcode.xip on this computer when you have it. The support file is separate             and has to be added by the person who ships this app.
            """)
        }
        throw Console.Error("""
        The iPhone support file \(key) must be checked by the app before the tools see it.
        Set \(envName) to that file. This command will not download it.
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
            throw Console.Error("Artifacts.json has no entry for \(key).")
        }
        return sha
    }
}
