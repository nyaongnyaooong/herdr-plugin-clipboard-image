import AppKit
import ApplicationServices
import Foundation

let vKeyCode: Int64 = 9
var eventTap: CFMachPort?
var runLoopSource: CFRunLoopSource?
var lastPaste = Date.distantPast
var workspaceLabel = ""
var machineLabels: [String] = []
let stateDir = ProcessInfo.processInfo.environment["HERDR_PLUGIN_STATE_DIR"]
    ?? (NSHomeDirectory() as NSString).appendingPathComponent(".local/state/herdr/plugins/clipboard-image")
let logPath = (stateDir as NSString).appendingPathComponent("paste.log")

func log(_ message: String) {
    let formatter = DateFormatter()
    formatter.dateFormat = "HH:mm:ss"
    let line = "\(formatter.string(from: Date())) \(message)\n"
    let url = URL(fileURLWithPath: logPath)
    try? FileManager.default.createDirectory(at: URL(fileURLWithPath: stateDir), withIntermediateDirectories: true)
    if let data = line.data(using: .utf8) {
        if FileManager.default.fileExists(atPath: logPath),
           let handle = try? FileHandle(forWritingTo: url) {
            handle.seekToEndOfFile()
            handle.write(data)
            try? handle.close()
        } else {
            try? data.write(to: url)
        }
    }
}

func herdrBinary() -> String {
    ProcessInfo.processInfo.environment["HERDR_BIN_PATH"] ?? "herdr"
}

func runHerdr(_ args: [String]) -> Data {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    process.arguments = [herdrBinary()] + args
    let output = Pipe()
    process.standardOutput = output
    process.standardError = Pipe()
    do {
        try process.run()
        process.waitUntilExit()
    } catch {
        return Data()
    }
    return output.fileHandleForReading.readDataToEndOfFile()
}

func jsonObject(_ data: Data) -> Any? {
    guard let text = String(data: data, encoding: .utf8) else { return nil }
    guard let start = text.firstIndex(where: { $0 == "{" || $0 == "[" }) else { return nil }
    let slice = Data(text[start...].utf8)
    return try? JSONSerialization.jsonObject(with: slice)
}

func refreshLabels() {
    let listed = jsonObject(runHerdr(["workspace", "list"])) as? [String: Any]
    let result = listed?["result"] as? [String: Any]
    let workspaces = result?["workspaces"] as? [[String: Any]] ?? []
    var chosen = workspaces.first { ($0["focused"] as? Bool) == true }
    if chosen == nil {
        chosen = workspaces.first
    }
    workspaceLabel = chosen?["label"] as? String ?? ""

    let machinesData = runHerdr(["machine", "list", "--json"])
    var machines: [[String: Any]] = []
    if let object = jsonObject(machinesData) as? [String: Any] {
        let result = object["result"] as? [String: Any]
        machines = result?["machines"] as? [[String: Any]] ?? []
    } else if let object = jsonObject(machinesData) as? [[String: Any]] {
        machines = object
    }
    machineLabels = machines.compactMap { item in
        if (item["enabled"] as? Bool) == false { return nil }
        return item["label"] as? String
    }
}

func isTerminal(_ name: String) -> Bool {
    let lowered = name.lowercased()
    if lowered == "herdr" || lowered == "herdr.exe" { return true }
    if lowered.contains("ghostty") { return true }
    if lowered.contains("iterm") { return true }
    if lowered.contains("warp") { return true }
    if lowered.contains("wezterm") { return true }
    if lowered.contains("kitty") { return true }
    if lowered.contains("alacritty") { return true }
    if lowered.contains("hyper") { return true }
    if lowered == "terminal" || lowered.contains("terminal") { return true }
    return false
}

func titleMatches(_ title: String) -> Bool {
    if title.isEmpty { return false }
    if !workspaceLabel.isEmpty {
        if title == workspaceLabel || title.hasSuffix(": " + workspaceLabel) || title.hasSuffix(workspaceLabel) {
            return true
        }
    }
    for label in machineLabels where !label.isEmpty {
        if title == label || title.hasPrefix(label + ": ") {
            return true
        }
    }
    return false
}

func herdrPids(from text: String) -> [Int32] {
    var found: [Int32] = []
    for line in text.split(separator: "\n") {
        let parts = line.split(whereSeparator: { $0 == " " || $0 == "\t" })
        if parts.count < 3 { continue }
        guard let pid = Int32(parts[0]) else { continue }
        let command = parts.dropFirst(2).joined(separator: " ")
        let base = (command as NSString).lastPathComponent
        if base == "herdr" || base.hasPrefix("herdr ") || command.hasSuffix("/herdr") {
            found.append(pid)
        }
    }
    return found
}

func descendantHostsHerdr(_ ancestor: pid_t) -> Bool {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/bin/ps")
    process.arguments = ["-ax", "-o", "pid=,ppid=,command="]
    let output = Pipe()
    process.standardOutput = output
    process.standardError = Pipe()
    do {
        try process.run()
        process.waitUntilExit()
    } catch {
        return false
    }
    let text = String(data: output.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    var parents: [Int32: Int32] = [:]
    for line in text.split(separator: "\n") {
        let parts = line.split(whereSeparator: { $0 == " " || $0 == "\t" })
        if parts.count < 2 { continue }
        guard let pid = Int32(parts[0]), let ppid = Int32(parts[1]) else { continue }
        parents[pid] = ppid
    }
    for pid in herdrPids(from: text) {
        var current = pid
        var hops = 0
        while hops < 30 {
            if current == ancestor { return true }
            guard let parent = parents[current], parent != current, parent > 0 else { break }
            current = parent
            hops += 1
        }
    }
    return false
}

func focusedWindowTitle(pid: pid_t) -> String {
    let app = AXUIElementCreateApplication(pid)
    var window: CFTypeRef?
    let windowError = AXUIElementCopyAttributeValue(app, kAXFocusedWindowAttribute as CFString, &window)
    if windowError != .success || window == nil { return "" }
    let element = window as! AXUIElement
    var title: CFTypeRef?
    let titleError = AXUIElementCopyAttributeValue(element, kAXTitleAttribute as CFString, &title)
    if titleError != .success { return "" }
    return title as? String ?? ""
}

func frontmost() -> (name: String, pid: pid_t, title: String) {
    let app = NSWorkspace.shared.frontmostApplication
    let name = app?.localizedName ?? app?.executableURL?.lastPathComponent ?? ""
    let pid = app?.processIdentifier ?? 0
    if pid == 0 { return (name, pid, "") }
    return (name, pid, focusedWindowTitle(pid: pid))
}

func shouldIntercept(name: String, title: String, pid: pid_t) -> Bool {
    if !isTerminal(name) { return false }
    let lowered = name.lowercased()
    if lowered == "herdr" || lowered == "herdr.exe" { return true }
    if titleMatches(title) { return true }
    if title.isEmpty && descendantHostsHerdr(pid) { return true }
    return false
}

func stampName() -> String {
    let formatter = DateFormatter()
    formatter.dateFormat = "yyyyMMdd-HHmmss-SSS"
    return "clip-\(formatter.string(from: Date()))"
}

func writePNG(_ image: NSImage, to url: URL) -> Bool {
    guard let tiff = image.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let png = rep.representation(using: .png, properties: [:]) else { return false }
    do {
        try png.write(to: url)
        return true
    } catch {
        return false
    }
}

func imageSuffix(_ url: URL) -> Bool {
    let suffix = url.pathExtension.lowercased()
    if suffix == "png" { return true }
    if suffix == "jpg" || suffix == "jpeg" { return true }
    if suffix == "gif" || suffix == "webp" || suffix == "bmp" { return true }
    if suffix == "tif" || suffix == "tiff" { return true }
    return false
}

enum ClipboardKind {
    case empty
    case image(String)
    case file(String)
    case text(String)
}

func readClipboard(destDir: String, pasteboard: NSPasteboard = .general) -> ClipboardKind {
    try? FileManager.default.createDirectory(atPath: destDir, withIntermediateDirectories: true)
    if let urls = pasteboard.readObjects(forClasses: [NSURL.self], options: nil) as? [URL] {
        for url in urls where url.isFileURL && imageSuffix(url) {
            return .file(url.path)
        }
    }
    let stamp = stampName()
    let pngURL = URL(fileURLWithPath: destDir).appendingPathComponent("\(stamp).png")
    if let image = NSImage(pasteboard: pasteboard), writePNG(image, to: pngURL) {
        return .image(pngURL.path)
    }
    if let text = pasteboard.string(forType: .string), !text.isEmpty {
        return .text(text)
    }
    return .empty
}

func emit(_ kind: ClipboardKind) {
    if case .image(let path) = kind {
        print("image")
        print(path)
        return
    }
    if case .file(let path) = kind {
        print("file")
        print(path)
        return
    }
    if case .text(let text) = kind {
        print("text")
        print(text, terminator: "")
        if !text.hasSuffix("\n") { print("") }
        return
    }
    print("empty")
}

func pluginRoot() -> String {
    if let root = ProcessInfo.processInfo.environment["HERDR_PLUGIN_ROOT"], !root.isEmpty {
        return root
    }
    let source = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
    return source.deletingLastPathComponent().path
}

func pasteScript() -> String {
    pluginRoot() + "/scripts/paste_macos.py"
}

func stageDirectory() -> String {
    let temp = NSTemporaryDirectory()
    let dir = (temp as NSString).appendingPathComponent("herdr-clipboard-images")
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    return dir
}

func runPaste(path: String, app: String, title: String) {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
    process.arguments = [pasteScript(), path]
    var environment = ProcessInfo.processInfo.environment
    environment["HERDR_PASTE_FROM_WATCH"] = "1"
    environment["HERDR_PASTE_APP"] = app
    environment["HERDR_PASTE_TITLE"] = title
    environment.removeValue(forKey: "HERDR_PANE_ID")
    environment.removeValue(forKey: "HERDR_TAB_ID")
    process.environment = environment
    process.standardOutput = Pipe()
    process.standardError = Pipe()
    do {
        try process.run()
        process.waitUntilExit()
        log("paste exit=\(process.terminationStatus) app=\(app) title=\(title)")
    } catch {
        log("paste failed \(error)")
    }
}

func handleKey(_ event: CGEvent) -> Unmanaged<CGEvent>? {
    let keyCode = event.getIntegerValueField(.keyboardEventKeycode)
    let flags = event.flags
    if keyCode != vKeyCode { return Unmanaged.passUnretained(event) }
    if !flags.contains(.maskCommand) { return Unmanaged.passUnretained(event) }
    if flags.contains(.maskAlternate) || flags.contains(.maskControl) || flags.contains(.maskShift) {
        return Unmanaged.passUnretained(event)
    }
    let front = frontmost()
    if !shouldIntercept(name: front.name, title: front.title, pid: front.pid) {
        return Unmanaged.passUnretained(event)
    }
    let clip = readClipboard(destDir: stageDirectory())
    let path: String
    if case .image(let imagePath) = clip {
        path = imagePath
    } else if case .file(let filePath) = clip {
        path = filePath
    } else {
        return Unmanaged.passUnretained(event)
    }
    let now = Date()
    if now.timeIntervalSince(lastPaste) < 0.4 {
        return nil
    }
    lastPaste = now
    let app = front.name
    let title = front.title
    DispatchQueue.global(qos: .userInitiated).async {
        runPaste(path: path, app: app, title: title)
    }
    return nil
}

func eventCallback(proxy: CGEventTapProxy, type: CGEventType, event: CGEvent, userInfo: UnsafeMutableRawPointer?) -> Unmanaged<CGEvent>? {
    if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
        if let eventTap {
            CGEvent.tapEnable(tap: eventTap, enable: true)
        }
        return Unmanaged.passUnretained(event)
    }
    return handleKey(event)
}

func installTap() -> Bool {
    let mask = CGEventMask(1 << CGEventType.keyDown.rawValue)
    guard let tap = CGEvent.tapCreate(
        tap: .cgSessionEventTap,
        place: .headInsertEventTap,
        options: .defaultTap,
        eventsOfInterest: mask,
        callback: eventCallback,
        userInfo: nil
    ) else {
        return false
    }
    eventTap = tap
    runLoopSource = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
    if let runLoopSource {
        CFRunLoopAddSource(CFRunLoopGetMain(), runLoopSource, .commonModes)
    }
    CGEvent.tapEnable(tap: tap, enable: true)
    return true
}

func promptAccessibility() {
    let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
    let options = [key: true] as CFDictionary
    _ = AXIsProcessTrustedWithOptions(options)
}

func exportCommand() -> Int32 {
    _ = NSApplication.shared
    let dest = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : stageDirectory()
    emit(readClipboard(destDir: dest))
    return 0
}

func selfTest() -> Int32 {
    _ = NSApplication.shared
    let pasteboard = NSPasteboard(name: NSPasteboard.Name("herdr-clipboard-self-test"))
    let temp = NSTemporaryDirectory() + "herdr-clipboard-self-test"
    try? FileManager.default.removeItem(atPath: temp)
    try? FileManager.default.createDirectory(atPath: temp, withIntermediateDirectories: true)
    pasteboard.clearContents()
    pasteboard.setString("herdr-clipboard-text", forType: .string)
    let exported = readClipboard(destDir: temp, pasteboard: pasteboard)
    if case .text(let text) = exported, text == "herdr-clipboard-text" {
        print("ok")
        return 0
    }
    fputs("self-test failed to round-trip clipboard text\n", stderr)
    return 1
}

func watch() -> Int32 {
    _ = NSApplication.shared
    refreshLabels()
    Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { _ in
        refreshLabels()
    }
    if installTap() {
        log("watching Cmd+V label=\(workspaceLabel)")
        CFRunLoopRun()
        return 0
    }
    log("accessibility permission is required for Cmd+V")
    promptAccessibility()
    Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { timer in
        if installTap() {
            log("watching Cmd+V label=\(workspaceLabel)")
            timer.invalidate()
        }
    }
    CFRunLoopRun()
    return 0
}

let command = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "watch"
if command == "export" {
    exit(exportCommand())
}
if command == "self-test" {
    exit(selfTest())
}
exit(watch())
