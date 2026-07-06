// Live camera via useVideo — WebRTC/WebCodecs <video>/<canvas> when available, else the JPEG Image-topic floor; auto-detects the topic.
import { type CSSProperties, useState } from "react";
import type { MediaMode, TopicInfo } from "@dimos/react";
import { useTopics, useVideo } from "../dimos";

// Playout buffer depth when "smooth" is on (?smooth=<ms> overrides). 150 ms rides out encoder and
// wire jitter at a latency cost that still feels live; 0 = paint-on-arrival (the teleop default).
const SMOOTH_MS = Number(new URLSearchParams(location.search).get("smooth") ?? "") || 150;

function pickImage(topics: TopicInfo[]): string | null {
  // Raw names only — the jpeg media channel swaps to a `<topic>_jpeg` transcode itself when the
  // gateway publishes one, and the stream channels (webcodecs/webrtc) must encode from the source.
  const prefer = ["/color_image", "/camera/image_raw", "/image", "/cam/rgb"];
  for (const p of prefer) if (topics.find((t) => t.topic === p)) return p;
  const raw = topics.find((t) => t.type === "sensor_msgs.Image" && !t.topic.endsWith("_jpeg"));
  return raw?.topic ?? topics.find((t) => t.type === "sensor_msgs.Image")?.topic ?? null;
}

export function CameraView({ mode, primary }: { mode?: MediaMode; primary?: boolean }) {
  const topics = useTopics();
  const topic = pickImage(topics);
  const [smooth, setSmooth] = useState(new URLSearchParams(location.search).has("smooth"));
  const { kind, videoRef, canvasRef, label, active, requested, latencyMs } = useVideo(topic, {
    mode,
    smoothMs: smooth ? SMOOTH_MS : 0,
  });

  const fellBack = requested && requested !== "auto" && active !== requested;

  // Fullscreen the media element itself, not a CSS overlay — the overlay's stacking context would break the live stream.
  const fullscreen = () => {
    const el = (kind === "stream" ? videoRef.current : canvasRef.current) as HTMLElement | null;
    el?.requestFullscreen?.().catch(() => {});
  };

  const style: CSSProperties = primary
    ? {
      width: "100%",
      height: "auto",
      maxHeight: "calc(100vh - 130px)",
      objectFit: "contain",
      display: "block",
      borderRadius: 8,
      background: "#000",
    }
    : {
      width: "100%",
      aspectRatio: "16 / 9",
      objectFit: "cover",
      display: "block",
      borderRadius: 8,
      background: "#000",
    };

  return (
    <div
      className="panel"
      style={primary ? { display: "flex", flexDirection: "column" } : undefined}
    >
      <div className="panel-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          Camera · {topic ?? "no sensor_msgs.Image"}
          {label ? ` · ${label}` : ""}
          {latencyMs != null ? ` · ${kind === "stream" ? "jb" : "age"} ${latencyMs} ms` : ""}
          {fellBack && (
            <span style={{ color: "var(--accent)" }}>
              {" "}
              · ⚠ wanted {requested}, using {active}
            </span>
          )}
        </span>
        {kind === "frames" && active === "webcodecs" && (
          <button
            className={smooth ? "tab active" : "tab"}
            onClick={() => setSmooth((s) => !s)}
            title={`smooth playout: buffer ${SMOOTH_MS} ms and paint at capture cadence — steady video for replay review; off = lowest latency for teleop`}
            style={{ padding: "2px 8px" }}
          >
            {smooth ? `smooth ${SMOOTH_MS}ms` : "smooth"}
          </button>
        )}
        <button
          className="tab"
          onClick={fullscreen}
          title="fullscreen (Esc to exit)"
          style={{ padding: "2px 8px" }}
        >
          ⛶ fullscreen
        </button>
      </div>
      {kind === "stream"
        ? <video ref={videoRef} autoPlay playsInline muted style={style} />
        : <canvas ref={canvasRef} style={style} />}
    </div>
  );
}
