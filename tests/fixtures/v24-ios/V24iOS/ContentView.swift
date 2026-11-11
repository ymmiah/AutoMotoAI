import SwiftUI

struct ContentView: View {
    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: "swift")
                .font(.system(size: 48))
            Text("V24_IOS_SIMULATOR_PASS")
                .font(.headline)
                .accessibilityIdentifier("v24-simulator-success")
        }
        .padding()
    }
}
