import Cocoa
import WebKit

// Draws icon.html, the icon's one source, to a 1024-pixel PNG with clear corners.
// build.sh --icon runs it, then scales the PNG with sips and packs it with iconutil.
//   render_icon <icon.html> <out.png>
let side = 1024
let args = CommandLine.arguments
if args.count != 3 {
    FileHandle.standardError.write("usage: render_icon <icon.html> <out.png>\n".data(using: .utf8)!)
    exit(2)
}
let source = URL(fileURLWithPath: args[1])
let output = URL(fileURLWithPath: args[2])

func fail(_ why: String) -> Never {
    FileHandle.standardError.write("render_icon: \(why)\n".data(using: .utf8)!)
    exit(1)
}

// Redrawn onto a 1024-pixel sRGB canvas, whatever the screen's scale and colour space,
// then checked before anything is written: a corner must be clear (a background drawn
// behind the page would put the icon on a square) and the middle solid (the page was
// drawn at all).
func save(_ drawn: CGImage) -> Never {
    guard let space = CGColorSpace(name: CGColorSpace.sRGB),
          let canvas = CGContext(data: nil, width: side, height: side, bitsPerComponent: 8, bytesPerRow: 0,
                                 space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
        fail("could not make a canvas")
    }
    canvas.interpolationQuality = .high
    canvas.draw(drawn, in: CGRect(x: 0, y: 0, width: side, height: side))
    guard let pixels = canvas.data?.assumingMemoryBound(to: UInt8.self) else { fail("the canvas is empty") }
    func alpha(_ x: Int, _ y: Int) -> UInt8 { return pixels[y * canvas.bytesPerRow + x * 4 + 3] }
    if alpha(0, 0) != 0 { fail("the corner is not clear: something drew a background behind the page") }
    if alpha(side / 2, side / 2) != 255 { fail("the middle is empty: the page was not drawn") }
    guard let image = canvas.makeImage(),
          let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else {
        fail("could not write the PNG")
    }
    do { try png.write(to: output) } catch { fail(error.localizedDescription) }
    exit(0)
}

class Renderer: NSObject, WKNavigationDelegate {
    let webView = WKWebView(frame: CGRect(x: 0, y: 0, width: side, height: side))
    let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: side, height: side),
                          styleMask: [.borderless], backing: .buffered, defer: false)    // never shown

    func start() {
        webView.setValue(false, forKey: "drawsBackground")      // the corners stay clear
        webView.navigationDelegate = self
        window.contentView = webView
        webView.loadFileURL(source, allowingReadAccessTo: source.deletingLastPathComponent())
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { fail("the page did not load in 20 seconds") }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        let config = WKSnapshotConfiguration()
        config.rect = CGRect(x: 0, y: 0, width: side, height: side)
        config.snapshotWidth = NSNumber(value: side)
        config.afterScreenUpdates = false                       // the window is never on screen to update
        webView.takeSnapshot(with: config) { image, error in
            guard let drawn = image?.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
                fail("no snapshot: \(error?.localizedDescription ?? "none was returned")")
            }
            save(drawn)
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        fail(error.localizedDescription)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        fail(error.localizedDescription)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)                            // no Dock icon while it draws
let renderer = Renderer()
renderer.start()
app.run()
