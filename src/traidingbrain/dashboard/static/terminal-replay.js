/**
 * Bar Replay: die Vergangenheit Kerze fuer Kerze abspielen.
 *
 * **Was im Replay ausgeblendet wird, und warum.** Zonen, Pools, Struktur,
 * Trendlinien, Setups, Orderbuch, Volumenprofil, grosse Trades und
 * Options-Strikes kommen vom Server und wurden mit dem HEUTIGEN Wissen
 * berechnet. Eine Zone, die erst morgen entsteht, stuende im Replay schon
 * heute da -- der Rueckblick wuesste die Zukunft. Im Replay bleiben darum nur
 * die Kerzen und die Indikatoren, die der Browser aus genau diesen Kerzen
 * rechnet. Positionen und Alarme sind Gegenwart und fehlen ebenfalls.
 *
 * Ablauf wie bei TradingView: Replay waehlen, in den Chart klicken (dort
 * beginnt es), dann abspielen oder schrittweise vor. "Zur Echtzeit" beendet.
 */

const TEMPO = [1, 3, 10];      // Kerzen je Sekunde

let uhr = null;

export function replayAktiv(S) { return !!S.replay; }

/** Kerzen und Sicht fuer den Chart, wenn Replay laeuft. */
export function replaySchnitt(S, kerzen, sicht) {
  const r = S.replay;
  if (!r || r.phase === "waehlen" || r.cut == null) return null;
  return {
    candles: kerzen.slice(0, r.cut + 1),
    view: { ...sicht, bands: [], diagonals: [], events: [], setups: [] },
  };
}

export function replayLeisteMarkup(S) {
  const r = S.replay;
  if (!r) return "";
  if (r.phase === "waehlen") {
    return `<span class="rp__marke">Replay</span>
      <span class="rp__text">In den Chart klicken: dort beginnt das Replay.</span>
      <button type="button" data-rp="ende">Abbrechen</button>`;
  }
  const laeuft = r.phase === "laeuft";
  return `<span class="rp__marke">Replay</span>
    <button type="button" data-rp="spiel" aria-label="${laeuft ? "Anhalten" : "Abspielen"}" title="${laeuft ? "Anhalten" : "Abspielen"}">${laeuft
      ? '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3.5 2.5v7M8.5 2.5v7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'
      : '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3.5 2.2 9.8 6l-6.3 3.8z" fill="currentColor"/></svg>'}</button>
    <button type="button" data-rp="schritt" title="Nächste Kerze (Umschalt+→)">
      <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 2.2 7.5 6l-5 3.8zM9.5 2.5v7" fill="currentColor" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg></button>
    <div class="rp__tempo" role="radiogroup" aria-label="Tempo">${TEMPO.map((t) =>
      `<button type="button" role="radio" data-rp-tempo="${t}" aria-checked="${r.tempo === t}">${t}×</button>`).join("")}</div>
    <button type="button" data-rp="neu" title="Neuen Startpunkt wählen">Startpunkt</button>
    <span class="rp__text">${r.hinweis ?? "Zonen, Struktur und Setups sind ausgeblendet — der Server kennt die Zukunft."}</span>
    <button type="button" class="rp__ende" data-rp="ende">Zur Echtzeit</button>`;
}

function anhalten(S) { if (uhr) { clearInterval(uhr); uhr = null; } if (S.replay?.phase === "laeuft") S.replay.phase = "pause"; }

/** Eine Kerze weiter. false, wenn kein Replay laeuft. */
export function replaySchritt(S, gesamt) {
  const r = S.replay;
  if (!r || r.cut == null) return false;
  if (r.cut >= gesamt - 1) { anhalten(S); r.hinweis = "Echtzeit erreicht — keine weitere Kerze."; return true; }
  r.cut += 1;
  return true;
}

export function replayStart(S) { anhalten(S); S.replay = { phase: "waehlen", cut: null, tempo: 1 }; }
export function replayEnde(S) { anhalten(S); S.replay = null; }

/** Klick in den Chart waehrend "waehlen". */
export function replayWaehle(S, index) {
  if (S.replay?.phase !== "waehlen") return false;
  S.replay = { phase: "pause", cut: Math.max(20, index), tempo: S.replay.tempo ?? 1 };
  return true;
}

export function wireReplay(T) {
  const leiste = document.querySelector("#replay-leiste");
  leiste.addEventListener("click", (e) => {
    const S = T.S, r = S.replay; if (!r) return;
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.rpTempo) {
      r.tempo = +b.dataset.rpTempo;
      if (r.phase === "laeuft") { anhalten(S); starte(T); }
    } else if (b.dataset.rp === "ende") replayEnde(S);
    else if (b.dataset.rp === "neu") replayStart(S);
    else if (b.dataset.rp === "schritt") { anhalten(S); replaySchritt(S, T.gesamt()); }
    else if (b.dataset.rp === "spiel") { if (r.phase === "laeuft") anhalten(S); else starte(T); }
    T.nachReplay();
  });
}

function starte(T) {
  const S = T.S;
  S.replay.phase = "laeuft"; S.replay.hinweis = null;
  uhr = setInterval(() => {
    if (!S.replay) { anhalten(S); return; }
    replaySchritt(S, T.gesamt());
    T.nachReplay();
  }, 1000 / (S.replay.tempo ?? 1));
}
