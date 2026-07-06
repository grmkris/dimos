// Headless video-lag bench for dimoscope CameraView. Per media mode (jpeg/webcodecs/webrtc/auto):
// draw fps (canvas drawImage / video rVFC), delivered fps + wire MB/s (WS counters), display
// latency (the CameraView header's live age/jb readout), decode backlog, main-thread longtasks.
// Chromium flags copied from scripts/bench-headless.ts (anti-throttle + real host ICE).
//
// Usage:  deno task bench-video [url] [secondsPerMode] [mode,mode,...]
//         deno task bench-video "http://localhost:8080/?transport=ws&gw=localhost:8081" 45 jpeg,webcodecs,webrtc,auto
// A per-mode screenshot of the camera element lands in $SHOT_DIR (default cwd).
// Pair with scripts/throttle-proxy.ts to reproduce a bandwidth-capped LAN (loopback hides the
// raw-camera problem: 720p rgb8 at 14 Hz is ~39 MB/s ≈ 315 Mbit).
import { chromium } from "npm:playwright-core@1.49.1";

const URL_ = Deno.args[0] ?? "http://localhost:8080/?transport=ws";
const SECS = Number(Deno.args[1] ?? 60);
const MODES = (Deno.args[2] ?? "jpeg,webcodecs,webrtc,auto").split(",");

function findPlaywrightChrome(): string | null {
  const home = Deno.env.get("HOME") ?? "";
  const root = Deno.build.os === "darwin"
    ? `${home}/Library/Caches/ms-playwright`
    : `${home}/.cache/ms-playwright`;
  const leaves = Deno.build.os === "darwin"
    ? [
      "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
      "chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    ]
    : ["chrome-linux/chrome"];
  try {
    const versions = [...Deno.readDirSync(root)]
      .filter((e) => e.isDirectory && e.name.startsWith("chromium-"))
      .map((e) => e.name).sort().reverse();
    for (const v of versions) {
      for (const leaf of leaves) {
        const p = `${root}/${v}/${leaf}`;
        try {
          Deno.statSync(p);
          return p;
        } catch { /* next */ }
      }
    }
  } catch { /* no cache */ }
  return null;
}

const EXE = Deno.env.get("CHROME_BIN") ?? findPlaywrightChrome();
if (!EXE) {
  console.error("no Chromium — set CHROME_BIN or npx playwright install chromium");
  Deno.exit(1);
}

const browser = await chromium.launch({
  executablePath: EXE,
  headless: true,
  args: [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=CalculateNativeWinOcclusion,WebRtcHideLocalIpsWithMdns",
    "--force-webrtc-ip-handling-policy=default",
  ],
});
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
page.on("pageerror", (e: Error) => console.error("PAGEERR", e.message));

await page.addInitScript(() => {
  // deno-lint-ignore no-explicit-any
  const g = globalThis as any;
  g.__vb = {
    draws: [] as number[], // camera-canvas drawImage timestamps
    vfc: [] as number[], // <video> requestVideoFrameCallback timestamps (webrtc)
    wsBytes: 0,
    wsMsgs: 0,
    bigMsgs: 0, // >1MB binary on /ws = raw camera frame
    mediaBytes: 0,
    mediaMsgs: 0,
    inFlight: 0,
    maxInFlight: 0, // createImageBitmap backlog
    longtasks: 0,
    longtaskMs: 0,
    reset() {
      this.draws.length = 0;
      this.vfc.length = 0;
      this.wsBytes =
        this.wsMsgs =
        this.bigMsgs =
        this.mediaBytes =
        this.mediaMsgs =
          0;
      this.maxInFlight = this.inFlight;
      this.longtasks = 0;
      this.longtaskMs = 0;
    },
  };
  const dI = CanvasRenderingContext2D.prototype.drawImage;
  CanvasRenderingContext2D.prototype.drawImage = function (...a: unknown[]) {
    // camera canvas is the only big 2d canvas the app draws images into
    if (this.canvas && this.canvas.width >= 320) {
      g.__vb.draws.push(performance.now());
      if (g.__vb.draws.length > 20000) g.__vb.draws.splice(0, 10000);
    }
    // deno-lint-ignore no-explicit-any
    return (dI as any).apply(this, a);
  };
  const OW = g.WebSocket;
  g.WebSocket = class extends OW {
    // deno-lint-ignore no-explicit-any
    constructor(url: any, ...r: any[]) {
      super(url, ...r);
      const isMedia = String(url).includes("/media");
      this.addEventListener("message", (e: MessageEvent) => {
        if (typeof e.data === "string") return;
        const n = (e.data as ArrayBuffer).byteLength ?? (e.data as Blob).size ?? 0;
        if (isMedia) {
          g.__vb.mediaBytes += n;
          g.__vb.mediaMsgs++;
        } else {
          g.__vb.wsBytes += n;
          g.__vb.wsMsgs++;
          if (n > 1e6) g.__vb.bigMsgs++;
        }
      });
    }
  };
  const cib = g.createImageBitmap.bind(globalThis);
  g.createImageBitmap = (...a: unknown[]) => {
    g.__vb.inFlight++;
    g.__vb.maxInFlight = Math.max(g.__vb.maxInFlight, g.__vb.inFlight);
    const p = cib(...a);
    p.finally(() => g.__vb.inFlight--);
    return p;
  };
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) {
        g.__vb.longtasks++;
        g.__vb.longtaskMs += e.duration;
      }
    }).observe({ type: "longtask", buffered: true });
  } catch { /* longtask unsupported */ }
  // webrtc <video> frame counter — poll for the element and attach rVFC once
  const attach = () => {
    const v = document.querySelector("video");
    // deno-lint-ignore no-explicit-any
    if (v && !(v as any).__vbHooked && "requestVideoFrameCallback" in v) {
      // deno-lint-ignore no-explicit-any
      (v as any).__vbHooked = true;
      const loop = () => {
        g.__vb.vfc.push(performance.now());
        if (g.__vb.vfc.length > 20000) g.__vb.vfc.splice(0, 10000);
        // deno-lint-ignore no-explicit-any
        (v as any).requestVideoFrameCallback(loop);
      };
      // deno-lint-ignore no-explicit-any
      (v as any).requestVideoFrameCallback(loop);
    }
  };
  setInterval(attach, 500);
});

await page.goto(URL_, { waitUntil: "domcontentloaded" });
await page.waitForFunction(
  () => document.querySelector(".status")?.textContent === "open",
  null,
  { timeout: 30000 },
);
// wait until the camera topic is discovered (header shows a topic, not "no sensor_msgs.Image")
await page.waitForFunction(
  () =>
    [...document.querySelectorAll(".panel-title")]
      .some((e) => /Camera · \//.test(e.textContent ?? "")),
  null,
  { timeout: 120000, polling: 1000 },
);
console.log("connected + camera topic discovered:", URL_);
await page.waitForTimeout(3000);

const header = () =>
  page.evaluate(() => {
    const el = [...document.querySelectorAll(".panel-title")]
      .find((e) => e.textContent?.startsWith("Camera"));
    return el?.textContent ?? "";
  });

interface Sample {
  t: number;
  drawFps: number;
  vfcFps: number;
  wsMBs: number;
  bigFps: number;
  mediaKBs: number;
  mediaFps: number;
  ageMs: number | null;
  label: string;
  inFlight: number;
  maxInFlight: number;
  longtasks: number;
  longtaskMs: number;
}

async function sampleWindow(winMs: number): Promise<Sample> {
  await page.evaluate(() => {
    // deno-lint-ignore no-explicit-any
    (globalThis as any).__vb.reset();
  });
  await page.waitForTimeout(winMs);
  const h = await header();
  const m = h.match(/(?:age|jb)\s+(\d+)\s*ms/);
  const s = await page.evaluate((win) => {
    // deno-lint-ignore no-explicit-any
    const vb = (globalThis as any).__vb;
    const now = performance.now();
    const inWin = (a: number[]) => a.filter((t) => now - t <= win).length;
    return {
      draws: inWin(vb.draws),
      vfc: inWin(vb.vfc),
      wsBytes: vb.wsBytes,
      bigMsgs: vb.bigMsgs,
      mediaBytes: vb.mediaBytes,
      mediaMsgs: vb.mediaMsgs,
      inFlight: vb.inFlight,
      maxInFlight: vb.maxInFlight,
      longtasks: vb.longtasks,
      longtaskMs: vb.longtaskMs,
    };
  }, winMs);
  const secs = winMs / 1000;
  return {
    t: Date.now(),
    drawFps: +(s.draws / secs).toFixed(1),
    vfcFps: +(s.vfc / secs).toFixed(1),
    wsMBs: +(s.wsBytes / secs / 1e6).toFixed(2),
    bigFps: +(s.bigMsgs / secs).toFixed(1),
    mediaKBs: +(s.mediaBytes / secs / 1e3).toFixed(1),
    mediaFps: +(s.mediaMsgs / secs).toFixed(1),
    ageMs: m ? Number(m[1]) : null,
    label: h.replace(/^Camera · /, ""),
    inFlight: s.inFlight,
    maxInFlight: s.maxInFlight,
    longtasks: s.longtasks,
    longtaskMs: Math.round(s.longtaskMs),
  };
}

const results: Record<string, Sample[]> = {};
for (const mode of MODES) {
  await page.selectOption("select[title*='camera media mode']", mode);
  console.log(`\n=== mode: ${mode} (${SECS}s) ===`);
  await page.waitForTimeout(3000); // channel negotiation
  const samples: Sample[] = [];
  const windows = Math.max(2, Math.floor(SECS / 15));
  for (let i = 0; i < windows; i++) {
    const s = await sampleWindow(15000);
    samples.push(s);
    console.log(
      `[${
        i + 1
      }/${windows}] draw ${s.drawFps} fps · video ${s.vfcFps} fps · ws ${s.wsMBs} MB/s (raw ${s.bigFps}/s) · media ${s.mediaKBs} kB/s (${s.mediaFps}/s) · lat ${
        s.ageMs ?? "—"
      } ms · backlog ${s.inFlight}(max ${s.maxInFlight}) · longtask ${s.longtasks}×/${s.longtaskMs}ms · ${s.label}`,
    );
  }
  results[mode] = samples;
  try {
    const el = page.locator(".center-col .panel canvas, .center-col .panel video").first();
    await el.screenshot({
      path: `${Deno.env.get("SHOT_DIR") ?? "."}/cam-${mode}.png`,
      timeout: 5000,
    });
  } catch { /* no visible media element */ }
}

console.log("\nJSON:", JSON.stringify(results));
await browser.close();
