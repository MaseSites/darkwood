/**
 * Wie der Chart aussieht -- Skala, Charttyp und die Hilfslinien, die
 * TradingView mitbringt. Ausgelagert aus terminal-chart.js, damit der Zeichner
 * nicht weiter waechst; er ruft diese Funktionen an festen Stellen.
 *
 * **Was hier NICHT passiert: Analyse.** Heikin-Ashi ist eine Darstellung der
 * Kerzen, keine Preisreihe. Indikatoren, das letzte Preisschild und jede
 * Linie im Chart rechnen weiter mit den echten Kursen. Ein Heikin-Ashi-Close
 * als "letzter Preis" waere eine erfundene Zahl.
 */

/** Heikin-Ashi aus echten Kerzen. Nur fuer das Zeichnen der Koerper. */
export function heikinAshi(kerzen) {
  const aus = [];
  for (let i = 0; i < kerzen.length; i++) {
    const k = kerzen[i];
    const close = (k.open + k.high + k.low + k.close) / 4;
    const open = i === 0 ? (k.open + k.close) / 2 : (aus[i - 1].open + aus[i - 1].close) / 2;
    aus.push({ ts: k.ts, open, close, high: Math.max(k.high, open, close), low: Math.min(k.low, open, close) });
  }
  return aus;
}

/**
 * Preis <-> Pixel fuer die vier Skalenarten.
 *
 *   normal   linear im Preis
 *   log      linear im Logarithmus -- gleiche Prozente, gleiche Abstaende
 *   prozent  linear im Preis, beschriftet in % zum ersten sichtbaren Schluss
 *   invert   jede der drei, kopfstehend
 *
 * `preisBei` ist die Umkehrung und das, was Zeichenwerkzeuge, Alarme und das
 * Fadenkreuz brauchen. Bis zum 21.10.2026 rechneten sie die lineare Formel
 * selbst nach -- unter einer log-Skala haette jede Linie neben dem Klick
 * gelegen.
 */
export function skalaBauen({ modus = "normal", invert = false, lo, hi, pT, pB }) {
  const pH = pB - pT;
  const log = modus === "log" && lo > 0;
  const f = log ? Math.log : (v) => v;
  const fi = log ? Math.exp : (v) => v;
  const a = f(lo), b = f(hi), weite = (b - a) || 1;
  const anteil = (p) => (f(p) - a) / weite;
  const y = invert ? (p) => pT + anteil(p) * pH : (p) => pB - anteil(p) * pH;
  const preisBei = invert
    ? (py) => fi(a + ((py - pT) / pH) * weite)
    : (py) => fi(a + ((pB - py) / pH) * weite);
  return { y, preisBei, log };
}

/** Beschriftung eines Achsenpreises je nach Modus. */
export function achsenText(p, modus, basis, fmt) {
  if (modus === "prozent" && basis) {
    const v = (p / basis - 1) * 100;
    return `${v >= 0 ? "+" : ""}${v.toFixed(Math.abs(v) < 10 ? 2 : 1)}%`;
  }
  return fmt(p);
}

/**
 * Die Kerzen im gewaehlten Typ zeichnen.
 *
 * `plot` sind die Kerzen, die GEZEICHNET werden (bei Heikin-Ashi umgerechnet),
 * `echt` die echten fuer Linie/Flaeche/Baseline -- eine Linie zeigt immer den
 * echten Schluss.
 */
export function zeichneKerzen(ctx, typ, plot, echt, g) {
  const { xk, y, body, c, formingKi, pT, pB, pL, pR } = g;
  if (typ === "linie" || typ === "flaeche" || typ === "baseline") {
    if (!echt.length) return;
    const pts = echt.map((k, i) => [xk(i), y(k.close)]);
    if (typ === "flaeche") {
      ctx.save();
      const verlauf = ctx.createLinearGradient(0, pT, 0, pB);
      verlauf.addColorStop(0, "rgba(96,165,250,0.28)");
      verlauf.addColorStop(1, "rgba(96,165,250,0.02)");
      ctx.fillStyle = verlauf;
      ctx.beginPath(); ctx.moveTo(pts[0][0], pB);
      for (const [px, py] of pts) ctx.lineTo(px, py);
      ctx.lineTo(pts[pts.length - 1][0], pB); ctx.closePath(); ctx.fill();
      ctx.restore();
    }
    if (typ === "baseline") {
      // Die Basis ist der erste sichtbare Schluss: ueber ihr gruen, unter ihr
      // rot. So liest man "seit Beginn des Fensters" ohne Rechnen.
      const by = y(echt[0].close);
      ctx.save();
      ctx.setLineDash([3, 3]); ctx.strokeStyle = c.ink3; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pL, Math.round(by) + 0.5); ctx.lineTo(pR, Math.round(by) + 0.5); ctx.stroke();
      ctx.setLineDash([]);
      for (const [farbe, clipOben] of [[c.long, true], [c.short, false]]) {
        ctx.save();
        ctx.beginPath();
        if (clipOben) ctx.rect(pL, pT, pR - pL, by - pT); else ctx.rect(pL, by, pR - pL, pB - by);
        ctx.clip();
        ctx.strokeStyle = farbe; ctx.lineWidth = 1.5;
        ctx.beginPath(); pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); ctx.stroke();
        ctx.restore();
      }
      ctx.restore();
      return;
    }
    ctx.save(); ctx.strokeStyle = "#60a5fa"; ctx.lineWidth = 1.5; ctx.lineJoin = "round";
    ctx.beginPath(); pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); ctx.stroke();
    ctx.restore();
    return;
  }

  for (let i = 0; i < plot.length; i++) {
    const k = plot[i];
    const up = k.close >= k.open;
    const col = up ? c.long : c.short;
    const pxx = Math.round(xk(i));
    ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 1;
    if (typ === "balken") {
      // OHLC-Balken: Docht, links der Eroeffnungsstrich, rechts der Schluss.
      const arm = Math.max(2, Math.floor(body / 2));
      ctx.beginPath();
      ctx.moveTo(pxx + 0.5, y(k.high)); ctx.lineTo(pxx + 0.5, y(k.low));
      ctx.moveTo(pxx - arm, Math.round(y(k.open)) + 0.5); ctx.lineTo(pxx + 0.5, Math.round(y(k.open)) + 0.5);
      ctx.moveTo(pxx + 0.5, Math.round(y(k.close)) + 0.5); ctx.lineTo(pxx + arm + 1, Math.round(y(k.close)) + 0.5);
      ctx.stroke();
      continue;
    }
    ctx.beginPath(); ctx.moveTo(pxx + 0.5, y(k.high)); ctx.lineTo(pxx + 0.5, y(k.low)); ctx.stroke();
    const t = Math.min(y(k.open), y(k.close)), bt = Math.max(y(k.open), y(k.close));
    const hohl = i === formingKi || (typ === "hohl" && up);
    if (hohl) {
      // Der Koerper muss die Docht-Linie verdecken, sonst liest sich eine
      // hohle Kerze wie eine durchgestrichene.
      ctx.fillStyle = c.ground;
      ctx.fillRect(pxx - body / 2, t, body, Math.max(1, bt - t));
      ctx.strokeRect(pxx - body / 2 + 0.5, t + 0.5, Math.max(1, body - 1), Math.max(1, bt - t - 1));
    } else {
      ctx.fillRect(pxx - body / 2, t, body, Math.max(1, bt - t));
    }
  }
}

/**
 * Senkrechte Linien am UTC-Tageswechsel, nur auf Ebenen unter einem Tag.
 * Auf D1 waere jede Kerze ein Wechsel; dort stehen sie am Wochenbeginn.
 */
export function zeichneSitzungen(ctx, shown, xk, g) {
  if (shown.length < 2) return;
  const takt = shown[1].ts - shown[0].ts;
  const tag = 86_400_000, woche = 7 * tag;
  const grenze = takt < tag ? tag : takt < woche ? woche : 0;
  if (!grenze) return;
  ctx.save();
  ctx.strokeStyle = g.c.rule; ctx.setLineDash([2, 4]); ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 1; i < shown.length; i++) {
    // Wochen beginnen montags: das Gitter der Epoche liegt donnerstags.
    const versatz = grenze === woche ? 4 * tag : 0;
    const a = Math.floor((shown[i - 1].ts - versatz) / grenze), b = Math.floor((shown[i].ts - versatz) / grenze);
    if (a === b) continue;
    const px = Math.round((xk(i - 1) + xk(i)) / 2) + 0.5;
    ctx.moveTo(px, g.pT); ctx.lineTo(px, g.pB);
  }
  ctx.stroke();
  ctx.restore();
}

/** Hoch und Tief des sichtbaren Fensters, wie TradingViews "High/Low"-Marken. */
export function zeichneHochTief(ctx, shown, xk, y, g, fmt) {
  if (!shown.length) return;
  let ih = 0, il = 0;
  for (let i = 1; i < shown.length; i++) {
    if (shown[i].high > shown[ih].high) ih = i;
    if (shown[i].low < shown[il].low) il = i;
  }
  ctx.save();
  ctx.font = `10px ${g.c.mono}`; ctx.fillStyle = g.c.ink2; ctx.strokeStyle = g.c.ink3; ctx.lineWidth = 1;
  const marke = (i, preis, oben) => {
    const px = xk(i), py = y(preis);
    const rechts = px < (g.pL + g.pR) / 2;
    const ende = px + (rechts ? 18 : -18);
    ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(ende, py); ctx.stroke();
    ctx.textAlign = rechts ? "left" : "right"; ctx.textBaseline = oben ? "bottom" : "top";
    ctx.fillText(`${oben ? "H" : "T"} ${fmt(preis)}`, ende + (rechts ? 3 : -3), py + (oben ? -1 : 1));
  };
  marke(ih, shown[ih].high, true);
  marke(il, shown[il].low, false);
  ctx.restore();
}

/** Restzeit der formenden Kerze, unter dem Preisschild. mm:ss oder hh:mm:ss. */
export function countdownText(restMs) {
  if (!Number.isFinite(restMs) || restMs < 0) return null;
  const s = Math.floor(restMs / 1000);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sek = s % 60;
  const zwei = (v) => String(v).padStart(2, "0");
  if (h >= 24) return `${Math.floor(h / 24)}T ${zwei(h % 24)}:${zwei(m)}`;
  return h ? `${zwei(h)}:${zwei(m)}:${zwei(sek)}` : `${zwei(m)}:${zwei(sek)}`;
}

/** Datum und Uhrzeit fuer die Zeitmarke am Fadenkreuz. */
export function zeitText(ts, takt) {
  const d = new Date(ts);
  const zwei = (v) => String(v).padStart(2, "0");
  const datum = `${zwei(d.getDate())}.${zwei(d.getMonth() + 1)}.${String(d.getFullYear()).slice(2)}`;
  return takt >= 86_400_000 ? datum : `${datum} ${zwei(d.getHours())}:${zwei(d.getMinutes())}`;
}
