/* Der Chart eines LAUFENDEN Trades. Interaktiv, und das ist der Unterschied.
 *
 * `chart.js` daneben zeichnet einen VORSCHLAG und hoert bei der Entscheidung
 * auf -- sein Kopf nennt das eine Integritaetseigenschaft, und sie stimmt:
 * ein Chart, der bis zur Gegenwart laeuft, zeigt dem Leser, was danach
 * passiert ist, und dann ist nichts mehr zu beurteilen.
 *
 * Fuer einen laufenden Trade gilt genau das Gegenteil. Dort MUSS man sehen,
 * wo der Kurs jetzt steht, wie weit der Stop noch weg ist und ob sich die
 * Struktur seit dem Einstieg gedreht hat. Darum zwei Renderer und nicht
 * einer, und darum hier TradingViews eigene Engine statt handgezeichnetem
 * SVG.
 *
 * Was vorher da war und was daran nicht ging:
 *
 *   90 Kerzen, fest             -- kein Zoom, kein Schwenken, kein Weiterlesen
 *   statisches SVG via innerHTML -- alle 15 s komplett neu gezeichnet
 *   kein Fadenkreuz              -- "welcher Kurs ist das da?" unbeantwortbar
 *   keine Einstiegsmarke         -- nur ein Zeitstempel in der Fussnote
 *   eine Zeitebene               -- dieselbe Bewegung auf H1 war nicht zu sehen
 *
 * Und der Grund, warum das Neuzeichnen allein schon falsch war: wer
 * hineingezoomt hat und 15 Sekunden spaeter seinen Ausschnitt verliert, kann
 * einen Chart nicht lesen. Diese Datei haelt den Ausschnitt fest und
 * schreibt nur die rechte Kante fort.
 */

import {
  CandlestickSeries,
  CrosshairMode,
  LineStyle,
  createChart,
  createSeriesMarkers,
} from "/static/vendor/lightweight-charts.mjs";

/* Dieselben Farben wie der Rest der Seite, aus den Variablen gelesen statt
 * doppelt gepflegt. Eine Bibliothek, die ihre eigene Palette mitbringt, sieht
 * in jedem Theme nach Fremdkoerper aus. */
function token(name, fallback) {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return value || fallback;
}

/* Wie viele Nachkommastellen der Markt braucht.
 *
 * Aus den Kursen selbst abgeleitet und nicht geraten: BTC bei 112.000 braucht
 * zwei, DOGE bei 0,19 braucht fuenf, und eine feste Zahl ist fuer den einen
 * Rauschen und fuer den anderen eine Luege. */
function precisionFor(candles) {
  const last = candles.length ? candles[candles.length - 1].close : 1;
  if (last >= 1000) return 2;
  if (last >= 100) return 3;
  if (last >= 1) return 4;
  if (last >= 0.01) return 5;
  return 8;
}

function bars(candles) {
  return candles.map((c) => ({
    /* Die Bibliothek rechnet in Sekunden, dieses Projekt durchgehend in
     * Millisekunden. Die Umrechnung steht an genau dieser Stelle, damit sie
     * nicht an fuenf verteilten Stellen halb passiert. */
    time: Math.floor(c.ts / 1000),
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));
}

const FMT = new Intl.NumberFormat("de-CH", { maximumFractionDigits: 8 });

function price(value, digits) {
  return value.toLocaleString("de-CH", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function clock(ms) {
  return new Date(ms).toLocaleString("de-CH", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
}

/* Jeder offene Trade bekommt genau eine Instanz, und die lebt, bis der Trade
 * zu ist oder das Panel verschwindet. Ohne dieses Register wuerde jeder
 * Abruf einen weiteren Chart in denselben Container bauen -- zwoelf Charts
 * auf zwoelf Panels, und der Browser wird langsam, ohne dass etwas kaputt
 * aussieht. */
const live = new Map();

export function disposePositionChart(symbol) {
  const held = live.get(symbol);
  if (!held) return;
  held.observer?.disconnect();
  held.chart.remove();
  live.delete(symbol);
}

export function disposeAllPositionCharts() {
  for (const symbol of [...live.keys()]) disposePositionChart(symbol);
}

/* Die drei Linien, die den Trade entscheiden, plus die vierte, die ihn
 * beendet.
 *
 * Als Preislinien der Bibliothek und nicht als gezeichnete Striche: dann
 * tragen sie ihr eigenes Achsenschild, bleiben beim Zoomen an ihrem Kurs und
 * verrutschen nicht um einen halben Pixel, wenn man schwenkt. */
function planLines(series, chart, digits) {
  const lines = [
    { key: "target", price: chart.target, color: token("--long", "#34d399"),
      title: `Ziel ${price(chart.target, digits)}` },
    { key: "entry", price: chart.entry, color: token("--text", "#e6edf7"),
      title: `Entry ${price(chart.entry, digits)}` },
    { key: "stop", price: chart.stop, color: token("--short", "#f87171"),
      title: `Stop ${price(chart.stop, digits)}` },
  ];
  /* Die Liquidation nur, wenn sie ueberhaupt in Reichweite der Kerzen liegt.
   * Bei 3x Hebel steht sie 30 % weg; sie mit einzuzeichnen wuerde die
   * Preisachse so weit aufziehen, dass die Kerzen zu einem Band
   * zusammenschrumpfen -- und dann waere der Chart schlechter geworden. */
  if (chart.liquidation > 0 && chart.candles.length) {
    const lows = chart.candles.map((c) => c.low);
    const highs = chart.candles.map((c) => c.high);
    const span = Math.max(...highs) - Math.min(...lows);
    const outside =
      chart.liquidation > Math.max(...highs) + span * 0.25 ||
      chart.liquidation < Math.min(...lows) - span * 0.25;
    if (!outside) {
      lines.push({
        key: "liq", price: chart.liquidation, color: token("--liq", "#f59e0b"),
        title: `Liquidation ${price(chart.liquidation, digits)}`,
      });
    }
  }
  return lines.map((line) =>
    series.createPriceLine({
      price: line.price,
      color: line.color,
      lineWidth: line.key === "entry" ? 1 : 2,
      lineStyle: line.key === "entry" ? LineStyle.Dashed : LineStyle.Solid,
      axisLabelVisible: true,
      title: line.title,
    }),
  );
}

/* Wo genau eingestiegen wurde.
 *
 * Auf der Kerze, in die der Einstieg fiel, und nicht auf der ersten
 * gezeichneten: ein Trade kann Tage laufen, und "irgendwo links" ist keine
 * Antwort auf "wo sind wir rein". */
function entryMarker(chart) {
  const opened = Math.floor(chart.opened_ts / 1000);
  const step = Math.max(1, Math.floor(chart.bar_ms / 1000));
  /* Auf den Kerzenbeginn gerundet, weil die Bibliothek eine Marke nur an
   * einem Zeitpunkt kennt, den die Reihe auch hat. */
  const slot = Math.floor(opened / step) * step;
  const long = chart.side.toLowerCase().includes("long");
  return [{
    time: slot,
    position: long ? "belowBar" : "aboveBar",
    shape: long ? "arrowUp" : "arrowDown",
    color: long ? token("--long", "#34d399") : token("--short", "#f87171"),
    text: `${long ? "Long" : "Short"} ${FMT.format(chart.qty)}`,
  }];
}

function readoutRow(label, value, extra = "") {
  return `<span class="pchart__cell ${extra}">
    <span class="pchart__key">${label}</span>
    <span class="pchart__val">${value}</span></span>`;
}

function shell(chart, digits) {
  const switcher = chart.timeframes
    .map((tf) => {
      const on = tf === chart.timeframe;
      const home = tf === chart.setup_timeframe ? " pchart__tf--home" : "";
      return `<button type="button" class="pchart__tf${home}${on ? " is-on" : ""}"
        data-tf="${tf}" aria-pressed="${on}"
        ${home ? 'title="Die Zeitebene, auf der das Setup gefunden wurde"' : ""}
        >${tf}</button>`;
    })
    .join("");
  const long = chart.side.toLowerCase().includes("long");
  return `
    <div class="pchart" data-symbol="${chart.symbol}">
      <div class="pchart__bar">
        <span class="pchart__side ${long ? "is-long" : "is-short"}">
          ${long ? "Long" : "Short"}</span>
        <span class="pchart__tfs" role="group"
              aria-label="Zeitebene">${switcher}</span>
        <output class="pchart__readout" aria-live="off"></output>
      </div>
      <div class="pchart__canvas"></div>
      <p class="pchart__foot">
        <span class="pchart__hint">Rad zoomt &middot; ziehen schwenkt &middot;
          Doppelklick zur&uuml;ck zum Trade</span>
        <span class="pchart__meta">${chart.candles.length} ${chart.timeframe}-Kerzen
          &middot; Einstieg ${clock(chart.opened_ts)} UTC
          &middot; Hebel ${FMT.format(chart.leverage)}x
          &middot; Risiko ${price(chart.risk_amount, 2)} USDT</span>
      </p>
    </div>`;
}

/* Das Fadenkreuz beantwortet "welche Kerze ist das".
 *
 * Und es beantwortet eine zweite Frage, die der alte Chart gar nicht stellen
 * konnte: wie weit ist dieser Kurs vom Stop weg, in R. Das ist die Einheit,
 * in der dieses Projekt rechnet, und sie am Chart ablesen zu koennen ist der
 * eigentliche Gewinn gegenueber einem Bild. */
function crosshair(host, series, data, digits) {
  const out = host.querySelector(".pchart__readout");
  const risk = Math.abs(data.entry - data.stop);
  const long = data.side.toLowerCase().includes("long");
  /* Der Beginn der Kerze, in die der Einstieg fiel -- dieselbe Rundung wie
   * bei der Einstiegsmarke, damit beide dieselbe Kerze meinen. */
  const openedSlot = Math.floor(data.opened_ts / data.bar_ms) * data.bar_ms;
  const idle = readoutRow("", "Zeiger auf eine Kerze", "pchart__cell--idle");
  out.innerHTML = idle;
  return (param) => {
    /* Nach der Reihe gefragt, nicht "das erste, was in der Map liegt". Mit
     * einer Reihe ist beides gleich; mit zwei waere das zweite ein Fehler,
     * der erst auffaellt, wenn jemand ein Volumen-Histogramm ergaenzt. */
    const bar = param.time ? param.seriesData?.get(series) : undefined;
    if (!bar) {
      out.innerHTML = idle;
      return;
    }
    const up = bar.close >= bar.open;
    const cells = [
      readoutRow("", clock(param.time * 1000), "pchart__cell--time"),
      readoutRow("O", price(bar.open, digits)),
      readoutRow("H", price(bar.high, digits)),
      readoutRow("T", price(bar.low, digits)),
      readoutRow("C", price(bar.close, digits), up ? "is-long" : "is-short"),
    ];
    /* R nur AB dem Einstieg.
     *
     * Davor waere es die Antwort auf eine Frage, die niemand gestellt hat --
     * "was waere das in R, wenn der Trade damals schon gelaufen waere" --
     * und sie sieht aus wie eine Messung. Die erste Fassung zeigte an einer
     * Kerze vom 21.08. ein sauberes "+1.32 R" fuer einen Trade, der am
     * 11.10. eroeffnet wurde. */
    if (param.time * 1000 >= openedSlot && risk > 0) {
      const r = (bar.close - data.entry) * (long ? 1 : -1) / risk;
      cells.push(readoutRow("R", `${r >= 0 ? "+" : ""}${r.toFixed(2)}`,
                            r >= 0 ? "is-long" : "is-short"));
    }
    out.innerHTML = cells.join("");
  };
}

/* Welcher Ausschnitt beim Oeffnen zu sehen ist.
 *
 * NICHT `fitContent`, und das ist hier gemessen und nicht gemeint: 1.500
 * D1-Kerzen sind vier Jahre, und `fitContent` quetscht den laufenden Trade
 * damit in die letzten zwei Prozent der Breite. Die Preisachse spannt dann
 * von 0,19 bis 1,60, die Planlinien kleben uebereinander, und genau die
 * Frage, fuer die es diesen Chart gibt -- wie weit ist der Kurs noch vom Stop
 * weg -- ist nicht mehr abzulesen. Das waere derselbe Fehler wie die 90 festen
 * Kerzen vorher, nur von der anderen Seite.
 *
 * Also: der Ausschnitt haengt am TRADE. Mindestens 90 Balken, und immer
 * genug, dass der Einstieg bequem drin liegt. Die vollen 1.500 bleiben da,
 * einen Wisch nach links entfernt -- das ist der Unterschied zwischen
 * "kleines Fenster" und "kleiner Datensatz". */
function openOnTheTrade(chart, data, count) {
  const sinceEntry = Math.max(0, Math.round((Date.now() - data.opened_ts) / data.bar_ms));
  const want = Math.min(count, Math.max(90, Math.ceil(sinceEntry * 1.6) + 20));
  chart.timeScale().setVisibleLogicalRange({
    from: Math.max(0, count - want),
    /* Etwas Luft rechts, damit die letzte Kerze nicht am Achsenrand klebt
     * und die neue Kerze irgendwo hin wachsen kann. */
    to: count + 5,
  });
}

/* Der Aufbau. Einmal je Trade.
 *
 * Gibt das Objekt zurueck, mit dem `update` spaeter weiterarbeitet -- die
 * Reihe, die Linien und der zuletzt eingetragene Balken. */
function build(host, data) {
  host.innerHTML = shell(data, precisionFor(data.candles));
  const root = host.querySelector(".pchart");
  const canvas = root.querySelector(".pchart__canvas");
  const digits = precisionFor(data.candles);

  const chart = createChart(canvas, {
    layout: {
      background: { color: "transparent" },
      textColor: token("--dim", "#9badcc"),
      fontFamily: token("--mono", "ui-monospace, monospace"),
      fontSize: 11,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: token("--rule", "#1e2839"), style: LineStyle.Dotted },
      horzLines: { color: token("--rule", "#1e2839"), style: LineStyle.Dotted },
    },
    rightPriceScale: {
      borderColor: token("--rule-strong", "#2c3a52"),
      scaleMargins: { top: 0.12, bottom: 0.12 },
    },
    timeScale: {
      borderColor: token("--rule-strong", "#2c3a52"),
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 6,
    },
    crosshair: {
      /* Normal, nicht Magnet: der Magnet springt auf den naechsten
       * Schlusskurs, und dann liest man nicht mehr ab, wo der Zeiger ist,
       * sondern wo die Bibliothek ihn gern haette. */
      mode: CrosshairMode.Normal,
      vertLine: { color: token("--rule-strong", "#2c3a52"), labelBackgroundColor: token("--panel-high", "#141c2b") },
      horzLine: { color: token("--rule-strong", "#2c3a52"), labelBackgroundColor: token("--panel-high", "#141c2b") },
    },
    localization: {
      locale: "de-CH",
      priceFormatter: (value) => price(value, digits),
    },
    autoSize: false,
    height: 360,
    handleScale: { axisPressedMouseMove: { time: true, price: false } },
  });

  const series = chart.addSeries(CandlestickSeries, {
    upColor: token("--long", "#34d399"),
    downColor: token("--short", "#f87171"),
    borderUpColor: token("--long", "#34d399"),
    borderDownColor: token("--short", "#f87171"),
    wickUpColor: token("--long", "#34d399"),
    wickDownColor: token("--short", "#f87171"),
    priceFormat: { type: "price", precision: digits, minMove: 10 ** -digits },
  });

  const rows = bars(data.candles);
  series.setData(rows);
  const markers = createSeriesMarkers(series, entryMarker(data));
  const lines = planLines(series, data, digits);
  openOnTheTrade(chart, data, rows.length);
  chart.subscribeCrosshairMove(crosshair(root, series, data, digits));
  /* Doppelklick zurueck auf den Trade, nicht auf die vollen vier Jahre.
   *
   * Die Bibliothek setzt von sich aus auf `fitContent` zurueck, und das ist
   * hier der Ausschnitt, in dem man nichts erkennt. Ein Zuruecksetzen, das in
   * einer schlechteren Ansicht endet als der Ausgangszustand, ist kein
   * Zuruecksetzen. */
  chart.subscribeDblClick(() => openOnTheTrade(chart, data, rows.length));

  /* Die Breite kommt vom Panel, und das Panel klappt auf und zu. Ohne diesen
   * Beobachter waere der Chart genau so breit wie im Moment des Aufbaus --
   * also bei einem noch zugeklappten Panel: null. */
  const observer = new ResizeObserver(([entry]) => {
    const width = Math.floor(entry.contentRect.width);
    if (width > 0) chart.applyOptions({ width });
  });
  observer.observe(canvas);

  const held = {
    chart, series, markers, lines, observer, root,
    digits,
    last: rows.length ? rows[rows.length - 1] : null,
    timeframe: data.timeframe,
    barMs: data.bar_ms,
  };
  live.set(data.symbol, held);
  return held;
}

/* Die rechte Kante fortschreiben, ohne den Ausschnitt anzufassen.
 *
 * `series.update` ersetzt genau einen Balken, also bleibt Zoom, Schwenkung
 * und Fadenkreuz, wo sie waren. Das ist der Unterschied zum alten
 * `innerHTML`-Neuzeichnen alle 15 Sekunden, bei dem jeder Zoom verloren war.
 */
function advance(held, tick) {
  if (!tick.last_price || !tick.last_minute_ts || !held.last) return;
  const step = Math.max(1, Math.floor(held.barMs / 1000));
  const slot = Math.floor(Math.floor(tick.last_minute_ts / 1000) / step) * step;
  if (slot < held.last.time) return;
  if (slot === held.last.time) {
    const bar = {
      time: slot,
      open: held.last.open,
      high: Math.max(held.last.high, tick.last_price),
      low: Math.min(held.last.low, tick.last_price),
      close: tick.last_price,
    };
    held.series.update(bar);
    held.last = bar;
    return;
  }
  /* Eine neue Kerze, die der Speicher noch nicht geschrieben hat. Sie wird
   * als eigener Balken eroeffnet und nicht an den alten geklebt -- sonst
   * waere der letzte Balken eine Mischung aus zwei Zeitabschnitten. */
  const bar = {
    time: slot,
    open: tick.last_price,
    high: tick.last_price,
    low: tick.last_price,
    close: tick.last_price,
  };
  held.series.update(bar);
  held.last = bar;
}

/* Die rechte Kante fortschreiben, aus Daten, die der Aufrufer schon hat.
 *
 * Bewusst OHNE Abruf. Der Trade-Poll holt alle 15 Sekunden ohnehin
 * `last_price` und `last_minute_ts` -- dafuer noch einmal 1.500 Kerzen zu
 * laden waere 90 KB je Chart und Poll, um zwei Zahlen zu erfahren, die schon
 * auf dem Tisch liegen.
 *
 * `{last_price, last_minute_ts}` ist genau die Form, die `OpenTrade`
 * liefert, also kann der Aufrufer die Zeile direkt durchgeben. */
export function advancePositionChart(symbol, tick) {
  const held = live.get(symbol);
  if (!held || !tick) return false;
  /* Ein Chart, dessen Rahmen nicht mehr im Dokument haengt, ist kein Chart
   * mehr. Das passiert, wenn die Liste neu gebaut wurde, ohne ihn
   * mitzunehmen -- dann wird aufgeraeumt statt auf ein Element gezeichnet,
   * das niemand sieht. */
  if (!held.root.isConnected) {
    disposePositionChart(symbol);
    return false;
  }
  advance(held, tick);
  return true;
}

export function hasPositionChart(symbol) {
  const held = live.get(symbol);
  if (!held) return false;
  if (!held.root.isConnected) {
    disposePositionChart(symbol);
    return false;
  }
  return true;
}

export function livePositionCharts() {
  return [...live.keys()];
}

/* Der Aufbau. Einmal je Trade, danach genuegt `advancePositionChart`.
 *
 * `fetcher(symbol, timeframe)` holt die Daten -- hereingegeben statt hier
 * verdrahtet, damit diese Datei nichts ueber die API-Pfade des Dashboards
 * wissen muss und in einem Test mit einem Stub laeuft. */
export async function renderPositionChart(host, symbol, fetcher) {
  if (hasPositionChart(symbol)) return;

  host.innerHTML = `<div class="placeholder"><span class="pulse"></span>
    <p>Lese Kerzen&hellip;</p></div>`;
  let data;
  try {
    data = await fetcher(symbol, null);
  } catch {
    host.innerHTML = `<p class="konto__state">Chart nicht lesbar.</p>`;
    return;
  }
  if (!data || !data.candles?.length) {
    host.innerHTML = `<p class="konto__state">Keine Kerzen f&uuml;r diesen Trade.</p>`;
    return;
  }

  /* Haengt der Container ueberhaupt noch im Dokument?
   *
   * Zwischen dem Abruf oben und dieser Zeile liegt ein `await`, und in dieser
   * Luecke kann der 15-Sekunden-Poll die ganze Liste neu gebaut haben. Dann
   * ist `host` ein losgeloestes Element: der Chart wuerde hineingebaut, die
   * Knoepfe bekaemen ihre Zuhoerer, und niemand saehe davon je etwas -- ein
   * Chart, der da ist und auf nichts reagiert. Genau dieses Bild war beim
   * ersten Durchlauf im Browser zu sehen.
   *
   * Abbrechen statt irgendwohin zeichnen. Der naechste Poll ruft hier ohnehin
   * wieder an, und dann mit einem Container, den es noch gibt. */
  if (!host.isConnected) return;

  wire(host, symbol, fetcher, build(host, data));
}

/* Die Verdrahtung der Zeitebenen-Knoepfe.
 *
 * Nach jedem Wechsel erneut, weil der Rahmen mit seinen Knoepfen neu gebaut
 * wird -- `build` schreibt `host.innerHTML`, und damit sind die alten Knoepfe
 * samt ihren Zuhoerern weg. Einmal verdrahten und auf Weiterleben hoffen
 * waere der Fehler, der nach dem ersten Wechsel aussieht wie ein toter Knopf.
 */
function wire(host, symbol, fetcher, built) {
  built.root.querySelectorAll("[data-tf]").forEach((button) => {
    button.addEventListener("click", () => switchTimeframe(host, symbol, fetcher, button));
  });
}

async function switchTimeframe(host, symbol, fetcher, button) {
  const tf = button.dataset.tf;
  if (tf === live.get(symbol)?.timeframe) return;
  let next;
  try {
    next = await fetcher(symbol, tf);
  } catch {
    /* Eine Ebene ohne Daten antwortet 404. Dann bleibt der vorhandene Chart
     * stehen und der Knopf wird stillgelegt -- besser als ein leerer Rahmen
     * an der Stelle, an der gerade noch ein Chart war. */
    button.disabled = true;
    button.title = "Für diesen Markt liegen auf dieser Ebene keine Kerzen";
    return;
  }
  if (!next || !next.candles?.length) {
    button.disabled = true;
    return;
  }
  /* Dieselbe Luecke wie beim Aufbau: zwischen Klick und Antwort kann die
   * Liste neu gebaut worden sein. */
  if (!host.isConnected) return;
  disposePositionChart(symbol);
  wire(host, symbol, fetcher, build(host, next));
}
