/**
 * Zeichnungen verwalten -- was TradingView im Objektbaum und in der unteren
 * Haelfte der Werkzeugleiste anbietet.
 *
 *   Strg+Z / Strg+Y      Rueckgaengig / Wiederholen (jede Aenderung, auch Loeschen)
 *   Strg+Alt+H           alle Zeichnungen aus- und einblenden
 *   Objektbaum           jede Zeichnung des Marktes einzeln aus/ein, loeschen
 *   Magnet               Punkte rasten auf Eroeffnung/Hoch/Tief/Schluss
 *   Umschalt beim Setzen Trendlinie rastet auf 0, 45 oder 90 Grad
 *
 * Der Zustand bleibt in `S.zeichnungen` (Zeit und Preis, nie Pixel). Hier
 * wird nur festgehalten, WIE er sich aendert, damit jede Aenderung
 * zuruecknehmbar ist.
 */
import { WERKZEUGE } from "./terminal-zeichnen.js";

const TIEFE = 60;          // so viele Schritte zurueck; mehr braucht niemand
let zurueck = [], vor = [];

/** Jede Aenderung an den Zeichnungen laeuft hier durch. */
export function aendere(S, merke, fn) {
  zurueck.push(JSON.stringify(S.zeichnungen));
  if (zurueck.length > TIEFE) zurueck.shift();
  vor = [];
  fn();
  merke();
}

export function rueckgaengig(S, merke) {
  if (!zurueck.length) return false;
  vor.push(JSON.stringify(S.zeichnungen));
  S.zeichnungen = JSON.parse(zurueck.pop());
  S.angefangen = null;
  merke();
  return true;
}

export function wiederholen(S, merke) {
  if (!vor.length) return false;
  zurueck.push(JSON.stringify(S.zeichnungen));
  S.zeichnungen = JSON.parse(vor.pop());
  merke();
  return true;
}

export function kannZurueck() { return zurueck.length > 0; }
export function kannVor() { return vor.length > 0; }

/**
 * Magnet: den Preis auf den naechsten der vier Kerzenwerte ziehen.
 * TradingViews "starker Magnet" -- er rastet immer, nicht erst in der Naehe.
 */
export function magnet(stelle, kerzen) {
  const k = kerzen[Math.max(0, Math.min(kerzen.length - 1, stelle.index))];
  if (!k || stelle.index >= kerzen.length) return stelle;
  const werte = [k.open, k.high, k.low, k.close];
  const naechster = werte.reduce((a, b) => (Math.abs(b - stelle.preis) < Math.abs(a - stelle.preis) ? b : a));
  return { ...stelle, preis: naechster };
}

/**
 * Umschalt beim zweiten Punkt: auf 0, 45 oder 90 Grad -- in PIXELN, nicht im
 * Preis, denn "45 Grad" ist eine Bildschirmaussage. Zurueckgerechnet ueber
 * die Skala, damit es unter log und invertiert genauso stimmt.
 */
export function einrasten(a, b, g, xVon) {
  const ax = xVon(a), ay = g.y(a.preis), bx = xVon(b), by = g.y(b.preis);
  const dx = bx - ax, dy = by - ay;
  const winkel = Math.atan2(dy, dx);
  const stufe = Math.round(winkel / (Math.PI / 4)) * (Math.PI / 4);
  const laenge = Math.hypot(dx, dy);
  if (Math.abs(Math.cos(stufe)) < 1e-6) return { ...b, index: a.index, ts: a.ts };       // senkrecht
  const ny = ay + Math.tan(stufe) * (bx - ax);
  if (!Number.isFinite(ny) || laenge === 0) return b;
  return { ...b, preis: g.preisBei(ny) };
}

const AUGE = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.5 8s2.4-4.5 6.5-4.5S14.5 8 14.5 8s-2.4 4.5-6.5 4.5S1.5 8 1.5 8z" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="8" cy="8" r="2" fill="currentColor"/></svg>';
const AUGE_ZU = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 2l12 12M6.2 3.8A7 7 0 0 1 8 3.5c4.1 0 6.5 4.5 6.5 4.5a12 12 0 0 1-1.9 2.4M4 5.2C2.4 6.5 1.5 8 1.5 8S3.9 12.5 8 12.5c.8 0 1.6-.2 2.3-.5" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>';
const MUELL = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>';

/** Der Objektbaum: Zeichnungen des aktuellen Marktes. */
export function objektbaumMarkup(S, fmt) {
  const eigene = S.zeichnungen.filter((d) => d.symbol === S.symbol);
  const kopf = `<div class="obj__kopf">
      <button type="button" data-obj-alle="${S.zeichnungenAus ? "an" : "aus"}" title="Strg+Alt+H">${S.zeichnungenAus ? "Alle einblenden" : "Alle ausblenden"}</button>
      <button type="button" data-obj-undo ${zurueck.length ? "" : "disabled"} title="Strg+Z">Rückgängig</button>
      <button type="button" data-obj-redo ${vor.length ? "" : "disabled"} title="Strg+Y">Wiederholen</button>
    </div>`;
  if (!eigene.length) {
    return `${kopf}<p class="obj__leer">Keine Zeichnung auf ${S.symbol.replace("USDT", "/USDT")}. Werkzeug links wählen und in den Chart klicken.</p>`;
  }
  const zeilen = eigene.slice().reverse().map((d) => {
    const wz = WERKZEUGE[d.typ];
    const p = d.punkte?.[0];
    const wann = p?.ts ? new Date(p.ts).toLocaleString("de-CH", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
    const versteckt = d.aus === true;
    return `<li class="obj__zeile${versteckt ? " obj__zeile--aus" : ""}">
        <span class="obj__farbe" style="background:${d.farbe ?? "#f59e0b"}" aria-hidden="true"></span>
        <span class="obj__name">${wz?.name ?? d.typ}${d.text ? ` · „${String(d.text).slice(0, 18)}“` : ""}</span>
        <span class="obj__wo">${d.tf ?? ""} ${p?.preis != null ? fmt(p.preis) : ""} ${wann}</span>
        <button type="button" class="obj__knopf" data-obj-auge="${d.id}" aria-pressed="${!versteckt}" aria-label="${versteckt ? "Einblenden" : "Ausblenden"}: ${wz?.name ?? d.typ}">${versteckt ? AUGE_ZU : AUGE}</button>
        <button type="button" class="obj__knopf" data-obj-weg="${d.id}" aria-label="Löschen: ${wz?.name ?? d.typ}">${MUELL}</button>
      </li>`;
  }).join("");
  return `${kopf}<ul class="obj__liste">${zeilen}</ul>
    <div class="pop__foot"><button type="button" data-obj-leeren>Alle auf diesem Markt löschen</button></div>`;
}

/** Klicks im Objektbaum. Gibt true zurueck, wenn sich etwas geaendert hat. */
export function objektbaumKlick(e, S, merke) {
  const t = e.target.closest("button"); if (!t) return false;
  if (t.dataset.objAlle) { S.zeichnungenAus = t.dataset.objAlle === "aus"; return true; }
  if (t.hasAttribute("data-obj-undo")) return rueckgaengig(S, merke);
  if (t.hasAttribute("data-obj-redo")) return wiederholen(S, merke);
  if (t.dataset.objAuge) {
    aendere(S, merke, () => {
      const d = S.zeichnungen.find((z) => z.id === t.dataset.objAuge);
      if (d) d.aus = !d.aus;
    });
    return true;
  }
  if (t.dataset.objWeg) {
    aendere(S, merke, () => { S.zeichnungen = S.zeichnungen.filter((z) => z.id !== t.dataset.objWeg); });
    return true;
  }
  if (t.hasAttribute("data-obj-leeren")) {
    aendere(S, merke, () => { S.zeichnungen = S.zeichnungen.filter((z) => z.symbol !== S.symbol); });
    return true;
  }
  return false;
}
