// gateway H.264-encodes the camera (PyAV libx264, Annex-B), streams raw NAL chunks over its
// WebSocket; browser hardware-decodes via WebCodecs; no ICE/SDP; falls back to jpeg when
// VideoDecoder unavailable.
//
// Wire (gateway → browser): a JSON {op:"video-config", topic, codec} when a sub starts, then binary
//   [u8 flags(bit0=keyframe)][u64 ts_us BE][u16 topic_len BE][topic utf8][H.264 Annex-B NAL]
import type { MediaCaps, MediaChannel, Status, VideoMeta } from "../types.ts";

interface Decoding {
  decoder: VideoDecoder;
  sawKey: boolean; // a decoder can only start on a keyframe
  meta: VideoMeta;
  ageEmaMs?: number; // smoothed encoder-stamp → decode age (same-host clocks)
}

export interface WebCodecsMediaDeps {
  gatewayUrl: string; // the gateway /media WS that streams H.264 chunks (e.g. ws://host:8080/media)
}

/** Close a decoder, swallowing the throw if it's already closed. */
const safeClose = (d: VideoDecoder): void => {
  try {
    d.close();
  } catch {
    /* already closed */
  }
};

// H.264 decode capability is a static property of the browser/OS — probe once per page, not per
// connect (reconnect storms would re-await the codec subsystem each time).
let h264Supported: Promise<boolean> | undefined;
const supportsH264 = (): Promise<boolean> =>
  h264Supported ??= VideoDecoder.isConfigSupported({ codec: "avc1.42E01F" })
    .then((s) => !!s.supported)
    .catch(() => false);

const HELLO_TIMEOUT_MS = 4000; // a gateway that accepts /media but never hellos must not hang connect

export const createWebCodecsMedia = (deps: WebCodecsMediaDeps): MediaChannel => {
  const { gatewayUrl } = deps;
  const caps: MediaCaps = { output: "frames", codec: "h264" };
  let ws: WebSocket | undefined;
  let connecting: Promise<void> | undefined; // single in-flight handshake — a 2nd connect() awaits it
  const decoders = new Map<string, Decoding>();
  const wanted = new Set<string>(); // (re)start these once the ws opens / reopens
  let frameCb: ((id: string, frame: VideoFrame | ImageBitmap, m: VideoMeta) => void) | undefined;
  let statusCb: ((s: Status) => void) | undefined;
  let latencyCb: ((id: string, ms: number) => void) | undefined;

  async function connect(): Promise<void> {
    // Share the in-flight handshake: an early `resolve()` for a 2nd caller while the hello is
    // still pending would report success for a channel that then fails its capability check.
    if (connecting) return connecting;
    // Honest support gate: `"VideoDecoder" in globalThis` is presence, not H.264 capability — a
    // failed configure() later would mean a black canvas with no fallback. Reject here instead, so
    // useVideo's connect-failure path falls through to the next media kind.
    if (!(await supportsH264())) throw new Error("h264 webcodecs unsupported in this browser");
    connecting = new Promise((resolve, reject) => {
      statusCb?.("connecting");
      const sock = new WebSocket(gatewayUrl);
      sock.binaryType = "arraybuffer";
      ws = sock;
      const timer = setTimeout(() => {
        sock.close();
        reject(new Error("webcodecs hello timeout"));
      }, HELLO_TIMEOUT_MS);
      // Resolve on the gateway hello, not on open: the hello advertises which media kinds this
      // gateway actually serves (a PyAV-less gateway accepts the WS but would never send video).
      sock.onopen = () => statusCb?.("open");
      sock.onmessage = (e) => {
        // One-shot hello gate, then hand the socket to the steady-state frame handler.
        const media = parseHello(e);
        if (media === undefined) return; // binary/other before the hello: ignore
        clearTimeout(timer);
        sock.onmessage = (e2) => onMessage(e2);
        if (media === null || media.includes("webcodecs")) {
          for (const t of wanted) send({ op: "webcodecs-start", topic: t });
          resolve();
        } else {
          sock.close();
          reject(new Error("gateway media plane lacks webcodecs"));
        }
      };
      sock.onerror = () => reject(new Error("webcodecs ws error"));
      sock.onclose = () => {
        clearTimeout(timer);
        statusCb?.("closed");
        connecting = undefined; // a fresh connect() after socket death starts a new handshake
        reject(new Error("webcodecs ws closed")); // no-op if already resolved
      };
    });
    return connecting;
  }

  /** The hello's media list; null = hello without one (older gateway); undefined = not a hello. */
  function parseHello(e: MessageEvent): (string[] | null) | undefined {
    if (typeof e.data !== "string") return undefined;
    try {
      const m = JSON.parse(e.data) as { op?: string; media?: string[] };
      if (m.op !== "hello") return undefined;
      return Array.isArray(m.media) ? m.media : null;
    } catch {
      return undefined;
    }
  }

  function onMessage(e: MessageEvent): void {
    if (typeof e.data === "string") {
      let m: { op?: string; topic?: string; codec?: string };
      try {
        m = JSON.parse(e.data);
      } catch {
        return;
      }
      if (m.op === "video-config" && m.topic) configure(m.topic, m.codec);
      return; // others: ignore (no data-plane on this socket)
    }
    const buf = e.data as ArrayBuffer;
    if (buf.byteLength < 11) return;
    const dv = new DataView(buf);
    const flags = dv.getUint8(0);
    const tsUs = Number(dv.getBigUint64(1));
    const topicLen = dv.getUint16(9);
    const topic = new TextDecoder().decode(new Uint8Array(buf, 11, topicLen));
    const payload = new Uint8Array(buf, 11 + topicLen);
    decodeChunk(topic, payload, (flags & 1) === 1, tsUs);
  }

  function configure(topic: string, codec?: string): void {
    const c = codec || "avc1.42E01F";
    const prev = decoders.get(topic);
    if (prev) safeClose(prev.decoder);
    const meta: VideoMeta = { width: 0, height: 0, fps: 0, codec: c };
    const decoder = new VideoDecoder({
      output: (frame: VideoFrame) => {
        meta.width = frame.displayWidth || frame.codedWidth;
        meta.height = frame.displayHeight || frame.codedHeight;
        // frame.timestamp is the gateway's wall-clock encode stamp (ts_us) — age is meaningful
        // when browser and gateway clocks agree (localhost / NTP-synced hosts).
        const d = decoders.get(topic);
        if (d && latencyCb) {
          const age = Date.now() - frame.timestamp / 1000;
          d.ageEmaMs = d.ageEmaMs === undefined ? age : d.ageEmaMs + 0.3 * (age - d.ageEmaMs);
          latencyCb(topic, d.ageEmaMs);
        }
        frameCb?.(topic, frame, meta); // caller draws then closes the frame
      },
      error: () => {
        const d = decoders.get(topic);
        if (d) d.sawKey = false; // resync on the next keyframe
      },
    });
    // Don't force hardwareAcceleration:"prefer-hardware": some Chrome contexts configure() OK but then
    // error async with no frames; let the browser choose (still uses hw when available).
    try {
      decoder.configure({ codec: c, optimizeForLatency: true });
    } catch {
      try {
        decoder.configure({ codec: c }); // codec alone is enough for Annex-B in-band SPS/PPS
      } catch {
        return;
      }
    }
    decoders.set(topic, { decoder, sawKey: false, meta });
  }

  function decodeChunk(topic: string, data: Uint8Array, isKey: boolean, tsUs: number): void {
    const d = decoders.get(topic);
    if (!d) return; // config (→ decoder) always precedes chunks
    if (!d.sawKey && !isKey) return; // can't start mid-GOP
    d.sawKey = true;
    try {
      d.decoder.decode(
        new EncodedVideoChunk({ type: isKey ? "key" : "delta", timestamp: tsUs, data }),
      );
    } catch {
      d.sawKey = false; // wait for the next keyframe and resync
    }
  }

  function subscribe(streamId: string): void {
    wanted.add(streamId);
    if (ws?.readyState === WebSocket.OPEN) send({ op: "webcodecs-start", topic: streamId });
  }

  function unsubscribe(streamId: string): void {
    wanted.delete(streamId);
    send({ op: "webcodecs-stop", topic: streamId });
    const d = decoders.get(streamId);
    if (d) {
      safeClose(d.decoder);
      decoders.delete(streamId);
    }
  }

  function send(obj: unknown): void {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  function close(): void {
    for (const d of decoders.values()) safeClose(d.decoder);
    decoders.clear();
    wanted.clear();
    ws?.close();
  }

  return {
    caps,
    label: "webcodecs (h264)",
    connect,
    subscribe,
    unsubscribe,
    onStream() {}, // n/a — this channel is "frames"
    onFrame(cb: (id: string, frame: VideoFrame | ImageBitmap, m: VideoMeta) => void): void {
      frameCb = cb;
    },
    onStatus(cb: (s: Status) => void): void {
      statusCb = cb;
    },
    onLatency(cb: (id: string, ms: number) => void): void {
      latencyCb = cb;
    },
    close,
  };
};
