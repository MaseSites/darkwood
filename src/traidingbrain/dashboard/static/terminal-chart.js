/**
 * Der Chart des Darkwood Terminals -- mit umschaltbaren Ebenen.
 *
 * Jede Ebene zeichnet EINE Art von Marktstruktur, und jede kommt aus der
 * Analyse, nicht aus einer Erfindung im Browser:
 *
 *   ema        EMA 20 / 200, hier aus den Kerzen gerechnet
 *   fvg        Fair Value Gaps          (bands: fvg_bullish / fvg_bearish)
 *   zonen      Angebot und Nachfrage    (bands: supply / demand)
 *   liquiditaet gleiche Hochs/Tiefs     (bands: equal_highs / equal_lows)
 *              plus die Sweeps, die sie geholt haben (events: sweep_up/down)
 *   struktur   BOS und CHoCH            (events) und Swings (levels)
 *   trend      Trendlinien              (diagonals)
 *   volumen    Volumenprofil links      (aus den Kerzen)
 *   heatmap    ruhende Liquiditaet rechts (aus dem Orderbuch)
 *   positionen Einstieg / Stop / Ziel
 *
 * ZOOM UND VERSCHIEBEN: `visible` (wie viele Kerzen) und `end` (Index der
 * letzten sichtbaren). `end` darf GROESSER sein als die Kerzenzahl -- dann
 * entsteht rechts leerer Raum, wie bei TradingView, damit man die aktuelle
 * Kerze aus dem rechten Rand holen kann.
 */

const PAD = { left: 56, right: 92, top: 14, bottom: 26 };

export const EBENEN = {
  ema: "EMA 20 / 200",
  fvg: "Fair Value Gaps",
  zonen: "Angebot & Nachfrage",
  liquiditaet: "Liquidität (Pools & Sweeps)",
  struktur: "Struktur (BOS / CHoCH / Swings)",
  trend: "Trendlinien",
  volumen: "Volumenprofil",
  heatmap: "Orderbuch-Heatmap",
  positionen: "Positionen & Linien",
};

const BAND_EBENE = {
  fvg_bullish: "fvg", fvg_bearish: "fvg",
  supply: "zonen", demand: "zonen",
  order_block_bullish: "zonen", order_block_bearish: "zonen",
  equal_highs: "liquiditaet", equal_lows: "liquiditaet",
};
const BAND_FARBE = {
  fvg_bullish: "245,158,11", fvg_bearish: "245,158,11",
  supply: "248,113,113", demand: "52,211,153",
  order_block_bullish: "52,211,153", order_block_bearish: "248,113,113",
  equal_highs: "248,113,113", equal_lows: "96,165,250",
};

export function ema(values, n) {
  const k = 2 / (n + 1);
  const out = new Array(values.length).fill(null);
  let acc = null;
  for (let i = 0; i < values.length; i++) {
    acc = acc === null ? values[i] : values[i] * k + acc * (1 - k);
    if (i >= n - 1) out[i] = acc;
  }
  return out;
}

export function fmt(p) {
  const a = Math.abs(p ?? 0);
  if (a >= 1000) return (p ?? 0).toLocaleString("de-CH", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  if (a >= 10) return (p ?? 0).toFixed(2);
  return (p ?? 0).toFixed(4);
}

function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

export function drawTerminalChart(canvas, view, opts = {}) {
  const ratio = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  const candles = opts.candles ?? view?.candles ?? [];
  if (!W || !H || !candles.length) return null;
  if (canvas.width !== W * ratio || canvas.height !== H * ratio) { canvas.width = W * ratio; canvas.height = H * ratio; }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const an = opts.layers ?? {};
  const on = (k) => an[k] !== false;
  const c = {
    rule: cssVar("--rule"), ink: cssVar("--ink"), ink3: cssVar("--ink-3"), long: cssVar("--long"),
    short: cssVar("--short"), star: cssVar("--star"), mark: cssVar("--mark"), surface: cssVar("--surface"),
  };

  const pL = PAD.left, pR = W - PAD.right, pT = PAD.top, pB = H - PAD.bottom;
  const pW = pR - pL, pH = pB - pT;

  const total = candles.length;
  const visible = Math.max(20, Math.min(2000, Math.round(opts.visible ?? Math.max(60, Math.floor(pW / 7)))));
  // `end` darf ueber die Kerzenzahl hinausgehen -- der Ueberhang wird rechts
  // zu leerem Raum. Begrenzt auf ein Drittel des Fensters, damit der Chart
  // nicht ins Nichts geschoben werden kann.
  const maxEnd = total + Math.floor(visible / 3);
  const end = opts.end === null || opts.end === undefined ? total : Math.max(20, Math.min(maxEnd, Math.round(opts.end)));
  const offset = end - visible;
  const shown = candles.slice(Math.max(0, offset), Math.min(total, end));
  if (!shown.length) return null;
  const leer = Math.max(0, end - total);                 // leere Spalten rechts
  const spalten = shown.length + leer + Math.max(0, -offset);
  const vorn = Math.max(0, -offset);                     // leere Spalten links
  const formingIndex = opts.forming && end >= total ? vorn + shown.length - 1 : -1;

  let lo = Math.min(...shown.map((k) => k.low)), hi = Math.max(...shown.map((k) => k.high));
  if (on("positionen")) for (const line of opts.lines ?? []) {
    if (line.price > lo * 0.85 && line.price < hi * 1.15) { lo = Math.min(lo, line.price); hi = Math.max(hi, line.price); }
  }
  const padP = (hi - lo) * 0.06 || 1;
  lo -= padP; hi += padP;
  const span = hi - lo;
  const y = (p) => pB - ((p - lo) / span) * pH;
  const slot = pW / spalten;
  const x = (i) => pL + slot * (i + 0.5);                 // i = Spaltenindex
  const xk = (ki) => x(vorn + ki);                        // ki = Index in `shown`
  const body = Math.max(1, Math.floor(slot * 0.66));

  /* ---- Raster + Preisachse ---- */
  ctx.font = '11px ui-monospace, "Cascadia Mono", Menlo, monospace';
  ctx.textBaseline = "middle";
  const step = niceStep(span, 6);
  for (let p = Math.ceil(lo / step) * step; p <= hi; p += step) {
    const py = Math.round(y(p)) + 0.5;
    ctx.strokeStyle = c.rule; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pL, py); ctx.lineTo(pR, py); ctx.stroke();
    ctx.fillStyle = c.ink3; ctx.textAlign = "left";
    ctx.fillText(fmt(p), pR + 8, py);
  }

  /* ---- Zonen-Ebenen (fvg / zonen / liquiditaet) ---- */
  const lastClose = shown[shown.length - 1].close;
  for (const b of view?.bands ?? []) {
    const ebene = BAND_EBENE[b.kind];
    if (!ebene || !on(ebene)) continue;
    if (b.high < lo || b.low > hi) continue;
    const top = y(b.high), bottom = y(b.low);
    const rgb = BAND_FARBE[b.kind] ?? "124,138,163";
    ctx.fillStyle = `rgba(${rgb},0.16)`;
    ctx.fillRect(pL, top, pW, Math.max(2, bottom - top));
    if (ebene === "liquiditaet") {
      // Pools bekommen eine Kante und Sterne: die Zahl der Beruehrungen ist
      // das Mass, wie viel dort liegt.
      ctx.strokeStyle = `rgba(${rgb},0.55)`; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pL, top + 0.5); ctx.lineTo(pR, top + 0.5); ctx.stroke();
      drawStars(ctx, pR - 8, top + 10, naechsteBeruehrungen(view, b), c);
    }
  }

  /* ---- Trendlinien ---- */
  if (on("trend")) for (const g of view?.diagonals ?? []) {
    const i0 = indexFuerTs(candles, g.from_ts), i1 = indexFuerTs(candles, g.to_ts);
    if (i0 === null || i1 === null) continue;
    ctx.save();
    ctx.strokeStyle = g.kind === "support" ? "rgba(52,211,153,0.5)" : "rgba(248,113,113,0.5)";
    ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(xk(i0 - Math.max(0, offset)), y(g.from_price));
    ctx.lineTo(xk(i1 - Math.max(0, offset)), y(g.to_price)); ctx.stroke(); ctx.restore();
  }

  /* ---- Volumenprofil links ---- */
  if (on("volumen")) drawProfile(ctx, shown, { pL, pT, pB, y, lo, hi });

  /* ---- EMAs ---- */
  let emaWerte = null;
  if (on("ema")) {
    const closes = candles.map((k) => k.close);
    const e20 = ema(closes, 20), e200 = ema(closes, 200);
    const linie = (series, colour, dash) => {
      ctx.save(); ctx.setLineDash(dash); ctx.strokeStyle = colour; ctx.lineWidth = 1.2; ctx.beginPath();
      let started = false;
      for (let i = 0; i < shown.length; i++) {
        const v = series[Math.max(0, offset) + i]; if (v === null || v === undefined) continue;
        if (!started) { ctx.moveTo(xk(i), y(v)); started = true; } else ctx.lineTo(xk(i), y(v));
      }
      ctx.stroke(); ctx.restore();
    };
    linie(e200, c.short, [5, 4]);
    linie(e20, "#60a5fa", [3, 3]);
    emaWerte = { e20: e20[e20.length - 1], e200: e200[e200.length - 1] };
  }

  /* ---- Kerzen ---- */
  for (let i = 0; i < shown.length; i++) {
    const k = shown[i];
    const up = k.close >= k.open;
    const col = up ? c.long : c.short;
    const pxx = Math.round(xk(i));
    ctx.strokeStyle = col; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pxx + 0.5, y(k.high)); ctx.lineTo(pxx + 0.5, y(k.low)); ctx.stroke();
    const t = y(Math.max(k.open, k.close)), bt = y(Math.min(k.open, k.close));
    if (vorn + i === formingIndex) {
      ctx.strokeRect(pxx - body / 2 + 0.5, t + 0.5, Math.max(1, body - 1), Math.max(1, bt - t - 1));
    } else {
      ctx.fillStyle = col; ctx.fillRect(pxx - body / 2, t, body, Math.max(1, bt - t));
    }
  }

  /* ---- Struktur: BOS / CHoCH / Sweeps als Marken an der Kerze ---- */
  if (on("struktur") || on("liquiditaet")) {
    for (const e of view?.events ?? []) {
      const ki = (e.bar_index ?? -1) - Math.max(0, offset);
      if (ki < 0 || ki >= shown.length) continue;
      const istSweep = String(e.kind).startsWith("sweep");
      if (istSweep ? !on("liquiditaet") : !on("struktur")) continue;
      const k = shown[ki];
      const runter = e.kind === "sweep_down" || e.kind === "bos_down";
      const py = runter ? y(k.low) + 10 : y(k.high) - 10;
      ctx.fillStyle = istSweep ? c.star : (e.kind === "choch" ? c.mark : c.ink3);
      ctx.font = "9px ui-monospace, Menlo, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      const label = istSweep ? (runter ? "↓LQ" : "↑LQ") : (e.kind === "choch" ? "CHoCH" : "BOS");
      ctx.fillText(label, xk(ki), py);
    }
  }

  /* ---- Signalkerze ---- */
  if (opts.signalIndex !== undefined) {
    const ki = opts.signalIndex - Math.max(0, offset);
    if (ki >= 0 && ki < shown.length) {
      const k = shown[ki];
      ctx.strokeStyle = c.mark; ctx.lineWidth = 1.5;
      ctx.strokeRect(xk(ki) - body / 2 - 4, y(k.high) - 4, body + 8, y(k.low) - y(k.high) + 8);
    }
  }

  /* ---- Orderbuch-Heatmap am rechten Rand ---- */
  if (on("heatmap") && opts.book) drawHeatmap(ctx, opts.book, { pR, y, lo, hi, pH });

  /* ---- Positionslinien ---- */
  const boxes = [];
  if (on("positionen")) for (const line of opts.lines ?? []) {
    if (line.price < lo || line.price > hi) continue;
    const py = Math.round(y(line.price)) + 0.5;
    ctx.save(); ctx.setLineDash(line.dash ?? [6, 4]); ctx.strokeStyle = line.colour; ctx.lineWidth = line.width ?? 1.5;
    ctx.beginPath(); ctx.moveTo(pL, py); ctx.lineTo(pR, py); ctx.stroke(); ctx.restore();
    boxes.push({ y: py, label: line.label, colour: line.colour, id: line.id, closable: line.closable });
  }

  /* ---- Zeitachse ---- */
  ctx.fillStyle = c.ink3; ctx.textAlign = "center"; ctx.textBaseline = "top";
  const every = Math.max(1, Math.round(96 / slot));
  for (let i = 0; i < shown.length; i += every) {
    const d = new Date(shown[i].ts);
    ctx.fillText(`${d.getDate()}.${d.getMonth() + 1} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`, xk(i), pB + 6);
  }

  /* ---- Letzter Preis ---- */
  const lpy = Math.round(y(lastClose)) + 0.5;
  ctx.fillStyle = lastClose >= shown[shown.length - 1].open ? c.long : c.short;
  ctx.fillRect(pR + 2, lpy - 9, PAD.right - 6, 18);
  ctx.fillStyle = "#04120a"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
  ctx.fillText(fmt(lastClose), pR + 8, lpy);

  /* ---- Fadenkreuz ---- */
  if (opts.hover) {
    const hx = opts.hover.x, hy = opts.hover.y;
    ctx.save(); ctx.setLineDash([3, 3]); ctx.strokeStyle = c.ink3;
    ctx.beginPath(); ctx.moveTo(hx + 0.5, pT); ctx.lineTo(hx + 0.5, pB); ctx.moveTo(pL, hy + 0.5); ctx.lineTo(pR, hy + 0.5); ctx.stroke();
    ctx.restore();
    const price = lo + ((pB - hy) / pH) * span;
    ctx.fillStyle = c.surface; ctx.fillRect(pR + 2, hy - 9, PAD.right - 6, 18);
    ctx.fillStyle = c.ink; ctx.fillText(fmt(price), pR + 8, hy);
  }

  return { pL, pR, pT, pB, slot, x: xk, y, lo, hi, offset: Math.max(0, offset), vorn, end, total,
    count: shown.length, spalten, boxes, ema: emaWerte, visible };
}

function indexFuerTs(candles, ts) {
  if (!candles.length) return null;
  if (ts <= candles[0].ts) return 0;
  if (ts >= candles[candles.length - 1].ts) return candles.length - 1;
  let lo = 0, hi = candles.length - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; if (candles[m].ts < ts) lo = m + 1; else hi = m; }
  return lo;
}

function naechsteBeruehrungen(view, band) {
  const mid = (band.high + band.low) / 2;
  let best = null;
  for (const l of view?.levels ?? []) {
    const d = Math.abs(l.price - mid);
    if (best === null || d < best.d) best = { d, touches: l.touches ?? 1 };
  }
  return Math.max(1, Math.min(5, best ? best.touches : 2));
}

function drawStars(ctx, x, y, n, c) {
  const size = 9, gap = 2, total = 5;
  const startX = x - total * (size + gap);
  for (let i = 0; i < total; i++) {
    ctx.fillStyle = i < n ? c.star : "rgba(255,255,255,0.18)";
    star(ctx, startX + i * (size + gap) + size / 2, y, size / 2);
  }
}
function star(ctx, cx, cy, r) {
  ctx.beginPath();
  for (let i = 0; i < 10; i++) {
    const rr = i % 2 === 0 ? r : r * 0.45;
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const p = [cx + Math.cos(a) * rr, cy + Math.sin(a) * rr];
    if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
  }
  ctx.closePath(); ctx.fill();
}

function drawProfile(ctx, candles, g) {
  const bins = 48, hist = new Array(bins).fill(0);
  for (const k of candles) {
    const i = Math.max(0, Math.min(bins - 1, Math.floor((((k.high + k.low) / 2 - g.lo) / (g.hi - g.lo)) * bins)));
    hist[i] += k.volume ?? 0;
  }
  const max = Math.max(...hist) || 1, width = 52;
  // Die Zeile mit dem meisten Volumen ist der Point of Control -- der Preis,
  // an dem am meisten gehandelt wurde, und damit der staerkste Magnet.
  const poc = hist.indexOf(max);
  ctx.save();
  for (let i = 0; i < bins; i++) {
    const h = (g.pB - g.pT) / bins;
    const yy = g.y(g.lo + ((i + 0.5) / bins) * (g.hi - g.lo)) - h / 2;
    ctx.fillStyle = i === poc ? "rgba(250,204,21,0.45)" : "rgba(232,237,245,0.14)";
    ctx.fillRect(g.pL, yy, (hist[i] / max) * width, Math.max(1, h - 1));
  }
  ctx.restore();
}

/**
 * Ruhende Liquiditaet aus dem Orderbuch, als Streifen am rechten Rand.
 *
 * Kein Bookmap ueber die Zeit -- dafuer muesste die x-Achse Sekunden sein,
 * und sie zeigt Kerzen. Was hier steht, ist der AKTUELLE Zustand: wo liegen
 * die Waende. Das ist die Frage, die ein Stop oder ein Ziel beantwortet
 * haben will, und sie ist mit einem Schnappschuss ehrlich zu beantworten.
 */
function drawHeatmap(ctx, book, g) {
  const alle = [...(book.bids ?? []).map(([p, q]) => [p, q, 1]), ...(book.asks ?? []).map(([p, q]) => [p, q, -1])];
  if (!alle.length) return;
  const max = Math.max(...alle.map(([, q]) => q)) || 1;
  const breite = 34;
  ctx.save();
  for (const [preis, menge, seite] of alle) {
    if (preis < g.lo || preis > g.hi) continue;
    const stark = Math.min(1, menge / max);
    ctx.fillStyle = seite > 0 ? `rgba(34,197,94,${0.12 + stark * 0.55})` : `rgba(239,68,68,${0.12 + stark * 0.55})`;
    ctx.fillRect(g.pR - breite, g.y(preis) - 1.5, breite * (0.35 + stark * 0.65), 3);
  }
  ctx.restore();
}

function niceStep(span, target) {
  const raw = span / target, mag = Math.pow(10, Math.floor(Math.log10(raw))), n = raw / mag;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * mag;
}

/* ------------------------------------------------- Kurven (Konto, Verlauf) -- */
function lineChart(canvas, series, { yOf, label, colour, grid, axis, zero }) {
  const ratio = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  if (!W || !H || !series.length) return;
  if (canvas.width !== W * ratio || canvas.height !== H * ratio) { canvas.width = W * ratio; canvas.height = H * ratio; }
  const ctx = canvas.getContext("2d"); ctx.setTransform(ratio, 0, 0, ratio, 0, 0); ctx.clearRect(0, 0, W, H);
  const pL = 52, pR = W - 16, pT = 16, pB = H - 36;
  const vals = series.map(yOf);
  let lo = Math.min(...vals, zero ? 0 : Infinity), hi = Math.max(...vals, zero ? 0 : -Infinity);
  if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
  const y = (v) => pB - ((v - lo) / (hi - lo)) * (pB - pT);
  const x = (i) => pL + (i / Math.max(1, series.length - 1)) * (pR - pL);
  ctx.font = "12px system-ui, sans-serif"; ctx.textBaseline = "middle"; ctx.textAlign = "right";
  const step = niceStep(hi - lo, 5);
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    const py = Math.round(y(v)) + 0.5;
    ctx.strokeStyle = grid; ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(pL, py); ctx.lineTo(pR, py); ctx.stroke();
    ctx.fillStyle = axis; ctx.fillText(v.toLocaleString("de-CH", { maximumFractionDigits: 2 }), pL - 8, py);
  }
  ctx.setLineDash([]);
  if (zero) { const z = Math.round(y(0)) + 0.5; ctx.strokeStyle = axis; ctx.beginPath(); ctx.moveTo(pL, z); ctx.lineTo(pR, z); ctx.stroke(); }
  ctx.strokeStyle = colour; ctx.lineWidth = 2.2; ctx.beginPath();
  series.forEach((p, i) => { const px = x(i), py = y(yOf(p)); if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py); });
  ctx.stroke();
  ctx.fillStyle = colour;
  if (series.length <= 80) series.forEach((p, i) => { ctx.beginPath(); ctx.arc(x(i), y(yOf(p)), 3.2, 0, Math.PI * 2); ctx.fill(); });
  ctx.fillStyle = axis; ctx.textAlign = "center"; ctx.textBaseline = "top";
  const every = Math.max(1, Math.round(series.length / 6));
  series.forEach((p, i) => { if (i % every !== 0 && i !== series.length - 1) return; ctx.fillText(label(p), x(i), pB + 8); });
}

export function drawEquity(canvas, series, range) {
  lineChart(canvas, series, {
    yOf: (p) => p.equity, colour: "#1d4ed8", grid: "#dbeafe", axis: "#2563eb", zero: false,
    label: (p) => { const d = new Date(p.ts); return range === "today" ? `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : `${d.getDate()}.${d.getMonth() + 1}.`; },
  });
}

export function drawRCurve(canvas, points) {
  lineChart(canvas, points, {
    yOf: (p) => p.cumulative_r, colour: cssVar("--long") || "#22c55e", grid: cssVar("--rule") || "#1f2733",
    axis: cssVar("--ink-3") || "#6b7789", zero: true,
    label: (p) => { const d = new Date(p.ts); return `${d.getDate()}.${d.getMonth() + 1}. ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; },
  });
}
