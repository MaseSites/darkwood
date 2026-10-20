/**
 * Die Zeichenwerkzeuge des Charts.
 *
 * **Punkte liegen in ZEIT und PREIS, nie in Pixeln.** Eine Trendlinie, die
 * sich Bildschirmkoordinaten merkt, wandert beim ersten Zoom vom Kurs weg und
 * behauptet danach etwas, das nie jemand gezeichnet hat. Jeder Punkt ist
 * `{ts, preis}`; der Zeichner rechnet beim Malen um.
 *
 * Jedes Werkzeug beschreibt SELBST, wie viele Punkte es braucht und wie es
 * gezeichnet wird. Ein neues Werkzeug kostet einen Eintrag hier und eine
 * Zeile in der Leiste -- keinen Eingriff in die Ereignisbehandlung.
 */

/** Wie ein Werkzeug Punkte sammelt. */
export const PUNKTE = { EINER: 1, ZWEI: 2, FREI: 0 };

const pfad = (ctx, pts, schliessen = false) => {
  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
  if (schliessen) ctx.closePath();
};

const pfeilspitze = (ctx, von, nach, groesse = 9) => {
  const w = Math.atan2(nach.y - von.y, nach.x - von.x);
  ctx.beginPath();
  ctx.moveTo(nach.x, nach.y);
  ctx.lineTo(nach.x - groesse * Math.cos(w - Math.PI / 7), nach.y - groesse * Math.sin(w - Math.PI / 7));
  ctx.lineTo(nach.x - groesse * Math.cos(w + Math.PI / 7), nach.y - groesse * Math.sin(w + Math.PI / 7));
  ctx.closePath();
  ctx.fill();
};

//: Die Stufen des Fibonacci-Retracements. 0 und 1 gehoeren dazu -- ohne sie
//: steht das Gitter in der Luft und man sieht nicht, worauf es sich bezieht.
export const FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];

export const WERKZEUGE = {
  cross: {
    name: "Fadenkreuz", punkte: null,
    pfad: "M12 3v18M3 12h18",
  },
  trend: {
    name: "Trendlinie", punkte: PUNKTE.ZWEI,
    pfad: "M4 19L20 5M4 19a1.6 1.6 0 1 0 0-.1M20 5a1.6 1.6 0 1 0 0-.1",
    male(ctx, p, s) { ctx.lineWidth = s.dicke; ctx.strokeStyle = s.farbe; pfad(ctx, p); ctx.stroke(); },
  },
  hline: {
    name: "Horizontale Linie", punkte: PUNKTE.EINER,
    pfad: "M3 8h18M3 16h18",
    male(ctx, p, s, g) {
      ctx.lineWidth = s.dicke; ctx.strokeStyle = s.farbe;
      pfad(ctx, [{ x: g.pL, y: p[0].y }, { x: g.pR, y: p[0].y }]); ctx.stroke();
    },
  },
  hray: {
    name: "Horizontaler Strahl", punkte: PUNKTE.EINER,
    pfad: "M3 12h14M17 12l-4-3M17 12l-4 3",
    male(ctx, p, s, g) {
      // Nach RECHTS, nicht nach beiden Seiten: ein Strahl sagt "ab hier gilt
      // das", und das ist eine Aussage ueber die Zukunft, nicht ueber frueher.
      ctx.lineWidth = s.dicke; ctx.strokeStyle = s.farbe;
      pfad(ctx, [{ x: p[0].x, y: p[0].y }, { x: g.pR, y: p[0].y }]); ctx.stroke();
      ctx.fillStyle = s.farbe;
      ctx.beginPath(); ctx.arc(p[0].x, p[0].y, 2.5, 0, 7); ctx.fill();
    },
  },
  fib: {
    name: "Fibonacci-Retracement", punkte: PUNKTE.ZWEI,
    pfad: "M3 5h18M3 10h18M3 14h18M3 19h18",
    male(ctx, p, s, g) {
      const [a, b] = p, hoch = Math.min(a.y, b.y), tief = Math.max(a.y, b.y);
      const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x);
      ctx.save();
      ctx.font = '10px ui-monospace, Menlo, monospace'; ctx.textBaseline = "middle";
      for (const f of FIB) {
        const yy = tief - (tief - hoch) * f;
        ctx.strokeStyle = `${s.farbe}${f === 0 || f === 1 ? "" : "99"}`;
        ctx.lineWidth = f === 0.618 ? 1.6 : 1;
        ctx.setLineDash(f === 0 || f === 1 ? [] : [4, 3]);
        pfad(ctx, [{ x: x0, y: yy }, { x: Math.max(x1, g.pR - 40), y: yy }]); ctx.stroke();
        ctx.fillStyle = s.farbe; ctx.textAlign = "left";
        ctx.fillText(f.toFixed(3).replace(/0+$/, "").replace(/\.$/, ""), x0 + 3, yy - 6);
      }
      ctx.restore();
    },
  },
  long: {
    name: "Long-Position", punkte: PUNKTE.ZWEI, richtung: 1,
    pfad: "M4 16h16M4 16V9M4 9h10M6 20h12",
    male: (ctx, p, s, g) => positionsKasten(ctx, p, s, g, 1),
  },
  short: {
    name: "Short-Position", punkte: PUNKTE.ZWEI, richtung: -1,
    pfad: "M4 8h16M4 8v7M4 15h10M6 4h12",
    male: (ctx, p, s, g) => positionsKasten(ctx, p, s, g, -1),
  },
  pinsel: {
    name: "Pinsel", punkte: PUNKTE.FREI,
    pfad: "M4 20c4-1 5-4 7-7s4-6 7-7c1 3-2 6-4 8s-6 5-10 6z",
    male(ctx, p, s) {
      ctx.lineWidth = s.dicke; ctx.strokeStyle = s.farbe;
      ctx.lineJoin = "round"; ctx.lineCap = "round";
      pfad(ctx, p); ctx.stroke();
    },
  },
  marker: {
    name: "Textmarker", punkte: PUNKTE.FREI,
    pfad: "M5 18l3-9 8 2-3 9zM13 11l4-6 3 2-4 6",
    male(ctx, p, s) {
      // Breit und durchscheinend -- ein Marker hebt hervor, er zeichnet nicht.
      ctx.save();
      ctx.globalAlpha = 0.28; ctx.lineWidth = s.dicke * 7;
      ctx.strokeStyle = s.farbe; ctx.lineJoin = "round"; ctx.lineCap = "round";
      pfad(ctx, p); ctx.stroke(); ctx.restore();
    },
  },
  pfeil: {
    name: "Pfeilmarkierung", punkte: PUNKTE.ZWEI,
    pfad: "M5 19L19 5M19 5h-7M19 5v7",
    male(ctx, p, s) {
      ctx.lineWidth = s.dicke; ctx.strokeStyle = s.farbe; ctx.fillStyle = s.farbe;
      pfad(ctx, p); ctx.stroke(); pfeilspitze(ctx, p[0], p[1], 5 + s.dicke * 3);
    },
  },
  rect: {
    name: "Viereck", punkte: PUNKTE.ZWEI,
    pfad: "M4 6h16v12H4z",
    male(ctx, p, s) {
      const [a, b] = p;
      ctx.fillStyle = `${s.farbe}1f`; ctx.strokeStyle = s.farbe; ctx.lineWidth = s.dicke;
      ctx.fillRect(a.x, a.y, b.x - a.x, b.y - a.y);
      ctx.strokeRect(a.x + 0.5, a.y + 0.5, b.x - a.x, b.y - a.y);
    },
  },
  rectrot: {
    name: "Rotiertes Viereck", punkte: PUNKTE.ZWEI, hoehe: true,
    pfad: "M3 14l7-8 11 4-7 8z",
    male(ctx, p, s) {
      // Ein Parallelogramm laengs der Verbindung: die Hoehe steht senkrecht
      // dazu. So folgt der Kasten einem Trend, statt achsenparallel zu bleiben.
      const [a, b] = p;
      const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
      const h = (s.hoehe ?? 26), nx = (-dy / len) * h / 2, ny = (dx / len) * h / 2;
      ctx.fillStyle = `${s.farbe}1f`; ctx.strokeStyle = s.farbe; ctx.lineWidth = s.dicke;
      pfad(ctx, [{ x: a.x + nx, y: a.y + ny }, { x: b.x + nx, y: b.y + ny },
                 { x: b.x - nx, y: b.y - ny }, { x: a.x - nx, y: a.y - ny }], true);
      ctx.fill(); ctx.stroke();
    },
  },
  tag: {
    name: "Preisschild", punkte: PUNKTE.EINER, text: true,
    pfad: "M4 9l5-5h11v11l-5 5zM15 9h.01",
    male(ctx, p, s, g, d) {
      const txt = d.text || g.preisText(d.punkte[0].preis);
      ctx.save();
      ctx.font = '11px ui-monospace, Menlo, monospace';
      const w = ctx.measureText(txt).width + 14;
      ctx.fillStyle = s.farbe;
      ctx.beginPath();
      ctx.moveTo(p[0].x, p[0].y);
      ctx.lineTo(p[0].x + 7, p[0].y - 9); ctx.lineTo(p[0].x + w, p[0].y - 9);
      ctx.lineTo(p[0].x + w, p[0].y + 9); ctx.lineTo(p[0].x + 7, p[0].y + 9);
      ctx.closePath(); ctx.fill();
      ctx.fillStyle = "#06090f"; ctx.textBaseline = "middle"; ctx.textAlign = "left";
      ctx.fillText(txt, p[0].x + 11, p[0].y);
      ctx.restore();
    },
  },
  kreis: {
    name: "Kreis", punkte: PUNKTE.ZWEI,
    pfad: "M12 4a8 8 0 1 0 .1 0",
    male(ctx, p, s) {
      const r = Math.hypot(p[1].x - p[0].x, p[1].y - p[0].y);
      ctx.fillStyle = `${s.farbe}1a`; ctx.strokeStyle = s.farbe; ctx.lineWidth = s.dicke;
      ctx.beginPath(); ctx.arc(p[0].x, p[0].y, r, 0, 7); ctx.fill(); ctx.stroke();
    },
  },
  ellipse: {
    name: "Ellipse", punkte: PUNKTE.ZWEI,
    pfad: "M12 7c5 0 9 2.2 9 5s-4 5-9 5-9-2.2-9-5 4-5 9-5z",
    male(ctx, p, s) {
      const cx = (p[0].x + p[1].x) / 2, cy = (p[0].y + p[1].y) / 2;
      ctx.fillStyle = `${s.farbe}1a`; ctx.strokeStyle = s.farbe; ctx.lineWidth = s.dicke;
      ctx.beginPath();
      ctx.ellipse(cx, cy, Math.abs(p[1].x - p[0].x) / 2, Math.abs(p[1].y - p[0].y) / 2, 0, 0, 7);
      ctx.fill(); ctx.stroke();
    },
  },
  text: {
    name: "Text", punkte: PUNKTE.EINER, text: true,
    pfad: "M5 6h14M12 6v13",
    male(ctx, p, s, g, d) {
      ctx.save();
      ctx.font = `${10 + s.dicke * 2}px system-ui, sans-serif`;
      ctx.fillStyle = s.farbe; ctx.textBaseline = "middle"; ctx.textAlign = "left";
      ctx.fillText(d.text || "…", p[0].x + 4, p[0].y);
      ctx.restore();
    },
  },
  lineal: {
    name: "Lineal", punkte: PUNKTE.ZWEI,
    pfad: "M3 15l12-12 6 6-12 12zM7 11l2 2M10 8l2 2M13 5l2 2",
    male(ctx, p, s, g, d) {
      const [a, b] = p;
      const vonP = d.punkte[0].preis, nachP = d.punkte[1].preis;
      const dp = nachP - vonP, pct = vonP ? (dp / vonP) * 100 : 0;
      const balken = Math.abs(d.punkte[1].index - d.punkte[0].index);
      const auf = dp >= 0;
      ctx.save();
      ctx.fillStyle = auf ? "rgba(34,197,94,0.16)" : "rgba(239,68,68,0.16)";
      ctx.fillRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y));
      ctx.strokeStyle = auf ? "#22c55e" : "#ef4444"; ctx.lineWidth = 1;
      ctx.strokeRect(Math.min(a.x, b.x) + .5, Math.min(a.y, b.y) + .5, Math.abs(b.x - a.x), Math.abs(b.y - a.y));
      ctx.fillStyle = s.farbe; ctx.fillRect(a.x, a.y, 0, 0);
      ctx.strokeStyle = s.farbe; pfad(ctx, [a, b]); ctx.stroke();
      ctx.fillStyle = auf ? "#22c55e" : "#ef4444";
      pfeilspitze(ctx, a, b, 8);
      // Was ein Lineal beantworten soll: wie weit, wie viel Prozent, wie lang.
      const txt = `${dp >= 0 ? "+" : ""}${dp.toFixed(Math.abs(dp) < 1 ? 4 : 2)}  ${pct >= 0 ? "+" : ""}${pct.toFixed(2)} %  ${balken} Kerzen`;
      ctx.font = '10px ui-monospace, Menlo, monospace';
      const w = ctx.measureText(txt).width + 10;
      const mx = (a.x + b.x) / 2 - w / 2, my = Math.min(a.y, b.y) - 16;
      ctx.fillStyle = "rgba(6,9,15,0.9)"; ctx.fillRect(mx, my, w, 15);
      ctx.fillStyle = auf ? "#22c55e" : "#ef4444";
      ctx.textBaseline = "middle"; ctx.textAlign = "left";
      ctx.fillText(txt, mx + 5, my + 8);
      ctx.restore();
    },
  },
  alert: {
    name: "Preisalarm", punkte: null,
    pfad: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0",
  },
  clear: {
    name: "Zeichnungen löschen", punkte: null,
    pfad: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
  },
};

/**
 * Ein Positionskasten: Einstieg, Ziel (gruen) und Stop (rot), mit dem
 * Chance:Risiko daneben.
 *
 * Gezeichnet aus ZWEI Punkten -- Einstieg und Ziel. Der Stop sitzt
 * spiegelbildlich im Abstand `chance_risiko`, Vorgabe 2:1. Das ist eine
 * Entscheidung und keine Messung: wer den Stop woanders will, zieht ihn.
 */
function positionsKasten(ctx, p, s, g, richtung) {
  const [ein, ziel] = p;
  const hoehe = ziel.y - ein.y;
  const stopY = ein.y - hoehe / (s.crv ?? 2);
  const x0 = Math.min(ein.x, ziel.x), x1 = Math.max(ein.x, ziel.x) + 40;
  ctx.save();
  ctx.fillStyle = "rgba(34,197,94,0.16)";
  ctx.fillRect(x0, Math.min(ein.y, ziel.y), x1 - x0, Math.abs(hoehe));
  ctx.fillStyle = "rgba(239,68,68,0.16)";
  ctx.fillRect(x0, Math.min(ein.y, stopY), x1 - x0, Math.abs(stopY - ein.y));
  ctx.strokeStyle = "#e8edf5"; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
  pfad(ctx, [{ x: x0, y: ein.y }, { x: x1, y: ein.y }]); ctx.stroke();
  ctx.setLineDash([]);
  ctx.font = '10px ui-monospace, Menlo, monospace';
  ctx.textBaseline = "middle"; ctx.textAlign = "left";
  ctx.fillStyle = "#22c55e"; ctx.fillText("Ziel", x0 + 4, ziel.y + (hoehe > 0 ? -7 : 7));
  ctx.fillStyle = "#ef4444"; ctx.fillText("Stop", x0 + 4, stopY + (hoehe > 0 ? 7 : -7));
  ctx.fillStyle = "#e8edf5";
  ctx.fillText(`${richtung > 0 ? "Long" : "Short"} · CRV ${(s.crv ?? 2).toFixed(1)}:1`, x0 + 4, ein.y - 8);
  ctx.restore();
}

/** Die Reihenfolge in der Leiste. Trenner als null. */
export const LEISTE = [
  "cross", "trend", "hline", "hray", "fib", null,
  "long", "short", null,
  "pinsel", "marker", "pfeil", null,
  "rect", "rectrot", "tag", "kreis", "ellipse", null,
  "text", "lineal", null,
  "alert", "clear",
];
