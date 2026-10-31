-- Sign-in throttling. See docs/spec.md, "Security", and docs/decisions.md.
-- One row per sign-in attempt that has not been cleared by a success: the failures, and attempts that
-- are still being checked. Only hashes are kept, never the typed email (a password pasted into the email
-- box must not end up here) and never the client's address.

CREATE TABLE login_attempts (
    id           INTEGER PRIMARY KEY,
    email_hash   TEXT NOT NULL,
    address_hash TEXT,                -- NULL when the client's address is not known
    attempted_at TEXT NOT NULL        -- UTC, YYYY-MM-DDTHH:MM:SSZ
);

CREATE INDEX login_attempts_email ON login_attempts (email_hash, attempted_at);
CREATE INDEX login_attempts_address ON login_attempts (address_hash, attempted_at);
