/**
 * Mehrfach-Layout: derselbe Markt auf vier Zeitebenen, Fadenkreuz gekoppelt.
 *
 * Die vier Ebenen sind nicht gewaehlt, sie sind die des Systems: D1, H4, H1
 * und M15 sind genau die Charts, auf denen die Setups suchen
 * (`strategies/guide.py`, SEARCH_ORDER). Wer sehen will, warum ein Setup
 * feuerte, sieht hier alle Ebenen, die es gefragt hat, zur selben Zeit.
 *
 * Gekoppelt wird die ZEIT, nicht der Preis: unter dem Mauszeiger steht auf
 * jeder Ebene die Kerze, in der dieser Zeitpunkt liegt.
 */
import { drawTerminalChart } from "/static/terminal-chart.js";

export const MTF_EBENEN = ["D1", "H4", "H1", "M15"];

const daten = {};          // tf -> chart view
const geo = {};            // tf -> letzte Geometrie
let fuer = null;           // Markt, fuer den die Daten gelten
let hoverTs = null, hoverQuelle = null, hoverY = null;

export function mtfMarkup() {
  return MTF_EBENEN.map((tf) => `
    <div class="mtf__zelle" data-mtf="${tf}">
      <div class="mtf__kopf">
        <button type="button" class="mtf__tf" data-mtf-oeffne="${tf}" title="Als Einzelchart öffnen">${tf === "M15" ? "15m" : tf}</button>
        <span class="mtf__wert" data-mtf-wert="${tf}"></span>
      </div>
      <canvas class="mtf__canvas" data-mtf-canvas="${tf}"></canvas>
    </div>`).join("");
}

export async function ladeMtf(T) {
  const sym = T.S.symbol;
  if (fuer !== sym) { for (const k of Object.keys(daten)) delete daten[k]; fuer = sym; }
  await Promise.all(MTF_EBENEN.map(async (tf) => {
    try {
      const v = await T.api(`/api/market/${sym}/chart?timeframe=${tf}&candles=300`);
      if (T.S.symbol === sym) daten[tf] = v;
    } catch { /* bleibt leer, die Zelle sagt es */ }
  }));
  zeichneMtf(T);
}

function indexBisTs(kerzen, ts) {
  // Die letzte Kerze, die zu diesem Zeitpunkt schon eroeffnet war.
  let lo = 0, hi = kerzen.length - 1, best = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (kerzen[m].ts <= ts) { best = m; lo = m + 1; } else hi = m - 1; }
  return best;
}

export function zeichneMtf(T) {
  const box = document.querySelector("#mtf"); if (!box || box.hidden) return;
  for (const tf of MTF_EBENEN) {
    const canvas = box.querySelector(`[data-mtf-canvas="${tf}"]`);
    const wert = box.querySelector(`[data-mtf-wert="${tf}"]`);
    const v = daten[tf];
    if (!v?.candles?.length) {
      const ctx = canvas.getContext("2d"); ctx.clearRect(0, 0, canvas.width, canvas.height);
      wert.textContent = "lädt …"; continue;
    }
    let hover = null, ausserhalb = false;
    if (hoverTs !== null && geo[tf]) {
      const i = indexBisTs(v.candles, hoverTs);
      const g = geo[tf];
      if (i >= g.offset && i < g.offset + g.count) hover = { x: g.x(i - g.offset), y: hoverQuelle === tf ? hoverY : null };
      else ausserhalb = true;
    }
    const g = drawTerminalChart(canvas, v, {
      candles: v.candles, layers: T.S.ebenen, indikatoren: T.S.indikatoren,
      ansicht: { ...T.A, hochTief: false, countdown: false }, skala: { modus: T.A.skala.modus, invert: T.A.skala.invert },
      lines: T.positionLines(), hover,
    });
    if (g) geo[tf] = g;
    // Liegt der Zeitpunkt ausserhalb dieses Fensters, steht das da -- nicht
    // still die letzte Kerze, die man fuer die gesuchte halten wuerde.
    if (ausserhalb) { wert.textContent = "Zeitpunkt nicht im Fenster"; continue; }
    const k = g && g.hoverKi !== null ? v.candles[g.offset + g.hoverKi] : v.candles[v.candles.length - 1];
    if (k) {
      const chg = ((k.close - k.open) / k.open) * 100;
      wert.innerHTML = `O ${T.px(k.open)} H ${T.px(k.high)} L ${T.px(k.low)} C ${T.px(k.close)} <span class="${chg >= 0 ? "up" : "down"}">${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%</span>`;
    }
  }
}

export function wireMtf(T) {
  const box = document.querySelector("#mtf"); if (!box) return;
  box.innerHTML = mtfMarkup();
  box.addEventListener("pointermove", (e) => {
    const c = e.target.closest("[data-mtf-canvas]"); if (!c) return;
    const tf = c.dataset.mtfCanvas, g = geo[tf], v = daten[tf];
    if (!g || !v) return;
    const r = c.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    const ki = Math.floor((x - g.pL) / g.slot) - g.vorn;
    const k = v.candles[g.offset + ki];
    if (!k) return;
    hoverTs = k.ts; hoverQuelle = tf; hoverY = y;
    zeichneMtf(T);
  });
  box.addEventListener("pointerleave", () => { hoverTs = null; zeichneMtf(T); });
  box.addEventListener("click", (e) => {
    const b = e.target.closest("[data-mtf-oeffne]"); if (!b) return;
    T.oeffneEinzeln(b.dataset.mtfOeffne);
  });
  box.addEventListener("dblclick", (e) => {
    const c = e.target.closest("[data-mtf]"); if (c) T.oeffneEinzeln(c.dataset.mtf);
  });
  new ResizeObserver(() => zeichneMtf(T)).observe(box);
}
