import SwiftUI

@main
struct ChanterLabApp: App {
    @State private var scales = ScalesModel()
    @State private var tab = Tab.scales
    @Environment(\.scenePhase) private var scenePhase

    private enum Tab { case scales, practice }

    var body: some Scene {
        WindowGroup {
            TabView(selection: $tab) {
                ScalesView(model: scales)
                    .tabItem { Label("Scales", systemImage: "music.note.list") }
                    .tag(Tab.scales)

                // Score practice still runs the web app; it moves to native screens next.
                ZStack {
                    Theme.background.ignoresSafeArea()
                    WebContainer()
                }
                .tabItem { Label("Practice", systemImage: "music.quarternote.3") }
                .tag(Tab.practice)
            }
            .tint(Theme.gold)
            .preferredColorScheme(.dark)
            .onChange(of: tab) { _, tab in
                // The web view runs its own audio session; do not sing over it.
                if tab == .practice { scales.quiet() }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .background, scales.idle { scales.audio.suspend() }
            }
        }
    }
}
