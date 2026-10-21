/**
 * Watchlist: die Maerkte des Kontos mit letztem Preis und Tagesaenderung,
 * ein Klick wechselt den Chart. TradingViews rechte Seitenleiste, hier links
 * ueber Kalender und Buch, weil rechts der Bot steht.
 *
 * Ein Aufruf fuer alle (`/api/terminal/watchlist`), alle drei Sekunden und
 * nur, solange das Fenster sichtbar ist.
 */

let maerkte = [], zeilen = [], fehler = null, laeuftSeit = 0;
//: Eine Abfrage, die nie zurueckkommt, darf die Liste nicht fuer immer
//: anhalten. So geschehen beim ersten Test am 21.10.: die Sperre gegen
//: Doppelabfragen blieb gesetzt, und dort stand dauerhaft "Lade Kurse".
const SPERRE_MS = 10_000;

export function setzeMaerkte(liste) { maerkte = liste; }

export async function tickWatchlist(T) {
  const panel = document.querySelector("#panel-watchlist");
  if (!panel || panel.hidden || !maerkte.length || document.hidden) return;
  if (laeuftSeit && Date.now() - laeuftSeit < SPERRE_MS) return;
  laeuftSeit = Date.now();
  try {
    const ab = new AbortController();
    const zeit = setTimeout(() => ab.abort(), SPERRE_MS - 1000);
    zeilen = await T.api(`/api/terminal/watchlist?symbols=${maerkte.join(",")}`, { signal: ab.signal });
    clearTimeout(zeit);
    fehler = null;
  } catch (e) { fehler = e.name === "AbortError" ? "Zeitüberschreitung" : e.message; }
  laeuftSeit = 0;
  renderWatchlist(T);
}

export function renderWatchlist(T) {
  const box = document.querySelector("#wl"); if (!box) return;
  const sum = document.querySelector("#wl-sum");
  if (fehler && !zeilen.length) { box.innerHTML = `<p class="empty">Watchlist nicht erreichbar: ${fehler}</p>`; return; }
  if (!zeilen.length) { box.innerHTML = '<p class="empty">Lade Kurse&hellip;</p>'; return; }
  const steigend = zeilen.filter((z) => z.change_pct >= 0).length;
  if (sum) sum.textContent = `${steigend} von ${zeilen.length} im Plus (24 h)`;
  box.innerHTML = zeilen.map((z) => {
    const aktiv = z.symbol === T.S.symbol;
    const auf = z.change_pct >= 0;
    return `<button type="button" class="wl__zeile" data-wl="${z.symbol}" aria-current="${aktiv}">
        <b>${z.symbol.replace("USDT", "")}</b>
        <span class="wl__preis">${T.px(z.last)}</span>
        <span class="wl__chg ${auf ? "up" : "down"}">${auf ? "+" : ""}${z.change_pct.toFixed(2)}%</span>
      </button>`;
  }).join("");
}

export function wireWatchlist(T) {
  const box = document.querySelector("#wl"); if (!box) return;
  box.addEventListener("click", (e) => {
    const b = e.target.closest("[data-wl]"); if (!b) return;
    T.setSymbol(b.dataset.wl);
  });
  // Pfeiltasten durch die Liste, wie in jeder Liste.
  box.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const k = [...box.querySelectorAll("[data-wl]")];
    const i = k.indexOf(document.activeElement); if (i < 0) return;
    k[(i + (e.key === "ArrowDown" ? 1 : -1) + k.length) % k.length].focus();
    e.preventDefault();
  });
}
