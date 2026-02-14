#!/usr/bin/env swift

import AppKit

// Usage: swift set_icon.swift <image-path> <target-path>

func setIcon(imagePath: String, targetPath: String) {
    guard let image = NSImage(contentsOfFile: imagePath) else {
        fputs("Error: Could not load image at \(imagePath)\n", stderr)
        exit(1)
    }

    let workspace = NSWorkspace.shared
    let result = workspace.setIcon(image, forFile: targetPath, options: [])

    if result {
        print("Successfully set icon for \(targetPath)")
        exit(0)
    } else {
        fputs("Error: Failed to set icon for \(targetPath)\n", stderr)
        exit(1)
    }
}

let args = CommandLine.arguments

if args.count != 3 {
    fputs("Usage: \(args[0]) <image-path> <target-path>\n", stderr)
    exit(1)
}

setIcon(imagePath: args[1], targetPath: args[2])
