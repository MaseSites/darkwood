/* The chart behind a proposal.
 *
 * Written rather than imported. A charting library would arrive with its own
 * opinions about axes, its own colours and its own idea of what a price line is,
 * and every overlay here — the risk band, the reward band, the levels the
 * analysis actually named, the bar the decision was made on — would be fought
 * through an API designed for something else. This draws exactly what this
 * screen needs and nothing else, in the palette the rest of the surface already
 * uses, with no network dependency at load.
 *
 * Two things are deliberate and worth stating.
 *
 * THE CHART STOPS AT THE DECISION. The server trims it; nothing here would
 * extend it. A chart running to the present shows the reader what happened next,
 * and then there is nothing left to judge.
 *
 * THE RISK IS SHADED, NOT LABELLED. Entry-to-stop is filled red and
 * entry-to-target green, at their true proportional heights. The ratio between
 * two numbers is something you have to work out; the ratio between two areas is
 * something you see. That is the whole reason this is a chart and not a table.
 *
 * Liquidation is usually far enough below the candles that including it would
 * squash them into a band. When it falls outside the visible range it is pinned
 * to the edge and labelled as off-scale, rather than silently dropped or allowed
 * to flatten everything else.
 */

const CHART = {
  padRight: 78, // price axis
  padBottom: 24, // time axis
  padTop: 10,
  padLeft: 8,
  minCandleWidth: 2,
  wickWidth: 1,
};

const PLAN_COLOUR = {
  entry: "--text",
  stop: "--short",
  target: "--long",
  liquidation: "--liq",
};

/* Level kinds grouped by what they mean, so the eye can sort them without
 * reading every label. Supply and demand read as the two sides; gaps read as
 * structure; everything else is context. */
const LEVEL_TONE = {
  swing_high: "supply",
  equal_highs: "supply",
  range_high: "supply",
  prev_day_high: "context",
  prev_week_high: "context",
  swing_low: "demand",
  equal_lows: "demand",
  range_low: "demand",
  prev_day_low: "context",
  prev_week_low: "context",
  fvg_high: "gap",
  fvg_mid: "gap",
  fvg_low: "gap",
};

/* Structural events. A break of structure and a sweep argue different things,
 * so they do not share a colour: the first is continuation, the second is a
 * reversal of whoever was just stopped out. */
const EVENT_COLOUR = {
  bos: "rgba(96, 165, 250, 0.55)",
  choch: "rgba(232, 121, 249, 0.55)",
  sweep_up: "rgba(248, 113, 113, 0.55)",
  sweep_down: "rgba(52, 211, 153, 0.55)",
};

const EVENT_LABEL = {
  bos: "#93c5fd",
  choch: "#f0abfc",
  sweep_up: "#f8a0a0",
  sweep_down: "#6ee7b7",
};

/* Line and label are separated deliberately. The line is background: it marks a
 * price and should not compete with the candles. The label is text at ten pixels
 * and has to clear the contrast floor, which the line's alpha does not. Using one
 * colour for both means either an unreadable label or a line that shouts. */
const TONE_COLOUR = {
  supply: "rgba(248, 113, 113, 0.5)",
  demand: "rgba(52, 211, 153, 0.5)",
  gap: "rgba(245, 158, 11, 0.42)",
  context: "rgba(124, 138, 163, 0.45)",
};

const TONE_LABEL = {
  supply: "#f8a0a0",
  demand: "#6ee7b7",
  gap: "#fbbf24",
  context: "#9aa8c0",
};

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function niceStep(range, targetLines) {
  /* A price axis with steps of 137 is a price axis nobody reads. Round to 1, 2
   * or 5 times a power of ten — the only step sizes that stay legible when the
   * range changes by an order of magnitude. */
  const raw = range / Math.max(1, targetLines);
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const normalised = raw / magnitude;
  const step = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
  return step * magnitude;
}

function formatPrice(value) {
  const digits = value >= 1000 ? 0 : value >= 10 ? 2 : 4;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatTime(ms, barMs) {
  const date = new Date(ms);
  const opts =
    barMs >= 86400000
      ? { month: "short", day: "2-digit" }
      : { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false };
  return date.toLocaleString("en-GB", { ...opts, timeZone: "UTC" });
}

/* ----------------------------------------------------------------- scale -- */

function priceRange(view) {
  /* Candles set the range; the plan extends it when there is one -- the market
   * view has no trade attached, so `plan` is absent there rather than empty. Liquidation is excluded on
   * purpose — it sits ten stop-distances away and would compress the price
   * action into an unreadable ribbon. It is drawn pinned instead. */
  let low = Infinity;
  let high = -Infinity;
  for (const candle of view.candles) {
    if (candle.low < low) low = candle.low;
    if (candle.high > high) high = candle.high;
  }
  for (const line of view.plan ?? []) {
    if (line.role === "liquidation") continue;
    low = Math.min(low, line.price);
    high = Math.max(high, line.price);
  }
  if (!isFinite(low) || !isFinite(high) || high <= low) return { low: 0, high: 1 };

  /* Levels may widen the view a little, but not set it. A weekly swing well
   * outside the range is useful context and not worth halving the height of
   * every candle for, so the allowance is a fraction of what is already shown
   * rather than a percentage of price — the same rule at any price level. */
  const allowance = (high - low) * 0.15;
  for (const level of view.levels) {
    if (level.price > low - allowance && level.price < high + allowance) {
      low = Math.min(low, level.price);
      high = Math.max(high, level.price);
    }
  }

  const margin = (high - low) * 0.06;
  return { low: low - margin, high: high + margin };
}

/**
 * Nudge labels apart so a cluster of levels stays readable.
 *
 * Four levels within half a percent is common and correct — price returns to the
 * same place. Drawn naively their labels land on top of each other and the
 * cluster becomes less legible than a single line would be. Each label is moved
 * to the nearest free slot; one that cannot be placed inside the plot is
 * dropped, and its line is still drawn, because a line without a name is far
 * better than two names on top of each other.
 */
function placeLabels(entries, top, bottom, lineHeight) {
  const used = [];
  const placed = [];
  for (const entry of entries.slice().sort((a, b) => a.y - b.y)) {
    let y = entry.y - lineHeight * 0.7;
    let attempts = 0;
    while (used.some((taken) => Math.abs(taken - y) < lineHeight) && attempts < 40) {
      y += lineHeight;
      attempts += 1;
    }
    if (y < top + lineHeight || y > bottom - 2) continue;
    used.push(y);
    placed.push({ ...entry, labelY: y });
  }
  return placed;
}

/* ------------------------------------------------------------------ draw -- */

export function drawChart(canvas, view, hover) {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return null;

  if (canvas.width !== width * ratio || canvas.height !== height * ratio) {
    canvas.width = width * ratio;
    canvas.height = height * ratio;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const plotLeft = CHART.padLeft;
  const plotRight = width - CHART.padRight;
  const plotTop = CHART.padTop;
  const plotBottom = height - CHART.padBottom;
  const plotWidth = plotRight - plotLeft;
  const plotHeight = plotBottom - plotTop;
  if (plotWidth < 40 || plotHeight < 40) return null;

  const { low, high } = priceRange(view);
  const span = high - low;
  const y = (price) => plotBottom - ((price - low) / span) * plotHeight;

  const count = view.candles.length || 1;
  const slot = plotWidth / count;
  const bodyWidth = Math.max(CHART.minCandleWidth, Math.floor(slot * 0.68));
  const x = (index) => plotLeft + slot * (index + 0.5);

  const colours = {
    rule: cssVar("--rule") || "#1e2839",
    ruleStrong: cssVar("--rule-strong") || "#2c3a52",
    text: cssVar("--text") || "#e6edf7",
    dim: cssVar("--dim") || "#7c8aa3",
    dimmer: cssVar("--dimmer") || "#4c5a72",
    long: cssVar("--long") || "#34d399",
    short: cssVar("--short") || "#f87171",
    liq: cssVar("--liq") || "#f59e0b",
    panel: cssVar("--panel") || "#0e1420",
  };

  drawGrid(ctx, { plotLeft, plotRight, plotTop, plotBottom, low, high, span, y, colours });
  drawZones(ctx, view, { plotLeft, plotRight, y, colours });
  drawDiagonals(ctx, view, { x, y, plotRight, colours });
  drawBands(ctx, view, { plotLeft, plotRight, y, colours });
  const levelLabels = drawLevels(ctx, view, {
    plotLeft,
    plotRight,
    plotTop,
    plotBottom,
    y,
    colours,
  });
  drawCandles(ctx, view, { x, y, bodyWidth, colours });
  drawLevelLabels(ctx, levelLabels, { plotLeft });
  drawEvents(ctx, view, { x, plotTop, plotBottom, colours });
  drawPlan(ctx, view, { plotLeft, plotRight, plotTop, plotBottom, y, colours });
  drawTimeAxis(ctx, view, { x, count, plotBottom, plotLeft, plotRight, height, colours });

  const geometry = { plotLeft, plotRight, plotTop, plotBottom, slot, x, y, low, high, count };
  if (hover) drawCrosshair(ctx, view, hover, geometry, colours);
  return geometry;
}

function drawGrid(ctx, g) {
  const step = niceStep(g.span, 5);
  const first = Math.ceil(g.low / step) * step;
  ctx.font = '11px ui-monospace, "SF Mono", Menlo, monospace';
  ctx.textBaseline = "middle";

  for (let price = first; price <= g.high; price += step) {
    const py = Math.round(g.y(price)) + 0.5;
    ctx.beginPath();
    ctx.strokeStyle = g.colours.rule;
    ctx.lineWidth = 1;
    ctx.moveTo(g.plotLeft, py);
    ctx.lineTo(g.plotRight, py);
    ctx.stroke();

    ctx.fillStyle = g.colours.dimmer;
    ctx.textAlign = "left";
    ctx.fillText(formatPrice(price), g.plotRight + 8, py);
  }
}

function drawBands(ctx, view, g) {
  /* The point of the whole picture: how much you lose against how much you make,
   * as two areas you can compare at a glance instead of two numbers you have to
   * divide. */
  const byRole = Object.fromEntries((view.plan ?? []).map((line) => [line.role, line.price]));
  if (byRole.entry === undefined) return;

  const band = (from, to, colour) => {
    const top = Math.min(g.y(from), g.y(to));
    const bottom = Math.max(g.y(from), g.y(to));
    ctx.fillStyle = colour;
    ctx.fillRect(g.plotLeft, top, g.plotRight - g.plotLeft, Math.max(1, bottom - top));
  };

  if (byRole.stop !== undefined) band(byRole.entry, byRole.stop, "rgba(248, 113, 113, 0.10)");
  if (byRole.target !== undefined) band(byRole.entry, byRole.target, "rgba(52, 211, 153, 0.10)");
}

/**
 * The price ranges that matter, drawn as ranges.
 *
 * Pools and structural zones have always had two edges -- a pool of equal highs
 * spans the spread between them, a demand zone spans a candle's body. Drawing
 * only a hairline threw that away, and the charts Severin sent all show
 * regions: a band price reacts *in*, not a line it touches.
 *
 * Behind the candles and very faint. A zone is context for the price action,
 * so anything strong enough to compete with the candles is drawn wrongly, and
 * ten of them at full strength would be a wall rather than a chart.
 */
function drawZones(ctx, view, g) {
  const tint = {
    equal_highs: "248, 113, 113",
    equal_lows: "52, 211, 153",
    supply: "248, 113, 113",
    demand: "52, 211, 153",
    order_block_bullish: "52, 211, 153",
    order_block_bearish: "248, 113, 113",
    fvg_bullish: "245, 158, 11",
    fvg_bearish: "245, 158, 11",
  };

  ctx.save();
  for (const band of view.bands ?? []) {
    const top = g.y(band.high);
    const bottom = g.y(band.low);
    const rgb = tint[band.kind] ?? "124, 138, 163";
    ctx.fillStyle = `rgba(${rgb}, 0.10)`;
    // A band thinner than a pixel disappears, and a pool of equal highs is
    // often only a few ticks tall. One pixel is the floor so it stays visible
    // as the thing it is rather than vanishing at this zoom.
    const height = Math.max(1, bottom - top);
    ctx.fillRect(g.plotLeft, top, g.plotRight - g.plotLeft, height);
    ctx.strokeStyle = `rgba(${rgb}, 0.28)`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(g.plotLeft, top);
    ctx.lineTo(g.plotRight, top);
    ctx.moveTo(g.plotLeft, top + height);
    ctx.lineTo(g.plotRight, top + height);
    ctx.stroke();
  }
  ctx.restore();
}

/**
 * Trendlines, drawn from their first anchor to the current bar.
 *
 * Extended rather than stopped at the second anchor: the evidence is where the
 * line was touched, but the useful part is where it sits today, and a segment
 * that ends in the past shows the first and hides the second.
 *
 * Dashed, because a diagonal is drawn by a person from points they chose. A
 * solid line would claim the same standing as the price itself.
 */
function drawDiagonals(ctx, view, g) {
  const lines = view.diagonals ?? [];
  const first = view.candles[0];
  if (!lines.length || !first || !view.bar_ms) return;

  // The anchors are timestamps, the plot speaks in bar positions, and an anchor
  // is usually older than the window shows. Bars are evenly spaced, so the
  // position follows from arithmetic and comes out negative for an anchor off
  // the left edge -- which is exactly where the line should be drawn from.
  const at = (ts) => (ts - first.ts) / view.bar_ms;

  ctx.save();
  ctx.setLineDash([5, 4]);
  ctx.lineWidth = 1;
  for (const line of lines) {
    const from = g.x(at(line.from_ts));
    const to = g.x(at(line.to_ts));
    if (!Number.isFinite(from) || !Number.isFinite(to)) continue;
    ctx.strokeStyle =
      line.kind === "resistance"
        ? "rgba(248, 113, 113, 0.55)"
        : "rgba(52, 211, 153, 0.55)";
    ctx.beginPath();
    ctx.moveTo(from, g.y(line.from_price));
    ctx.lineTo(to, g.y(line.to_price));
    ctx.stroke();
  }
  ctx.restore();
}

function drawLevels(ctx, view, g) {
  ctx.font = '10px ui-monospace, "SF Mono", Menlo, monospace';
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";

  const visible = [];
  for (const level of view.levels) {
    const py = Math.round(g.y(level.price)) + 0.5;
    if (py < g.plotTop || py > g.plotBottom) continue;

    const tone = LEVEL_TONE[level.kind] || "context";
    ctx.save();
    ctx.setLineDash([2, 4]);
    ctx.strokeStyle = TONE_COLOUR[tone];
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(g.plotLeft, py);
    ctx.lineTo(g.plotRight, py);
    ctx.stroke();
    ctx.restore();

    visible.push({ y: py, tone, text: `${level.label} ${level.timeframe}` });
  }

  return placeLabels(visible, g.plotTop, g.plotBottom, 11);
}

/**
 * The level names, drawn after the candles so they are never under one.
 *
 * Each sits on a backing plate: hairline text on a candle body is the one thing
 * on this chart that cannot be read at a glance, and a level nobody can read is
 * a line that only adds noise.
 */
function drawLevelLabels(ctx, labels, g) {
  ctx.font = '10px ui-monospace, "SF Mono", Menlo, monospace';
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  for (const entry of labels) {
    const width = ctx.measureText(entry.text).width;
    ctx.fillStyle = "rgba(6, 9, 16, 0.92)";
    ctx.fillRect(g.plotLeft + 2, entry.labelY - 5.5, width + 6, 11);
    ctx.fillStyle = TONE_LABEL[entry.tone];
    ctx.fillText(entry.text, g.plotLeft + 5, entry.labelY);
  }
}

function drawCandles(ctx, view, g) {
  view.candles.forEach((candle, index) => {
    const up = candle.close >= candle.open;
    const colour = up ? g.colours.long : g.colours.short;
    const cx = Math.round(g.x(index)) + 0.5;

    ctx.strokeStyle = colour;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cx, Math.round(g.y(candle.high)));
    ctx.lineTo(cx, Math.round(g.y(candle.low)));
    ctx.stroke();

    const top = g.y(Math.max(candle.open, candle.close));
    const bottom = g.y(Math.min(candle.open, candle.close));
    const bodyHeight = Math.max(1, bottom - top);
    const left = cx - g.bodyWidth / 2;

    /* Hollow for up, filled for down. It reads faster than colour alone and it
     * still reads when colour does not — about one in twelve men cannot tell
     * this particular green from this particular red. */
    if (up) {
      ctx.strokeStyle = colour;
      ctx.strokeRect(left, top, g.bodyWidth, bodyHeight);
    } else {
      ctx.fillStyle = colour;
      ctx.fillRect(left, top, g.bodyWidth, bodyHeight);
    }
  });
}

/**
 * The structural events, as vertical marks on the time axis.
 *
 * This is what turns "bos: true" into evidence. "There was a break of structure"
 * and "the break was here, price has not come back to it, and the setup is
 * eighteen bars later" are different amounts of argument, and only the second is
 * something a person can disagree with.
 *
 * Labels are written along the line rather than beside it, because a horizontal
 * label at the top of a vertical mark collides with the next one as soon as two
 * events land near each other -- which is exactly when they matter.
 */
function drawEvents(ctx, view, g) {
  if (!view.events?.length) return;
  ctx.font = '10px ui-monospace, "SF Mono", Menlo, monospace';

  view.events.forEach((event, order) => {
    const colour = EVENT_COLOUR[event.kind] || "rgba(124, 138, 163, 0.7)";
    const px = Math.round(g.x(event.bar_index)) + 0.5;

    ctx.save();
    ctx.strokeStyle = colour;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(px, g.plotTop);
    ctx.lineTo(px, g.plotBottom);
    ctx.stroke();
    ctx.restore();

    /* The label gets a backing plate too, for the same reason the level labels
     * do: it runs down the chart and will cross candles. */
    ctx.save();
    ctx.translate(px + 3, g.plotTop + 5 + (order % 2) * 88);
    ctx.rotate(Math.PI / 2);
    const width = ctx.measureText(event.label).width;
    ctx.fillStyle = "rgba(6, 9, 16, 0.9)";
    ctx.fillRect(-2, -6, width + 5, 12);
    ctx.fillStyle = EVENT_LABEL[event.kind] || "#9aa8c0";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(event.label, 1, 0);
    ctx.restore();
  });
}

function drawPlan(ctx, view, g) {
  ctx.font = '11px ui-monospace, "SF Mono", Menlo, monospace';
  ctx.textBaseline = "middle";

  for (const line of view.plan ?? []) {
    const colour = g.colours[
      { entry: "text", stop: "short", target: "long", liquidation: "liq" }[line.role] || "text"
    ];
    let py = g.y(line.price);
    const offScale = py < g.plotTop || py > g.plotBottom;
    if (offScale) py = py < g.plotTop ? g.plotTop + 0.5 : g.plotBottom - 0.5;
    py = Math.round(py) + 0.5;

    ctx.save();
    ctx.strokeStyle = colour;
    ctx.lineWidth = line.role === "entry" ? 1.5 : 1;
    if (offScale) ctx.setLineDash([1, 3]);
    else if (line.role !== "entry") ctx.setLineDash([6, 3]);
    ctx.beginPath();
    ctx.moveTo(g.plotLeft, py);
    ctx.lineTo(g.plotRight, py);
    ctx.stroke();
    ctx.restore();

    /* The tag sits in the price gutter, where it cannot cover a candle. */
    const text = offScale ? `${line.label} ↓` : line.label;
    const tagWidth = ctx.measureText(text).width + 10;
    ctx.fillStyle = colour;
    ctx.fillRect(g.plotRight + 2, py - 8, tagWidth, 16);
    ctx.fillStyle = g.colours.panel;
    ctx.textAlign = "left";
    ctx.fillText(text, g.plotRight + 7, py);
  }
}

function drawTimeAxis(ctx, view, g) {
  if (!view.candles.length) return;
  ctx.font = '10px ui-monospace, "SF Mono", Menlo, monospace';
  ctx.fillStyle = g.colours.dimmer;
  ctx.textBaseline = "top";

  const wanted = Math.max(2, Math.floor((g.plotRight - g.plotLeft) / 110));
  const stride = Math.max(1, Math.floor(g.count / wanted));
  for (let index = 0; index < g.count; index += stride) {
    const label = formatTime(view.candles[index].ts, view.bar_ms);
    ctx.textAlign = "center";
    const px = g.x(index);
    if (px < g.plotLeft + 20 || px > g.plotRight - 20) continue;
    ctx.fillText(label, px, g.plotBottom + 7);
  }

  ctx.textAlign = "right";
  ctx.fillStyle = g.colours.dim;
  ctx.fillText("Entscheidung →", g.plotRight - 2, g.plotBottom + 7);
}

function drawCrosshair(ctx, view, hover, g, colours) {
  const index = Math.max(0, Math.min(g.count - 1, Math.floor((hover.x - g.plotLeft) / g.slot)));
  const candle = view.candles[index];
  if (!candle) return;

  const px = Math.round(g.x(index)) + 0.5;
  const py = Math.round(Math.max(g.plotTop, Math.min(g.plotBottom, hover.y))) + 0.5;
  const price = g.low + ((g.plotBottom - py) / (g.plotBottom - g.plotTop)) * (g.high - g.low);

  ctx.save();
  ctx.setLineDash([2, 3]);
  ctx.strokeStyle = colours.ruleStrong;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(px, g.plotTop);
  ctx.lineTo(px, g.plotBottom);
  ctx.moveTo(g.plotLeft, py);
  ctx.lineTo(g.plotRight, py);
  ctx.stroke();
  ctx.restore();

  ctx.font = '11px ui-monospace, "SF Mono", Menlo, monospace';
  const text = formatPrice(price);
  const tagWidth = ctx.measureText(text).width + 10;
  ctx.fillStyle = colours.ruleStrong;
  ctx.fillRect(g.plotRight + 2, py - 8, tagWidth, 16);
  ctx.fillStyle = colours.text;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(text, g.plotRight + 7, py);

  return { index, candle, price };
}

export function candleReadout(view, index) {
  const candle = view.candles[index];
  if (!candle) return "";
  const change = ((candle.close - candle.open) / candle.open) * 100;
  return [
    formatTime(candle.ts, view.bar_ms),
    `O ${formatPrice(candle.open)}`,
    `H ${formatPrice(candle.high)}`,
    `L ${formatPrice(candle.low)}`,
    `C ${formatPrice(candle.close)}`,
    `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`,
  ].join("   ");
}
