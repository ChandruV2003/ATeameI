import AVFoundation
import CoreMedia
import Foundation
import ScreenCaptureKit

enum ArgError: Error, CustomStringConvertible {
    case missingValue(String)
    case invalidInt(String, String)

    var description: String {
        switch self {
        case .missingValue(let flag):
            return "Missing value for \(flag)"
        case .invalidInt(let flag, let value):
            return "Invalid integer for \(flag): \(value)"
        }
    }
}

struct Args {
    var sampleRate: Double = 16_000
    var channels: AVAudioChannelCount = 1
    var displayIndex: Int = 0
    var appBundleId: String? = nil
}

func parseArgs() throws -> Args {
    var out = Args()
    var i = 1
    let argv = CommandLine.arguments
    while i < argv.count {
        let a = argv[i]
        switch a {
        case "--sample-rate":
            i += 1
            guard i < argv.count else { throw ArgError.missingValue(a) }
            guard let v = Double(argv[i]) else { throw ArgError.invalidInt(a, argv[i]) }
            out.sampleRate = v
        case "--channels":
            i += 1
            guard i < argv.count else { throw ArgError.missingValue(a) }
            guard let v = Int(argv[i]) else { throw ArgError.invalidInt(a, argv[i]) }
            out.channels = AVAudioChannelCount(v)
        case "--display-index":
            i += 1
            guard i < argv.count else { throw ArgError.missingValue(a) }
            guard let v = Int(argv[i]) else { throw ArgError.invalidInt(a, argv[i]) }
            out.displayIndex = v
        case "--app-bundle-id":
            i += 1
            guard i < argv.count else { throw ArgError.missingValue(a) }
            out.appBundleId = argv[i]
        case "-h", "--help":
            print(
                """
                ateamei-sck-capture (ScreenCaptureKit audio capture)

                Captures system/app audio via ScreenCaptureKit and writes raw s16le PCM to stdout.

                Usage:
                  ateamei-sck-capture [--sample-rate 16000] [--channels 1] [--display-index 0] [--app-bundle-id com.microsoft.teams]

                Notes:
                  - Requires macOS Screen Recording permission for this binary.
                  - Pipe stdout into a consumer that expects s16le PCM.
                """
            )
            exit(0)
        default:
            // Unknown arg: ignore for forward-compat.
            break
        }
        i += 1
    }
    return out
}

final class AudioPipe: NSObject, SCStreamOutput {
    private let stdout = FileHandle.standardOutput
    private let dstFormat: AVAudioFormat
    private var converter: AVAudioConverter? = nil

    init(dstFormat: AVAudioFormat) {
        self.dstFormat = dstFormat
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio else { return }
        guard CMSampleBufferDataIsReady(sampleBuffer) else { return }

        do {
            guard let pcm = try self.sampleBufferToPCM(sampleBuffer: sampleBuffer) else { return }
            guard let converted = try self.convert(pcm) else { return }
            try self.writePCM(converted)
        } catch {
            // Best-effort: avoid crashing the capture pipeline; emit to stderr for debugging.
            FileHandle.standardError.write(Data("[ateamei-sck-capture] \(error)\n".utf8))
        }
    }

    private func sampleBufferToPCM(sampleBuffer: CMSampleBuffer) throws -> AVAudioPCMBuffer? {
        guard let fmtDesc = CMSampleBufferGetFormatDescription(sampleBuffer) else { return nil }
        guard let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(fmtDesc) else { return nil }
        var asbd = asbdPtr.pointee

        guard let srcFormat = AVAudioFormat(streamDescription: &asbd) else { return nil }
        let frameCount = AVAudioFrameCount(CMSampleBufferGetNumSamples(sampleBuffer))
        guard let buffer = AVAudioPCMBuffer(pcmFormat: srcFormat, frameCapacity: frameCount) else { return nil }
        buffer.frameLength = frameCount

        var sizeNeeded: Int = 0
        _ = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: &sizeNeeded,
            bufferListOut: nil,
            bufferListSize: 0,
            blockBufferAllocator: kCFAllocatorDefault,
            blockBufferMemoryAllocator: kCFAllocatorDefault,
            flags: 0,
            blockBufferOut: nil
        )

        let ablSize = max(sizeNeeded, MemoryLayout<AudioBufferList>.size)
        let raw = UnsafeMutableRawPointer.allocate(byteCount: ablSize, alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { raw.deallocate() }
        let audioBufferList = raw.bindMemory(to: AudioBufferList.self, capacity: 1)

        var blockBuffer: CMBlockBuffer?
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: &sizeNeeded,
            bufferListOut: audioBufferList,
            bufferListSize: ablSize,
            blockBufferAllocator: kCFAllocatorDefault,
            blockBufferMemoryAllocator: kCFAllocatorDefault,
            flags: 0,
            blockBufferOut: &blockBuffer
        )
        guard status == noErr else { return nil }

        // Copy audio buffers into AVAudioPCMBuffer
        let srcBuffers = UnsafeMutableAudioBufferListPointer(audioBufferList)
        let dstBuffers = UnsafeMutableAudioBufferListPointer(buffer.mutableAudioBufferList)
        for idx in 0..<min(srcBuffers.count, dstBuffers.count) {
            let srcBuf = srcBuffers[idx]
            let dstBuf = dstBuffers[idx]
            guard let srcData = srcBuf.mData, let dstData = dstBuf.mData else { continue }
            memcpy(dstData, srcData, Int(min(srcBuf.mDataByteSize, dstBuf.mDataByteSize)))
        }

        return buffer
    }

    private func convert(_ src: AVAudioPCMBuffer) throws -> AVAudioPCMBuffer? {
        if converter == nil || converter?.inputFormat != src.format {
            converter = AVAudioConverter(from: src.format, to: dstFormat)
        }
        guard let converter else { return nil }

        let ratio = dstFormat.sampleRate / src.format.sampleRate
        let outFrames = AVAudioFrameCount(Double(src.frameLength) * ratio + 0.5)
        guard let out = AVAudioPCMBuffer(pcmFormat: dstFormat, frameCapacity: max(outFrames, 1)) else { return nil }

        var err: NSError?
        let inputBlock: AVAudioConverterInputBlock = { _inNumPackets, outStatus in
            outStatus.pointee = .haveData
            return src
        }
        converter.convert(to: out, error: &err, withInputFrom: inputBlock)
        if let err { throw err }

        return out
    }

    private func writePCM(_ buffer: AVAudioPCMBuffer) throws {
        guard let channelData = buffer.int16ChannelData else { return }
        let frames = Int(buffer.frameLength)
        let channels = Int(buffer.format.channelCount)

        // Interleaved expected; if not interleaved, interleave manually.
        if buffer.format.isInterleaved {
            let byteCount = frames * channels * MemoryLayout<Int16>.size
            let ptr = UnsafeRawPointer(channelData[0])
            stdout.write(Data(bytes: ptr, count: byteCount))
        } else {
            var interleaved = [Int16](repeating: 0, count: frames * channels)
            for f in 0..<frames {
                for c in 0..<channels {
                    interleaved[f * channels + c] = channelData[c][f]
                }
            }
            stdout.write(interleaved.withUnsafeBytes { Data($0) })
        }
    }
}

@main
struct Main {
    static func main() async {
        do {
            let args = try parseArgs()

            // Destination format: s16le PCM on stdout.
            guard let dstFormat = AVAudioFormat(
                commonFormat: .pcmFormatInt16,
                sampleRate: args.sampleRate,
                channels: args.channels,
                interleaved: true
            ) else {
                throw NSError(domain: "ateamei", code: 1, userInfo: [NSLocalizedDescriptionKey: "Failed to create output AVAudioFormat"])
            }

            // Shareable content
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            guard args.displayIndex >= 0 && args.displayIndex < content.displays.count else {
                throw NSError(domain: "ateamei", code: 2, userInfo: [NSLocalizedDescriptionKey: "Invalid --display-index. Found \(content.displays.count) display(s)."])
            }
            let display = content.displays[args.displayIndex]

            // Build filter
            let filter: SCContentFilter
            if let bundleId = args.appBundleId {
                if let app = content.applications.first(where: { $0.bundleIdentifier == bundleId }) {
                    filter = SCContentFilter(display: display, including: [app], exceptingWindows: [])
                } else {
                    throw NSError(domain: "ateamei", code: 3, userInfo: [NSLocalizedDescriptionKey: "Application with bundle id not found: \(bundleId)"])
                }
            } else {
                filter = SCContentFilter(display: display, excludingWindows: [])
            }

            // Configure stream (audio-only)
            let cfg = SCStreamConfiguration()
            cfg.capturesAudio = true

            // Some versions require width/height even for audio-only capture; set minimal.
            cfg.width = 2
            cfg.height = 2

            let output = AudioPipe(dstFormat: dstFormat)
            let queue = DispatchQueue(label: "ateamei.sck.audio")
            let stream = SCStream(filter: filter, configuration: cfg, delegate: nil)
            try stream.addStreamOutput(output, type: .audio, sampleHandlerQueue: queue)

            try await stream.startCapture()

            // Keep running until killed.
            dispatchMain()
        } catch {
            FileHandle.standardError.write(Data("[ateamei-sck-capture] \(error)\n".utf8))
            exit(1)
        }
    }
}
