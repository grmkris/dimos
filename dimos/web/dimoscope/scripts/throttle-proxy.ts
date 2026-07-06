// TCP throttle proxy: localhost:<listen> → localhost:<target>, capping server→client bytes at
// <mbit>. Token bucket with small chunks so backpressure propagates to the gateway (like a real
// LAN). Point the app at it with ?gw=localhost:<listen> to bench any transport under a bandwidth
// cap — loopback alone hides bandwidth problems (raw 720p rgb8 at 14 Hz is ~39 MB/s ≈ 315 Mbit).
// Usage:  deno task throttle [listenPort] [mbit] [targetPort]     (defaults: 8081 100 8080)
const LISTEN = Number(Deno.args[0] ?? 8081);
const MBIT = Number(Deno.args[1] ?? 100);
const TARGET = Number(Deno.args[2] ?? 8080);
const BYTES_PER_SEC = (MBIT * 1e6) / 8;
const TICK_MS = 10;
const PER_TICK = Math.max(1, Math.floor(BYTES_PER_SEC * (TICK_MS / 1000)));

async function pumpThrottled(from: Deno.Conn, to: Deno.Conn) {
  const buf = new Uint8Array(64 * 1024);
  let budget = PER_TICK;
  let last = performance.now();
  try {
    while (true) {
      const n = await from.read(buf);
      if (n === null) break;
      let off = 0;
      while (off < n) {
        const now = performance.now();
        budget = Math.min(PER_TICK * 4, budget + ((now - last) / 1000) * BYTES_PER_SEC);
        last = now;
        if (budget < 1) {
          await new Promise((r) => setTimeout(r, TICK_MS));
          continue;
        }
        const take = Math.min(n - off, Math.floor(budget));
        await writeAll(to, buf.subarray(off, off + take));
        off += take;
        budget -= take;
      }
    }
  } catch { /* peer closed */ }
  try {
    to.closeWrite();
  } catch { /* already closed */ }
}

async function pump(from: Deno.Conn, to: Deno.Conn) {
  const buf = new Uint8Array(64 * 1024);
  try {
    while (true) {
      const n = await from.read(buf);
      if (n === null) break;
      await writeAll(to, buf.subarray(0, n));
    }
  } catch { /* peer closed */ }
  try {
    to.closeWrite();
  } catch { /* already closed */ }
}

async function writeAll(c: Deno.Conn, b: Uint8Array) {
  let off = 0;
  while (off < b.length) off += await c.write(b.subarray(off));
}

const listener = Deno.listen({ port: LISTEN });
console.log(`throttle proxy :${LISTEN} → :${TARGET} at ${MBIT} Mbit/s downstream`);
for await (const client of listener) {
  (async () => {
    try {
      const server = await Deno.connect({ port: TARGET });
      pump(client, server); // upstream unthrottled
      pumpThrottled(server, client); // downstream capped
    } catch {
      client.close();
    }
  })();
}
