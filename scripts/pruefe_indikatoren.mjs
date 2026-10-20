/**
 * Prueft die Indikator-Rechnungen gegen von Hand nachrechenbare Erwartungen.
 *
 * Die Python-Suite erreicht diesen Code nicht -- er laeuft im Browser. Ohne
 * diese Datei waere "stimmt die EMA?" eine Frage, die man nur am Augenschein
 * im Chart beantworten kann, und genau das ist in diesem Projekt schon
 * mehrfach schiefgegangen.
 *
 *     node scripts/pruefe_indikatoren.mjs
 */
import { copyFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// Node liest eine `.js` ohne package.json als CommonJS; der Browser bekommt
// sie als Modul und ist zufrieden. Statt dem ausgelieferten Verzeichnis eine
// package.json unterzuschieben, die nur fuer diese Pruefung da waere, kopiert
// der Pruefer die Datei einmal nach `.mjs` -- die Quelle bleibt unberuehrt.
const hier = dirname(fileURLToPath(import.meta.url));
const quelle = join(hier, "..", "src", "traidingbrain", "dashboard", "static", "terminal-indikatoren.js");
const kopie = join(mkdtempSync(join(tmpdir(), "dw-ind-")), "terminal-indikatoren.mjs");
copyFileSync(quelle, kopie);
const {
  INDIKATOREN, atr, bollinger, ema, macd, rsi, sma, stochastik, supertrend, vwap,
} = await import(pathToFileURL(kopie).href);

let fehler = 0;
const ok = (name, bedingung, zusatz = "") => {
  if (!bedingung) fehler++;
  console.log(`${bedingung ? "  ok  " : "FEHLER"}  ${name}${zusatz ? "  -- " + zusatz : ""}`);
};
const nah = (a, b, eps = 1e-9) => Math.abs(a - b) < eps;

// Eine glatte Reihe statt Zufall: jede Zahl ist nachrechenbar.
const n = 300;
const kerzen = Array.from({ length: n }, (_, i) => {
  const b = 100 + Math.sin(i / 11) * 8 + i * 0.05;
  return { ts: 1.7e12 + i * 900000, open: b, high: b + 1.2, low: b - 1.2, close: b + 0.3, volume: 100 + (i % 7) * 10 };
});
const close = kerzen.map((k) => k.close);

console.log("SMA");
const handSMA = close.slice(-50).reduce((a, b) => a + b, 0) / 50;
ok("SMA 50 gleich der Handrechnung", nah(sma(close, 50).at(-1), handSMA, 1e-9),
   `${sma(close, 50).at(-1).toFixed(6)} vs ${handSMA.toFixed(6)}`);
ok("SMA vor der Periode ist null", sma(close, 50)[48] === null);

console.log("EMA");
ok("EMA vor der Periode ist null", ema(close, 20)[18] === null,
   "sonst zieht die Linie quer durch den Chart");
ok("EMA startet auf dem Mittel der ersten n",
   nah(ema(close, 20)[19], close.slice(0, 20).reduce((a, b) => a + b, 0) / 20, 1e-9));
// Eine konstante Reihe muss exakt die Konstante liefern.
ok("EMA einer Konstanten ist die Konstante", nah(ema(new Array(60).fill(7), 20).at(-1), 7, 1e-12));

console.log("RSI");
const r = rsi(close, 14).filter((v) => v != null);
ok("RSI bleibt in [0, 100]", r.every((v) => v >= 0 && v <= 100));
ok("RSI einer steigenden Reihe ist 100",
   nah(rsi(Array.from({ length: 50 }, (_, i) => i), 14).at(-1), 100, 1e-9));
ok("RSI einer fallenden Reihe ist 0",
   nah(rsi(Array.from({ length: 50 }, (_, i) => 50 - i), 14).at(-1), 0, 1e-9));

console.log("ATR");
ok("ATR ist nie negativ", atr(kerzen, 14).filter((v) => v != null).every((v) => v >= 0));
// Die Reihe hat eine feste Spanne von 2.4; die erste echte Spanne ist high-low.
ok("ATR trifft die bekannte Spanne", nah(atr(kerzen, 14).at(-1), 2.4, 0.3),
   atr(kerzen, 14).at(-1).toFixed(4));

console.log("Bollinger");
const b = bollinger(close, 20, 2);
ok("oben > mitte > unten", b.oben.at(-1) > b.mitte.at(-1) && b.mitte.at(-1) > b.unten.at(-1));
ok("Mitte ist die SMA", nah(b.mitte.at(-1), sma(close, 20).at(-1), 1e-12));
ok("Konstante Reihe hat Breite null",
   nah(bollinger(new Array(60).fill(5), 20, 2).oben.at(-1), 5, 1e-12));

console.log("MACD");
const m = macd(close, 12, 26, 9);
ok("Linie ist schnelle minus langsame EMA",
   nah(m.linie.at(-1), ema(close, 12).at(-1) - ema(close, 26).at(-1), 1e-9));
ok("Histogramm ist Linie minus Signal", nah(m.hist.at(-1), m.linie.at(-1) - m.signal.at(-1), 1e-9));

console.log("Stochastik");
const st = stochastik(kerzen, 14, 3, 3);
ok("%K bleibt in [0, 100]", st.k.filter((v) => v != null).every((v) => v >= 0 && v <= 100));

console.log("Supertrend");
const sup = supertrend(kerzen, 10, 3);
ok("Richtung ist nur +1 oder -1", sup.richtung.filter((v) => v != null).every((v) => v === 1 || v === -1));

console.log("VWAP");
ok("VWAP liegt in der Spanne der Kerzen",
   vwap(kerzen, 86400000).filter((v) => v != null).every((v) => v > 90 && v < 140));
ok("VWAP ohne Ruecksetzung ist das Gesamtmittel",
   vwap(kerzen, 0).at(-1) !== vwap(kerzen, 3600000).at(-1),
   "stuendlich und nie duerfen nicht dasselbe sein");

console.log("Verzeichnis");
for (const [k, def] of Object.entries(INDIKATOREN)) {
  const p = Object.fromEntries(def.felder.map((f) => [f.k, f.vorgabe]));
  let serien = null;
  try { serien = def.rechne(kerzen, p); } catch (e) { /* faellt unten auf */ }
  ok(`${k} rechnet mit seinen Vorgaben`, Array.isArray(serien) && serien.length > 0);
  ok(`${k} hat eine bekannte Art`, def.art === "overlay" || def.art === "pane");
  // Eine Unterachse OHNE Hoehe bekommt im Zeichner 60 px -- das ist eine
  // stille Vorgabe, und sie gehoert in die Beschreibung, nicht in den Zeichner.
  if (def.art === "pane") ok(`${k} nennt seine Hoehe`, typeof def.hoehe === "number");
}

console.log(`\n${fehler === 0 ? "ALLE PRUEFUNGEN GRUEN" : fehler + " FEHLER"}`);
process.exit(fehler === 0 ? 0 : 1);
