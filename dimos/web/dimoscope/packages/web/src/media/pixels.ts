// Raw sensor_msgs.Image pixel conversion, shared by the jpeg media channel and the react
// useTopicImage hook (one implementation — a swizzle fix must not fork between the two paths).
export interface RawImageLike {
  width: number;
  height: number;
  encoding: string;
  step?: number;
  data: Uint8Array;
}

/** Raw rgb8/bgr8/mono8/rgba8/bgra8 → RGBA ImageData (the universal, per-pixel fallback). */
export function rawToRGBA(img: RawImageLike): ImageData | null {
  const { width: w, height: h, data } = img;
  const enc = (img.encoding || "").toLowerCase();
  if (!w || !h || !data?.length) return null;
  const out = new Uint8ClampedArray(w * h * 4);
  const ch = enc === "mono8" || enc === "8uc1" ? 1 : enc === "rgba8" || enc === "bgra8" ? 4 : 3;
  const step = img.step && img.step >= w * ch ? img.step : w * ch;
  const bgr = enc === "bgr8" || enc === "bgra8";
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * step + x * ch;
      const o = (y * w + x) * 4;
      if (ch === 1) {
        const v = data[i];
        out[o] = v;
        out[o + 1] = v;
        out[o + 2] = v;
        out[o + 3] = 255;
      } else {
        out[o] = data[i + (bgr ? 2 : 0)];
        out[o + 1] = data[i + 1];
        out[o + 2] = data[i + (bgr ? 0 : 2)];
        out[o + 3] = ch === 4 ? data[i + 3] : 255;
      }
    }
  }
  return new ImageData(out, w, h);
}

/** rgb8/bgr8 → VideoFrame via one flat 3→4-byte stride copy (no per-pixel swizzle branch, no async
 *  bitmap hop — VideoPixelFormat has no packed-24-bit format, but BGRX/RGBX map both encodings).
 *  Returns null when unsupported (no VideoFrame, other encodings) — callers fall back to rawToRGBA. */
export function rawToVideoFrame(img: RawImageLike): VideoFrame | null {
  const { width: w, height: h, data } = img;
  const enc = (img.encoding || "").toLowerCase();
  if (!("VideoFrame" in globalThis) || !w || !h || !data?.length) return null;
  if (enc !== "rgb8" && enc !== "bgr8") return null;
  const step = img.step && img.step >= w * 3 ? img.step : w * 3;
  const out = new Uint8Array(w * h * 4);
  for (let y = 0, di = 0; y < h; y++) {
    for (let si = y * step, xe = si + w * 3; si < xe; si += 3, di += 4) {
      out[di] = data[si];
      out[di + 1] = data[si + 1];
      out[di + 2] = data[si + 2];
      out[di + 3] = 255;
    }
  }
  try {
    return new VideoFrame(out, {
      format: enc === "bgr8" ? "BGRX" : "RGBX",
      codedWidth: w,
      codedHeight: h,
      timestamp: performance.now() * 1000, // required; µs
    });
  } catch {
    return null; // fall through to the ImageData path
  }
}
