import SwiftUI
import WebKit

/// The web app lives at this origin; the shell only hosts it.
let appURL = URL(string: "https://chanterlab.com/")!

struct WebContainer: UIViewRepresentable {
    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        // No tap-to-unlock dance for playback; the mic prompt still appears once.
        config.mediaTypesRequiringUserActionForPlayback = []

        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = context.coordinator
        web.uiDelegate = context.coordinator
        web.isOpaque = false
        web.backgroundColor = UIColor(red: 0.078, green: 0.082, blue: 0.102, alpha: 1)
        web.scrollView.backgroundColor = web.backgroundColor
        web.scrollView.contentInsetAdjustmentBehavior = .never
        web.allowsBackForwardNavigationGestures = true
        if #available(iOS 16.4, *) { web.isInspectable = true }
        context.coordinator.web = web
        web.load(URLRequest(url: appURL))
        return web
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        weak var web: WKWebView?

        // Grant the mic to our own origin only; the OS-level permission prompt
        // (NSMicrophoneUsageDescription) still appears the first time.
        func webView(_ webView: WKWebView,
                     requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                     initiatedByFrame frame: WKFrameInfo,
                     type: WKMediaCaptureType,
                     decisionHandler: @escaping (WKPermissionDecision) -> Void) {
            decisionHandler(origin.host == appURL.host ? .grant : .deny)
        }

        // Links to other sites open in Safari instead of replacing the app.
        func webView(_ webView: WKWebView,
                     decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if let url = action.request.url, action.navigationType == .linkActivated,
               url.host != appURL.host, url.host != "www.chanterlab.com",
               ["http", "https"].contains(url.scheme) {
                UIApplication.shared.open(url)
                decisionHandler(.cancel)
            } else {
                decisionHandler(.allow)
            }
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                     withError error: Error) {
            let html = """
            <meta name=viewport content='width=device-width,initial-scale=1'>
            <body style='background:#14151a;color:#e8e8ee;font:17px -apple-system;display:flex;
            flex-direction:column;align-items:center;justify-content:center;height:100vh;margin:0;gap:16px'>
            <div>ChanterLab can't reach the server.</div>
            <button onclick="location.href='\(appURL.absoluteString)'"
             style='font-size:17px;padding:10px 22px;border-radius:10px;border:0'>Try again</button>
            """
            webView.loadHTMLString(html, baseURL: nil)
        }
    }
}
