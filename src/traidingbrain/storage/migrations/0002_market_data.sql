-- The collector's landing zone: what a machine that never sleeps writes down.
--
-- These four tables mirror the four Parquet schemas in data/ exactly -- same
-- columns, same units, same millisecond timestamps. Mirrored rather than
-- improved on, for the same reason 0001 translated the SQLite proposal schema
-- instead of redesigning it: while both exist they have to agree, and a schema
-- that is merely better is one whose differences have to be reasoned about at
-- every call site.
--
-- **This is not the archive.** The Parquet store keeps the history -- 244 MB and
-- five years of it -- and the backtest reads from there. What Postgres adds is
-- the thing Parquet cannot do: a collector on one machine writing while a
-- dashboard on another reads. So this holds what the collector has gathered and
-- the laptop has not yet drained into Parquet, and a sync empties it forward.
-- Two stores, one direction, no ambiguity about which one is right.
--
-- **Every table upserts on its natural key.** A collector restarts, re-fetches an
-- overlapping window and writes it again -- that is the normal case, not the
-- exceptional one, because the alternative is a collector that trusts its own
-- last-seen marker across a crash. Overlap costs a few redundant rows; a gap
-- costs a hole in the history that only surfaces months later in a backtest.

-- Candles. One row per symbol, timeframe and bar close.
CREATE TABLE IF NOT EXISTS ohlcv (
    symbol     TEXT             NOT NULL,
    timeframe  TEXT             NOT NULL,
    -- Bar OPEN time in milliseconds, matching the Parquet store and ccxt.
    ts         BIGINT           NOT NULL,
    open       DOUBLE PRECISION NOT NULL,
    high       DOUBLE PRECISION NOT NULL,
    low        DOUBLE PRECISION NOT NULL,
    close      DOUBLE PRECISION NOT NULL,
    volume     DOUBLE PRECISION NOT NULL,

    PRIMARY KEY (symbol, timeframe, ts)
);

-- Serves the sync's only query: everything newer than what Parquet already has.
CREATE INDEX IF NOT EXISTS ohlcv_by_ts ON ohlcv (ts);

-- Funding settlements. One row per symbol and settlement time.
--
-- Eight-hourly rather than per-bar, so this stays small -- about a thousand rows
-- per symbol per year.
CREATE TABLE IF NOT EXISTS funding (
    symbol  TEXT             NOT NULL,
    ts      BIGINT           NOT NULL,
    rate    DOUBLE PRECISION NOT NULL,

    PRIMARY KEY (symbol, ts)
);

-- Open interest. One row per symbol, interval and reading.
--
-- `interval` is the venue's own spelling ('5min', '1h', '4h', ...) and not a
-- Timeframe: these endpoints accept a different set than the candle endpoint
-- does, which is why data/derivatives.py spells the accepted values out rather
-- than deriving them. Storing the venue's string keeps that honest.
CREATE TABLE IF NOT EXISTS open_interest (
    symbol         TEXT             NOT NULL,
    interval       TEXT             NOT NULL,
    ts             BIGINT           NOT NULL,
    open_interest  DOUBLE PRECISION NOT NULL,

    PRIMARY KEY (symbol, interval, ts)
);

-- Which way the crowd leans. One row per symbol, interval and reading.
--
-- Both sides are stored even though they sum to one. The venue reports both, and
-- deriving the second would mean this table quietly disagrees with the source
-- the day a venue rounds them differently.
CREATE TABLE IF NOT EXISTS long_short_ratio (
    symbol      TEXT             NOT NULL,
    interval    TEXT             NOT NULL,
    ts          BIGINT           NOT NULL,
    buy_ratio   DOUBLE PRECISION NOT NULL,
    sell_ratio  DOUBLE PRECISION NOT NULL,

    PRIMARY KEY (symbol, interval, ts)
);

-- What the collector did, and when it last succeeded.
--
-- The reason this table exists is the failure it makes visible. A collector that
-- dies at 03:00 and is noticed at the next backtest has already written a hole
-- into the history, and a hole is indistinguishable from a quiet market unless
-- something recorded that nobody was looking. One row per series, overwritten on
-- every successful pass: "last_ok_ts far in the past" is then a question anyone
-- can ask, including a health check.
CREATE TABLE IF NOT EXISTS collector_status (
    series        TEXT        PRIMARY KEY,
    last_ok_ts    BIGINT      NOT NULL,
    last_rows     INTEGER     NOT NULL DEFAULT 0,
    last_error    TEXT        NOT NULL DEFAULT '',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
