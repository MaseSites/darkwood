-- Proposals and their confirmation tokens.
--
-- The same shape the SQLite store has carried since stage 7, translated rather
-- than redesigned. Translated on purpose: the two have to behave identically
-- while both exist, and a schema that improves on the old one is a schema whose
-- differences have to be reasoned about at every call site.
--
-- What Postgres adds is not a better table. It is that two processes on two
-- machines can hold this at the same time -- a collector writing while a
-- dashboard reads is the normal case here, and SQLite over a network share is
-- how databases get corrupted.

CREATE TABLE IF NOT EXISTS proposals (
    id            TEXT PRIMARY KEY,
    symbol        TEXT        NOT NULL,
    -- The authoritative status. The payload also carries one, and they can
    -- disagree after a transition; readers must trust this column. That is not a
    -- preference -- it is the bug that was found by a concurrency test in the
    -- SQLite store, where `get()` returned the stale payload copy.
    status        TEXT        NOT NULL,
    created_ts    BIGINT      NOT NULL,
    expires_ts    BIGINT      NOT NULL,
    -- The whole proposal as JSON. jsonb rather than text: it is queryable, and
    -- every field in it is one someone will eventually want to filter on.
    payload       JSONB       NOT NULL,
    note          TEXT        NOT NULL DEFAULT '',
    finished_ts   BIGINT
);

-- Serves the dashboard's only hot query: pending proposals that have not expired.
CREATE INDEX IF NOT EXISTS proposals_by_status ON proposals (status, expires_ts);

CREATE TABLE IF NOT EXISTS tokens (
    token        TEXT PRIMARY KEY,
    proposal_id  TEXT   NOT NULL,
    -- A hash of the proposal's numbers. A token does not survive an edit: adjust
    -- the leverage and this no longer matches, so the token issued for the trade
    -- you were looking at cannot confirm the trade you now have.
    fingerprint  TEXT   NOT NULL,
    issued_ts    BIGINT NOT NULL,
    expires_ts   BIGINT NOT NULL,
    -- NULL until spent. The single-use guarantee is `WHERE used_ts IS NULL` in
    -- the same statement that sets it, so two simultaneous attempts cannot both
    -- report success.
    used_ts      BIGINT,

    CONSTRAINT tokens_proposal_fk
        FOREIGN KEY (proposal_id) REFERENCES proposals (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS tokens_by_proposal ON tokens (proposal_id);
