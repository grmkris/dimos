/// <reference lib="dom" />
// WebCodecs over WebTransport: gateway encodes H.264, the Rust sidecar carries encoded chunks on a
// dedicated QUIC stream, and the browser decodes with VideoDecoder. Falls back at a higher layer.
import type { MediaCaps, MediaChannel, Status, VideoMeta } from "../types.ts";
import { readBulkStream } from "../transports/webTransport.ts";

interface Decoding {
  decoder: VideoDecoder;
  sawKey: boolean;
  meta: VideoMeta;
  ageEmaMs?: number;
}

export interface WebTransportWebCodecsMediaDeps {
  wtUrl: string;
  certHashUrl: string;
}

const HELLO_TIMEOUT_MS = 4000;

let h264Supported: Promise<boolean> | undefined;
const supportsH264 = (): Promise<boolean> =>
  h264Supported ??= VideoDecoder.isConfigSupported({ codec: "avc1.42E01F" })
    .then((s) => !!s.supported)
    .catch(() => false);

function hexToBytes(hex: string): Uint8Array {
  const h = hex.trim();
  const out = new Uint8Array(h.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(h.substr(i * 2, 2), 16);
  return out;
}

const safeClose = (d: VideoDecoder): void => {
  try {
    d.close();
  } catch {
    /* already closed */
  }
};

export const createWebTransportWebCodecsMedia = (
  deps: WebTransportWebCodecsMediaDeps,
): MediaChannel => {
  const caps: MediaCaps = { output: "frames", codec: "h264" };
  let wt: WebTransport | undefined;
  let ctlWriter: WritableStreamDefaultWriter<Uint8Array> | undefined;
  let connecting: Promise<void> | undefined;
  const wanted = new Set<string>();
  const decoders = new Map<string, Decoding>();
  let frameCb: ((id: string, frame: VideoFrame | ImageBitmap, m: VideoMeta) => void) | undefined;
  let statusCb: ((s: Status) => void) | undefined;
  let latencyCb: ((id: string, ms: number) => void) | undefined;
  const enc = new TextEncoder();

  async function connect(): Promise<void> {
    if (connecting) return connecting;
    if (typeof WebTransport === "undefined") throw new Error("webtransport unsupported");
    if (!(await supportsH264())) throw new Error("h264 webcodecs unsupported in this browser");

    connecting = new Promise((resolve, reject) => {
      let settled = false;
      const settle = (fn: () => void): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        fn();
      };
      const timer = setTimeout(() => {
        wt?.close();
        settle(() => reject(new Error("wt media hello timeout")));
      }, HELLO_TIMEOUT_MS);

      (async () => {
        statusCb?.("connecting");
        const hashHex = await (await fetch(deps.certHashUrl)).text();
        wt = new WebTransport(deps.wtUrl, {
          serverCertificateHashes: [{
            algorithm: "sha-256",
            value: hexToBytes(hashHex) as BufferSource,
          }],
        });
        await wt.ready;
        const ctl = await wt.createBidirectionalStream();
        ctlWriter = ctl.writable.getWriter();
        readControl(ctl.readable.getReader(), (media) => {
          if (!media.includes("webcodecs")) {
            wt?.close();
            settle(() => reject(new Error("gateway media plane lacks webcodecs")));
            return;
          }
          statusCb?.("open");
          for (const t of wanted) send({ op: "media-start", topic: t });
          settle(resolve);
        }).catch((e) => settle(() => reject(e instanceof Error ? e : new Error(String(e)))));
        readStreams(wt.incomingUnidirectionalStreams).catch(() => {});
        send({ op: "list" });
        wt.closed.then(() => statusCb?.("closed")).catch(() => statusCb?.("closed"));
      })().catch((e) => settle(() => reject(e instanceof Error ? e : new Error(String(e)))));
    });
    return connecting;
  }

  async function readControl(
    reader: ReadableStreamDefaultReader<Uint8Array>,
    hello: (media: string[]) => void,
  ): Promise<void> {
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buf += dec.decode(value, { stream: true });
      let nl: number;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl);
        buf = buf.slice(nl + 1);
        if (!line.trim()) continue;
        try {
          const m = JSON.parse(line) as { op?: string; media?: string[] };
          if (m.op === "hello") hello(Array.isArray(m.media) ? m.media : []);
        } catch {
          /* ignore malformed control */
        }
      }
    }
  }

  async function readStreams(streams: ReadableStream<ReadableStream<Uint8Array>>): Promise<void> {
    const reader = streams.getReader();
    for (;;) {
      const { value: stream, done } = await reader.read();
      if (done) break;
      if (stream) readBulkStream(stream, onChunk).catch(() => {});
    }
  }

  function onChunk(buf: Uint8Array): void {
    if (buf.byteLength < 11) return;
    const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    const flags = dv.getUint8(0);
    const tsUs = Number(dv.getBigUint64(1));
    const topicLen = dv.getUint16(9);
    const topic = new TextDecoder().decode(buf.subarray(11, 11 + topicLen));
    const payload = buf.subarray(11 + topicLen);
    decodeChunk(topic, payload, (flags & 1) === 1, tsUs);
  }

  function configure(topic: string, codec = "avc1.42E01F"): void {
    const prev = decoders.get(topic);
    if (prev) safeClose(prev.decoder);
    const meta: VideoMeta = { width: 0, height: 0, fps: 0, codec };
    const decoder = new VideoDecoder({
      output: (frame: VideoFrame) => {
        meta.width = frame.displayWidth || frame.codedWidth;
        meta.height = frame.displayHeight || frame.codedHeight;
        const d = decoders.get(topic);
        if (d && latencyCb) {
          const age = Date.now() - frame.timestamp / 1000;
          d.ageEmaMs = d.ageEmaMs === undefined ? age : d.ageEmaMs + 0.3 * (age - d.ageEmaMs);
          latencyCb(topic, d.ageEmaMs);
        }
        frameCb?.(topic, frame, meta);
      },
      error: () => {
        // An errored VideoDecoder is CLOSED — every later decode() throws, so resetting sawKey
        // alone leaves the topic black forever. Rebuild the decoder and resync on the next IDR.
        queueMicrotask(() => {
          if (decoders.has(topic)) configure(topic, codec);
        });
      },
    });
    try {
      decoder.configure({ codec, optimizeForLatency: true });
    } catch {
      try {
        decoder.configure({ codec });
      } catch {
        return;
      }
    }
    decoders.set(topic, { decoder, sawKey: false, meta });
  }

  function decodeChunk(topic: string, data: Uint8Array, isKey: boolean, tsUs: number): void {
    const d = decoders.get(topic);
    if (!d) return;
    if (!d.sawKey && !isKey) return;
    d.sawKey = true;
    try {
      d.decoder.decode(
        new EncodedVideoChunk({ type: isKey ? "key" : "delta", timestamp: tsUs, data }),
      );
    } catch {
      d.sawKey = false;
    }
  }

  function send(obj: unknown): void {
    ctlWriter?.write(enc.encode(JSON.stringify(obj) + "\n")).catch(() => {});
  }

  function subscribe(streamId: string): void {
    wanted.add(streamId);
    configure(streamId);
    send({ op: "media-start", topic: streamId });
  }

  function unsubscribe(streamId: string): void {
    wanted.delete(streamId);
    send({ op: "media-stop", topic: streamId });
    const d = decoders.get(streamId);
    if (d) {
      safeClose(d.decoder);
      decoders.delete(streamId);
    }
  }

  function close(): void {
    for (const t of wanted) send({ op: "media-stop", topic: t });
    wanted.clear();
    for (const d of decoders.values()) safeClose(d.decoder);
    decoders.clear();
    wt?.close();
    connecting = undefined;
  }

  return {
    caps,
    label: "webcodecs (h264/WT)",
    connect,
    subscribe,
    unsubscribe,
    onStream() {},
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
