CREATE TABLE IF NOT EXISTS company_outbox (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id BIGINT NOT NULL UNIQUE,
    inn TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    published_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_company_outbox_pending
    ON company_outbox (version_id) WHERE published_at IS NULL;
