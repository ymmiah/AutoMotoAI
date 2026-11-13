import Foundation
import RCodesign
import Testing

struct RCodesignTests {
    @Test func signingErrorsCrossTheCBridge() {
        #expect(throws: RCodesign.Error.self) {
            try RCodesign.sign(at: URL(fileURLWithPath: "/dev/null"), identity: .adHoc)
        }
    }

    @Test func invalidIdentityDoesNotFallBackToAdHoc() {
        do {
            try RCodesign.sign(
                at: URL(fileURLWithPath: "/dev/null"),
                identity: .certificate(certificateDER: Data(), privateKeyPEM: Data())
            )
            Issue.record("An empty certificate identity was accepted")
        } catch let error as RCodesign.Error {
            #expect(error.message.contains("invalid signing certificate"))
        } catch {
            Issue.record(error)
        }
    }

    @Test func entitlementPathsCrossTheCBridge() {
        let xml = Data("<plist><dict/></plist>".utf8)
        do {
            try RCodesign.sign(
                at: URL(fileURLWithPath: "/dev/null"), identity: .adHoc,
                options: .init(entitlements: ["../Widget.appex": xml])
            )
            Issue.record("A non-relative entitlement path was accepted")
        } catch let error as RCodesign.Error {
            #expect(error.message.contains("normalized relative bundle path"))
        } catch {
            Issue.record(error)
        }
    }
    @Test func readingEntitlementsCopiesTheOwnedResult() throws {
        let fixture = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("fixtures/entitlements-macho")
        let data = try #require(try RCodesign.entitlements(at: fixture))
        let value = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: String]
        #expect(value?["name"] == "app")
    }

    @Test func unsignedExecutablesHaveNoEntitlements() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: file) }
        // A valid arm64 MH_EXECUTE header with no load commands or signature.
        let header: [UInt32] = [0xfeedfacf, 0x0100000c, 0, 2, 0, 0, 0, 0]
        let bytes = header.flatMap { word in
            (0..<4).map { UInt8(truncatingIfNeeded: word >> ($0 * 8)) }
        }
        try Data(bytes).write(to: file)
        #expect(try RCodesign.entitlements(at: file) == nil)
    }

    @Test func readingErrorsCrossTheCBridge() {
        #expect(throws: RCodesign.Error.self) {
            try RCodesign.entitlements(at: URL(fileURLWithPath: "/dev/null"))
        }
    }

}
