// jpeg is the universal media floor — the Image-topic path repackaged as a MediaChannel so the app
// consumes video uniformly; needs no media gateway; works on all browsers/transports. When the
// gateway's image plane republishes a `<topic>_jpeg` transcode (~100 KB vs ~2.8 MB raw), this
// channel rides that sibling instead — the caller keeps addressing the raw topic name.
import type { MediaCaps, MediaChannel, Status, VideoMeta } from "../types.ts";
import type { DimosClient } from "../client.ts";
import { rawToRGBA, rawToVideoFrame } from "./pixels.ts";

export interface JpegTopicMediaDeps {
  client: DimosClient; // for the jpeg-topic floor (subscribes via client.topic)
}

interface ImageMsg {
  width: number;
  height: number;
  encoding: string;
  is_bigendian?: number;
  step?: number;
  data: Uint8Array;
}

/** Decode a sensor_msgs.Image (jpeg or raw) to a VideoFrame/ImageBitmap. Rejects on unsupported/empty. */
function decodeImage(img: ImageMsg): Promise<VideoFrame | ImageBitmap> {
  const enc = (img.encoding || "").toLowerCase();
  if (enc === "jpeg" || enc === "jpg") {
    return createImageBitmap(new Blob([img.data as BlobPart], { type: "image/jpeg" }));
  }
  const vf = rawToVideoFrame(img);
  if (vf) return Promise.resolve(vf);
  const id = rawToRGBA(img);
  if (!id) return Promise.reject(new Error(`unsupported image encoding: ${img.encoding}`));
  return createImageBitmap(id);
}

export const createJpegTopicMedia = (deps: JpegTopicMediaDeps): MediaChannel => {
  const { client } = deps;
  const caps: MediaCaps = { output: "frames", codec: "jpeg" };
  const subs = new Map<string, () => void>(); // streamId → teardown (wire sub + discovery watch)
  let frameCb: ((id: string, f: VideoFrame | ImageBitmap, m: VideoMeta) => void) | undefined;
  let statusCb: ((s: Status) => void) | undefined;
  let latencyCb: ((id: string, ms: number) => void) | undefined;

  function connect(): Promise<void> {
    statusCb?.("open"); // rides the existing client connection — nothing to open
    return Promise.resolve();
  }

  function subscribe(streamId: string): void {
    if (subs.has(streamId)) return;
    // Freshest-wins decode pump: keep only the newest message and never run two decodes at once —
    // an async decode queue is unbounded latency (and out-of-order frames) the moment decoding is
    // slower than delivery. A slow machine drops frames; it never falls behind.
    let pending: { img: ImageMsg; recvTs: number; hopMs?: number } | null = null;
    let busy = false;
    let ageEma: number | undefined;
    const pump = (): void => {
      if (busy || !pending) return;
      const { img, recvTs, hopMs } = pending;
      pending = null;
      busy = true;
      decodeImage(img)
        .then((frame) => {
          if (latencyCb) {
            // Age at draw = now − gateway send stamp (recvTs − transport hop); falls back to
            // decode time alone when the transport carries no hop measurement.
            const age = Date.now() - recvTs + (hopMs ?? 0);
            ageEma = ageEma === undefined ? age : ageEma + 0.3 * (age - ageEma);
            latencyCb(streamId, ageEma);
          }
          frameCb?.(streamId, frame, {
            width: img.width,
            height: img.height,
            fps: 0,
            codec: img.encoding,
          });
        })
        .catch(() => {})
        .finally(() => {
          busy = false;
          pump(); // drain whatever arrived while decoding (always the newest)
        });
    };

    // Ride the gateway image plane's `<topic>_jpeg` transcode when available — same frames, ~40×
    // fewer bytes. The sibling appears in discovery only after the plane sees its first frame, so
    // watch topics and switch the wire subscription when it shows up (else a client that
    // subscribes early would stay pinned to the raw firehose for the whole session).
    const sibling = streamId + "_jpeg";
    const wireSub = (name: string) =>
      client.topic(name).subscribeLatest((raw) => {
        pending = { img: raw.data as ImageMsg, recvTs: raw.meta.recvTs, hopMs: raw.meta.latencyMs };
        pump();
      });
    const hasSibling = () => client.listTopics().some((t) => t.topic === sibling);
    let sub = wireSub(hasSibling() ? sibling : streamId);
    let unwatch: (() => void) | undefined;
    if (!hasSibling() && streamId !== sibling) {
      unwatch = client.onTopics(() => {
        if (!hasSibling()) return;
        unwatch?.();
        unwatch = undefined;
        sub.unsubscribe(); // swap the wire to the transcode; frames keep reporting as streamId
        sub = wireSub(sibling);
      });
    }
    subs.set(streamId, () => {
      unwatch?.();
      sub.unsubscribe();
    });
  }

  function unsubscribe(streamId: string): void {
    subs.get(streamId)?.();
    subs.delete(streamId);
  }

  function close(): void {
    for (const teardown of subs.values()) teardown();
    subs.clear();
    statusCb?.("closed");
  }

  return {
    caps,
    label: "jpeg (Image topic)",
    connect,
    subscribe,
    unsubscribe,
    onStream() {}, // n/a — this channel is "frames"
    onFrame(cb: (id: string, f: VideoFrame | ImageBitmap, m: VideoMeta) => void): void {
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
