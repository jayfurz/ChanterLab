import SwiftUI

@main
struct ChanterLabApp: App {
    var body: some Scene {
        WindowGroup {
            ZStack {
                Color(red: 0.078, green: 0.082, blue: 0.102).ignoresSafeArea()
                WebContainer() // respects the safe area so the page header clears the status bar
            }
        }
    }
}
