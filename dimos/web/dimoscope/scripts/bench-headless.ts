// Headless bench driver (Deno): launches a real Chromium with anti-throttle + WebRTC-friendly flags
// so the page is never background-throttled (the corruption that wrecks numbers when a real tab is
// occluded) and WebRTC uses real host ICE candidates. Navigates a dimoscope bench URL (run=1
// auto-runs), waits for "done ✓", prints the results table. Valid for WS / WebTransport / WebRTC.
//
// Usage:  deno run -A scripts/bench-headless.ts "<bench-url-with-run=1>"
// Chromium: set CHROME_BIN, else the newest Playwright-managed Chrome-for-Testing in the local cache.
import { chromium } from "npm:playwright-core@1.49.1";

const URL = Deno.args[0];
if (!URL) {
  console.error("usage: bench-headless.ts <url>");
  Deno.exit(1);
}

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
      .map((e) => e.name).sort().reverse(); // newest build first
    for (const v of versions) {
      for (const leaf of leaves) {
        const p = `${root}/${v}/${leaf}`;
        try {
          Deno.statSync(p);
          return p;
        } catch { /* try next candidate */ }
      }
    }
  } catch { /* no playwright cache */ }
  return null;
}

const EXE = Deno.env.get("CHROME_BIN") ?? findPlaywrightChrome();
if (!EXE) {
  console.error("no Chromium found — set CHROME_BIN or `npx playwright install chromium`");
  Deno.exit(1);
}

const browser = await chromium.launch({
  executablePath: EXE,
  headless: true,
  args: [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    // WebRtcHideLocalIpsWithMdns off: headless Chrome otherwise offers only mDNS `.local` ICE
    // candidates, which webrtc-rs (the sidecar's ICE stack) can't resolve → WebRTC limps at a few
    // Hz. Exposing real host IPs lets ICE pick a clean host pair. (No effect on WS/WT.)
    "--disable-features=CalculateNativeWinOcclusion,WebRtcHideLocalIpsWithMdns",
    "--force-webrtc-ip-handling-policy=default",
  ],
});
const page = await browser.newPage();
page.on("pageerror", (e: Error) => console.error("PAGEERR", e.message));
await page.goto(URL, { waitUntil: "domcontentloaded" });

try {
  await page.waitForFunction(() => /done\s*✓/.test(document.body.innerText), null, {
    timeout: 1200000,
    polling: 2000,
  });
} catch {
  console.error("TIMEOUT waiting for done — dumping partial");
}

const out = await page.evaluate(() => {
  const line = [...document.querySelectorAll("*")].map((e) => (e as HTMLElement).innerText || "")
    .find((t) => /clk\s*[+\-]/.test(t))?.match(/clk[^\n]*ms/)?.[0] ?? "";
  const chip = [...document.querySelectorAll(".badge")].map((b) => b.textContent).join(" | ");
  const table = document.querySelector("table.stats");
  const header = table
    ? [...table.querySelectorAll("thead th")].map((th) => th.textContent!.trim())
    : [];
  const rows = table
    ? [...table.querySelectorAll("tbody tr")].map((tr) =>
      [...tr.querySelectorAll("td")].map((td) => td.textContent!.trim())
    )
    : [];
  return { chip, line, header, rows };
});

console.log("CHIP:", out.chip);
console.log("CLK:", out.line);
console.log("H:", out.header.join(" | "));
for (const r of out.rows) console.log(r.join(" | "));
await browser.close();
