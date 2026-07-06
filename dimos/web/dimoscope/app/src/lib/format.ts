// Shared display formatting. One auto-scale rule for bandwidth (≥1 MB/s → MB/s, else kB/s) so every
// panel reads the same at the same rate; two shapes because chips want one label while metric cells
// style the number and unit separately.

/** Bandwidth as one label; blank below 1 kB/s so idle chips stay quiet. */
export function fmtBw(bps?: number): string {
  if (!bps) return "";
  const kb = bps / 1000;
  return kb >= 1000 ? `${(kb / 1000).toFixed(1)} MB/s` : kb >= 1 ? `${kb.toFixed(0)} kB/s` : "";
}

/** Bandwidth split into number + unit for styled metric rendering; "—" when there is no signal. */
export function bwParts(bps?: number): { n: string; u: string } {
  if (!bps) return { n: "—", u: "" };
  const kb = bps / 1000;
  return kb >= 1000 ? { n: (kb / 1000).toFixed(1), u: "MB/s" } : { n: kb.toFixed(0), u: "kB/s" };
}
