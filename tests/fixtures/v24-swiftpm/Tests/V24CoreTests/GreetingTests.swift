import XCTest
@testable import V24Core

final class GreetingTests: XCTestCase {
    func testArithmetic() {
        XCTAssertEqual(Greeting.calculate(20, 22), 42)
    }
    func testMarker() {
        XCTAssertEqual(Greeting.marker, "V24_SWIFTPM_SMOKE_PASS")
    }
}
