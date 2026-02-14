#!/usr/bin/env swift

import Cocoa
import WebKit

// Usage: swift svg2png.swift <input.svg> <output.png> <width>

class SVGRenderer: NSObject, WKNavigationDelegate {
    let webView: WKWebView
    let inputURL: URL
    let outputURL: URL
    let width: Int
    
    init(inputPath: String, outputPath: String, width: Int) {
        self.inputURL = URL(fileURLWithPath: inputPath)
        self.outputURL = URL(fileURLWithPath: outputPath)
        self.width = width
        
        let config = WKWebViewConfiguration()
        self.webView = WKWebView(frame: CGRect(x: 0, y: 0, width: width, height: width), configuration: config)
        
        // Essential for transparency
        self.webView.setValue(false, forKey: "drawsBackground")
        
        super.init()
        self.webView.navigationDelegate = self
    }
    
    func start() {
        // Load the SVG content
        webView.loadFileURL(inputURL, allowingReadAccessTo: inputURL.deletingLastPathComponent())
        CFRunLoopRun()
    }
    
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // Wait a bit for rendering to complete
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
            self.takeSnapshot()
        }
    }
    
    func takeSnapshot() {
        let config = WKSnapshotConfiguration()
        // We want the snapshot to be transparent
        
        webView.takeSnapshot(with: config) { image, error in
            guard let image = image, error == nil else {
                fputs("Error taking snapshot: \(String(describing: error))\n", stderr)
                exit(1)
            }
            
            if let tiffData = image.tiffRepresentation,
               let bitmap = NSBitmapImageRep(data: tiffData),
               let pngData = bitmap.representation(using: .png, properties: [:]) {
                
                do {
                    try pngData.write(to: self.outputURL)
                    // print("Generated \(self.outputURL.lastPathComponent)")
                    exit(0)
                } catch {
                    fputs("Error writing PNG: \(error)\n", stderr)
                    exit(1)
                }
            } else {
                fputs("Error converting image to PNG\n", stderr)
                exit(1)
            }
        }
    }
}

let args = CommandLine.arguments

if args.count != 4 {
    fputs("Usage: \(args[0]) <input.svg> <output.png> <width>\n", stderr)
    exit(1)
}

let inputPath = args[1]
let outputPath = args[2]
guard let width = Int(args[3]) else {
    fputs("Error: Invalid width\n", stderr)
    exit(1)
}

let renderer = SVGRenderer(inputPath: inputPath, outputPath: outputPath, width: width)
renderer.start()
