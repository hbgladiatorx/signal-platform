-- Migration 0011: Option instrument modeling (single-leg options).
--
-- Adds typed, nullable columns to the existing instruments table so option
-- contracts can live alongside crypto/equity rows without affecting them.
-- Canonical option symbols are OCC-style, e.g. 'AAPL250117C00150000@ALPACA'
-- (venue = execution venue ALPACA; data_source recorded in metadata). The OCC
-- string is also the Alpaca native symbol. multiplier is 100 for US options.
--
-- Idempotent.

ALTER TABLE instruments
    ADD COLUMN IF NOT EXISTS underlying   TEXT,            -- canonical of underlier, e.g. 'AAPL@ALPACA'
    ADD COLUMN IF NOT EXISTS option_right CHAR(1),         -- 'C' or 'P'
    ADD COLUMN IF NOT EXISTS strike       NUMERIC(28,12),
    ADD COLUMN IF NOT EXISTS expiry       DATE,
    ADD COLUMN IF NOT EXISTS multiplier   NUMERIC NOT NULL DEFAULT 1;

-- Guard the right column to valid values (only when set).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'instruments_option_right_chk'
    ) THEN
        ALTER TABLE instruments
            ADD CONSTRAINT instruments_option_right_chk
            CHECK (option_right IS NULL OR option_right IN ('C', 'P'));
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_instruments_underlying_expiry
    ON instruments (underlying, expiry)
    WHERE asset_class = 'option';
