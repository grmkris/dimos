// browser receives camera as a real WebRTC video track, encoded once server-side (aiortc),
// GPU-decoded by <video> (~20–40× less bandwidth than JPEG); signaling rides a thin WS to the
// gateway; non-trickle ICE (gather-then-send); currently ONE active camera per channel (multi-cam
// grid will share a PeerConnection).
import type { MediaCaps, MediaChannel, Status } from "../types.ts";

export interface WebRtcMediaDeps {
  gatewayUrl: string; // the gateway /media WS for WebRTC signaling (e.g. ws://host:8080/media)
}

export const createWebRtcMedia = (deps: WebRtcMediaDeps): MediaChannel => {
  const { gatewayUrl } = deps;
  const caps: MediaCaps = { output: "stream", codec: "h264" };
  let ws: WebSocket | undefined;
  let pc: RTCPeerConnection | undefined;
  let active: string | undefined; // the one subscribed camera topic
  let streamCb: ((id: string, s: MediaStream) => void) | undefined;
  let statusCb: ((s: Status) => void) | undefined;
  let latencyCb: ((id: string, ms: number) => void) | undefined;
  let statsTimer: ReturnType<typeof setInterval> | undefined;
  let answerTimer: ReturnType<typeof setTimeout> | undefined;

  const HELLO_TIMEOUT_MS = 4000;
  const ANSWER_TIMEOUT_MS = 4000;

  function connect(): Promise<void> {
    if (ws && ws.readyState <= WebSocket.OPEN) return Promise.resolve();
    return new Promise((resolve, reject) => {
      statusCb?.("connecting");
      const sock = new WebSocket(gatewayUrl);
      ws = sock;
      const timer = setTimeout(() => {
        sock.close();
        reject(new Error("webrtc hello timeout"));
      }, HELLO_TIMEOUT_MS);
      sock.onopen = () => statusCb?.("open");
      sock.onmessage = (e) => {
        const media = parseHello(e);
        if (media === undefined) return;
        clearTimeout(timer);
        sock.onmessage = (e2) => onSignal(e2);
        if (media === null || media.includes("webrtc")) resolve();
        else {
          sock.close();
          reject(new Error("gateway media plane lacks webrtc"));
        }
      };
      sock.onerror = () => {
        clearTimeout(timer);
        reject(new Error("webrtc signaling ws error"));
      };
      sock.onclose = () => {
        clearTimeout(timer);
        statusCb?.("closed");
      };
    });
  }

  /** The hello's media list; null = legacy hello without media; undefined = not a hello. */
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

  function onSignal(e: MessageEvent): void {
    if (typeof e.data !== "string") return; // ignore data-plane binary (we never subscribe topics)
    let m: any;
    try {
      m = JSON.parse(e.data);
    } catch {
      return;
    }
    if (m.op === "webrtc-answer" && pc) {
      clearTimeout(answerTimer);
      pc.setRemoteDescription({ type: "answer", sdp: m.sdp }).catch(() => {});
    }
  }

  function subscribe(streamId: string): void {
    if (active === streamId) return;
    teardownPc(); // single active camera — drop any prior one
    active = streamId;
    void negotiate(streamId);
  }

  async function negotiate(streamId: string): Promise<void> {
    const peer = new RTCPeerConnection();
    pc = peer;
    peer.addTransceiver("video", { direction: "recvonly" });
    peer.ontrack = (ev) => {
      if (active !== streamId) return;
      // Zero the receive-side jitter buffer: Chrome's adaptive target reads a low-fps source's
      // inter-frame gaps (200 ms at 5 fps) as jitter and holds several frame-intervals of playout
      // delay — even on loopback. Freshness over smoothness, same policy as the data plane.
      const rx = ev.receiver as RTCRtpReceiver & {
        jitterBufferTarget?: number | null; // ms (spec, Chrome ≥ M120)
        playoutDelayHint?: number; // seconds (legacy Chrome hint)
      };
      try {
        rx.jitterBufferTarget = 0;
      } catch { /* older browsers: hint below still applies */ }
      try {
        rx.playoutDelayHint = 0;
      } catch { /* non-Chromium: default buffering */ }
      streamCb?.(streamId, ev.streams[0]);
      watchJitterBuffer(peer, streamId);
    };
    peer.onconnectionstatechange = () => {
      if (peer.connectionState === "failed" || peer.connectionState === "closed") {
        statusCb?.("closed");
      }
    };
    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    await iceComplete(peer);
    send({ op: "webrtc-offer", sdp: peer.localDescription?.sdp, topic: streamId });
    answerTimer = setTimeout(() => {
      if (pc === peer) {
        statusCb?.("closed");
        teardownPc();
      }
    }, ANSWER_TIMEOUT_MS);
  }

  /** Non-trickle: resolve once ICE candidate gathering finishes (instant on localhost). */
  function iceComplete(peer: RTCPeerConnection): Promise<void> {
    if (peer.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
      const check = () => {
        if (peer.iceGatheringState === "complete") {
          peer.removeEventListener("icegatheringstatechange", check);
          resolve();
        }
      };
      peer.addEventListener("icegatheringstatechange", check);
    });
  }

  /** ~1 Hz poll of the measured jitter-buffer playout delay (avg ms per emitted frame over the
   *  last interval) — the number the receiver knobs above are meant to drive toward ~0. */
  function watchJitterBuffer(peer: RTCPeerConnection, streamId: string): void {
    clearInterval(statsTimer);
    let prevDelay = 0;
    let prevCount = 0;
    statsTimer = setInterval(async () => {
      if (pc !== peer || active !== streamId) return clearInterval(statsTimer);
      const stats = await peer.getStats().catch(() => undefined);
      if (!stats) return;
      for (const s of stats.values()) {
        const st = s as {
          type: string;
          kind?: string;
          jitterBufferDelay?: number;
          jitterBufferEmittedCount?: number;
        };
        if (st.type !== "inbound-rtp" || st.kind !== "video") continue;
        const d = st.jitterBufferDelay ?? 0; // cumulative seconds
        const n = st.jitterBufferEmittedCount ?? 0;
        if (n > prevCount) {
          latencyCb?.(streamId, ((d - prevDelay) / (n - prevCount)) * 1000);
        }
        prevDelay = d;
        prevCount = n;
      }
    }, 1000);
  }

  function unsubscribe(streamId: string): void {
    if (active !== streamId) return;
    send({ op: "webrtc-stop", topic: streamId });
    teardownPc();
    active = undefined;
  }

  function teardownPc(): void {
    clearInterval(statsTimer);
    clearTimeout(answerTimer);
    pc?.close();
    pc = undefined;
  }
  function send(obj: unknown): void {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  function close(): void {
    teardownPc();
    ws?.close();
    active = undefined;
  }

  return {
    caps,
    label: "webrtc (aiortc gateway)",
    connect,
    subscribe,
    unsubscribe,
    onStream(cb: (id: string, s: MediaStream) => void): void {
      streamCb = cb;
    },
    onFrame() {}, // n/a — this channel is "stream"
    onStatus(cb: (s: Status) => void): void {
      statusCb = cb;
    },
    onLatency(cb: (id: string, ms: number) => void): void {
      latencyCb = cb;
    },
    close,
  };
};
