import AppKit
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    var window: NSWindow?
    var webView: WKWebView?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1200, height: 800),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Buzz"
        window.minSize = NSSize(width: 840, height: 560)
        window.center()
        window.setFrameAutosaveName("BuzzMain")
        window.backgroundColor = NSColor(red: 0.047, green: 0.067, blue: 0.090, alpha: 1)

        let webView = WKWebView(frame: window.contentView?.bounds ?? .zero)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        if let url = URL(string: "http://127.0.0.1:8081/") {
            webView.load(URLRequest(url: url))
        }

        self.window = window
        self.webView = webView
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
