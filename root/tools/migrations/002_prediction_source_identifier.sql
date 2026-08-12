ALTER TABLE predictions ADD COLUMN source_identifier TEXT;

CREATE INDEX predictions_source_identifier
    ON predictions(source_identifier);
