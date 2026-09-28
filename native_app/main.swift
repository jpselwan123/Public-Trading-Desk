import Cocoa
import WebKit

// Trading Desk.app: starts the desk's local server, shows the page in its own window,
// and stops the server when the window closes. It does what ./desk.sh does, as an app
// that can sit in the Dock.
//
// The desk is found in ~/trading-desk, resolved from the current user's home rather
// than written in, so no personal path is in the source.
let deskDir = NSHomeDirectory() + "/trading-desk"
let port = 8935
let deskURL = URL(string: "http://127.0.0.1:\(port)/")!
let readyURL = URL(string: "http://127.0.0.1:\(port)/data")!

func bash(_ command: String) -> Process {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/bin/bash")
    p.arguments = ["-c", command]
    return p
}

// As desk.sh does, a server already listening is stopped first: it may be in demo mode,
// or older than the code. Then any new code is brought in (update.sh: a fast-forward
// only, given up after 20 seconds without a connection), the page is built from the code
// as it is now, and this app's own server is started, bound to 127.0.0.1 by server.py.
let stopOld = bash("lsof -ti tcp:\(port) -sTCP:LISTEN | xargs kill 2>/dev/null; sleep 0.4")
try? stopOld.run()
stopOld.waitUntilExit()
let server = bash("cd \"\(deskDir)\" && { ./update.sh >> server.log 2>&1 || true; } "
                  + "&& { python3 build_desk.py >> server.log 2>&1 || true; } "
                  + "&& exec python3 server.py >> server.log 2>&1")
try? server.run()

func page(_ title: String, _ body: String) -> String {
    return """
    <html><body style="margin:0;background:#10161F;color:#E4E9F0;font:15px -apple-system,sans-serif;
    display:flex;align-items:center;justify-content:center;height:100vh"><div style="max-width:560px;padding:32px;line-height:1.6">
    <h2 style="margin:0 0 8px;font-weight:600">\(title)</h2>\(body)</div></body></html>
    """
}

class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var tries = 0

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        let frame = NSRect(x: 0, y: 0, width: 1320, height: 900)
        webView = WKWebView(frame: frame, configuration: WKWebViewConfiguration())
        webView.uiDelegate = self
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")      // no white flash before the page paints
        webView.loadHTMLString(page("Starting the desk…", "<p style='color:#AAB5C5'>Checking for updates, then starting its server on this Mac only.</p>"), baseURL: nil)

        window = NSWindow(contentRect: frame, styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Trading Desk"
        window.backgroundColor = NSColor(red: 0.063, green: 0.086, blue: 0.122, alpha: 1)   // the page's --bg
        window.minSize = NSSize(width: 420, height: 500)
        window.contentView = webView
        window.center()
        window.setFrameAutosaveName("TradingDeskWindow")        // reopens where you left it
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        waitForServer()
    }

    // The page is loaded once the server answers: up to a minute, since an update may take
    // up to 20 seconds on a slow connection before the page is built. Then it says why not.
    func waitForServer() {
        var request = URLRequest(url: readyURL)
        request.timeoutInterval = 1
        URLSession.shared.dataTask(with: request) { _, response, _ in
            DispatchQueue.main.async {
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    self.webView.load(URLRequest(url: deskURL))
                } else if self.tries < 240 && server.isRunning {
                    self.tries += 1
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { self.waitForServer() }
                } else {
                    self.webView.loadHTMLString(page("The desk's server did not start",
                        "<p style='color:#AAB5C5'>It runs from <code>\(deskDir)</code>. What it said is in "
                        + "<code>server.log</code> there. From a terminal, <code>./desk.sh</code> starts it the same way.</p>"),
                        baseURL: nil)
                }
            }
        }.resume()
    }

    // Links that leave the desk (SEC filings, sources) open in your normal browser.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, action.navigationType == .linkActivated,
           url.host != "127.0.0.1", url.host != "localhost" {
            NSWorkspace.shared.open(url)
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    // target="_blank" links: the same, rather than a second window.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    // The page's own questions ("Stop following KO?") need a real dialog: without these
    // a web view answers every confirm() with "no".
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }

    @objc func reloadPage() { webView.reload() }

    // Copy, paste and select-all in the page's fields need an Edit menu to exist.
    func buildMenu() {
        let main = NSMenu()
        func add(_ title: String, _ items: [NSMenuItem]) {
            let holder = NSMenuItem()
            let menu = NSMenu(title: title)
            items.forEach(menu.addItem)
            holder.submenu = menu
            main.addItem(holder)
        }
        func item(_ title: String, _ action: Selector?, _ key: String, target: AnyObject? = nil) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
            i.target = target
            return i
        }
        add("Trading Desk", [item("Hide Trading Desk", #selector(NSApplication.hide(_:)), "h"),
                             NSMenuItem.separator(),
                             item("Quit Trading Desk", #selector(NSApplication.terminate(_:)), "q")])
        add("Edit", [item("Undo", Selector(("undo:")), "z"), item("Redo", Selector(("redo:")), "Z"),
                     NSMenuItem.separator(),
                     item("Cut", #selector(NSText.cut(_:)), "x"), item("Copy", #selector(NSText.copy(_:)), "c"),
                     item("Paste", #selector(NSText.paste(_:)), "v"), item("Select All", #selector(NSText.selectAll(_:)), "a")])
        add("View", [item("Reload", #selector(reloadPage), "r", target: self)])
        add("Window", [item("Minimise", #selector(NSWindow.performMiniaturize(_:)), "m"),
                       item("Close", #selector(NSWindow.performClose(_:)), "w")])
        NSApp.mainMenu = main
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { return true }

    func applicationWillTerminate(_ notification: Notification) {
        if server.isRunning { server.terminate() }               // nothing is left running on the port
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
