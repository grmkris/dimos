// Media plane selector: picks the best pluggable video channel (jpeg floor / webrtc / webcodecs) by
// capability negotiation. The channel types live in types.ts; the impls in ./media/.
import type { MediaChannel, MediaKind, Status, VideoMeta } from "./types.ts";
import type { DimosClient } from "./client.ts";
import { createJpegTopicMedia } from "./media/jpegTopicMedia.ts";
import { createWebRtcMedia } from "./media/webRtcMedia.ts";
import { createWebCodecsMedia } from "./media/webCodecsMedia.ts";
import { createWebTransportWebCodecsMedia } from "./media/webTransportWebCodecsMedia.ts";

export interface MediaDeps {
  client: DimosClient; // for the jpeg-topic floor (subscribes via client.topic)
  gatewayUrl?: string; // the gateway /media WS (WebRTC signaling / WebCodecs chunks, e.g. ws://host:8080/media)
  wtUrl?: string; // WebTransport media endpoint (https://host:8443)
  certHashUrl?: string; // gateway /cert endpoint for the WT self-signed cert hash
  serverMedia?: readonly MediaKind[]; // what the gateway's media plane serves; floor = ["jpeg"]
  prefer?: MediaKind[]; // preference order; default ["webrtc","jpeg"]
}

function fallbackMedia(primary: MediaChannel, fallback: () => MediaChannel): MediaChannel {
  let active: MediaChannel = primary;
  let frameCb: ((id: string, frame: VideoFrame | ImageBitmap, m: VideoMeta) => void) | undefined;
  let streamCb: ((id: string, stream: MediaStream) => void) | undefined;
  let statusCb: ((s: Status) => void) | undefined;
  let latencyCb: ((id: string, ms: number) => void) | undefined;
  const wanted = new Set<string>();
  const wire = (ch: MediaChannel) => {
    if (frameCb) ch.onFrame(frameCb);
    if (streamCb) ch.onStream(streamCb);
    if (statusCb) ch.onStatus(statusCb);
    if (latencyCb) ch.onLatency?.(latencyCb);
  };
  wire(active);
  return {
    caps: primary.caps,
    label: `${primary.label ?? "primary"} -> webcodecs (h264/WS)`,
    async connect(): Promise<void> {
      try {
        await active.connect();
      } catch {
        active.close();
        active = fallback();
        wire(active);
        for (const t of wanted) active.subscribe(t);
        await active.connect();
      }
    },
    subscribe(streamId: string): void {
      wanted.add(streamId);
      active.subscribe(streamId);
    },
    unsubscribe(streamId: string): void {
      wanted.delete(streamId);
      active.unsubscribe(streamId);
    },
    onStream(cb: (id: string, stream: MediaStream) => void): void {
      streamCb = cb;
      active.onStream(cb);
    },
    onFrame(cb: (id: string, frame: VideoFrame | ImageBitmap, m: VideoMeta) => void): void {
      frameCb = cb;
      active.onFrame(cb);
    },
    onStatus(cb: (s: Status) => void): void {
      statusCb = cb;
      active.onStatus(cb);
    },
    onLatency(cb: (id: string, ms: number) => void): void {
      latencyCb = cb;
      active.onLatency?.(cb);
    },
    close(): void {
      active.close();
    },
  };
}

/** Pick the best path the server offers and the browser supports, in preference order; jpeg is the floor (always returns something). */
export function selectMediaChannel(d: MediaDeps): MediaChannel {
  const prefer = d.prefer ?? ["webrtc", "jpeg"];
  const offered = new Set<MediaKind>(d.serverMedia ?? ["jpeg"]);
  const jpeg = () => createJpegTopicMedia({ client: d.client }); // jpeg floor (no gatewayUrl)
  // Browser support per kind (webcodecs chunks ride the WS, so decoder types suffice).
  const supported: Record<MediaKind, boolean> = {
    webcodecs: "VideoDecoder" in globalThis && "EncodedVideoChunk" in globalThis,
    webrtc: "RTCPeerConnection" in globalThis,
    jpeg: true,
  };
  // webcodecs/webrtc need the /media URL, else they skip.
  const build: Record<MediaKind, () => MediaChannel | undefined> = {
    webcodecs: () => {
      const ws = d.gatewayUrl
        ? () => createWebCodecsMedia({ gatewayUrl: d.gatewayUrl! })
        : undefined;
      if (d.wtUrl && d.certHashUrl) {
        const wt = createWebTransportWebCodecsMedia({ wtUrl: d.wtUrl, certHashUrl: d.certHashUrl });
        return ws ? fallbackMedia(wt, ws) : wt;
      }
      return ws?.();
    },
    webrtc: () => d.gatewayUrl ? createWebRtcMedia({ gatewayUrl: d.gatewayUrl }) : undefined,
    jpeg,
  };
  for (const kind of prefer) {
    if (!offered.has(kind) || !supported[kind]) continue;
    const ch = build[kind]();
    if (ch) return ch;
  }
  return jpeg();
}
