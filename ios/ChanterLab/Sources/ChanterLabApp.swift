import SwiftUI

/// App-wide objects: one audio engine shared by both screens.
@Observable
final class AppModel {
    let audio = AudioEngine()
    let scales: ScalesModel
    let practice: PracticeModel

    init() {
        scales = ScalesModel(audio: audio)
        practice = PracticeModel(audio: audio, library: Library())
        let practice = self.practice
        audio.pitchListeners.append { [weak practice] frames in practice?.ingest(frames) }
        audio.resetListeners.append { [weak practice] in practice?.audioClockReset() }
        audio.stateListeners.append { [weak practice] in practice?.audioStateChanged() }
        audio.recorder.onInterrupted = { [weak practice] in practice?.recordingInterrupted() }
        audio.errorListeners.append { [weak practice] message in
            guard let practice, practice.micOn else { return }
            practice.micFailed()
            practice.errorMessage = message
        }
    }
}

@main
struct ChanterLabApp: App {
    @State private var app = AppModel()
    @State private var tab = ChanterLabApp.initialTab
    @Environment(\.scenePhase) private var scenePhase

    enum Tab: String { case scales, practice }

    private static var initialTab: Tab {
        #if DEBUG
        if let raw = ProcessInfo.processInfo.environment["CHANTERLAB_TAB"], let tab = Tab(rawValue: raw) { return tab }
        #endif
        return .scales
    }

    var body: some Scene {
        WindowGroup {
            TabView(selection: $tab) {
                ScalesView(model: app.scales)
                    .tabItem { Label("Scales", systemImage: "music.note.list") }
                    .tag(Tab.scales)
                PracticeView(model: app.practice)
                    .tabItem { Label("Practice", systemImage: "music.quarternote.3") }
                    .tag(Tab.practice)
            }
            .tint(Theme.gold)
            .preferredColorScheme(.dark)
            .onChange(of: tab) { _, tab in
                // One screen makes sound at a time.
                switch tab {
                case .scales:
                    app.practice.finishRecording()
                    app.practice.stop()
                    if app.practice.micOn { app.practice.setMic(false) }
                case .practice:
                    app.scales.quiet()
                }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .background, app.scales.idle, app.practice.transport != .playing, !app.practice.micOn {
                    app.audio.suspend()
                }
            }
        }
    }
}
