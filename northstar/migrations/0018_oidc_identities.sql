-- Storage for OIDC sign-in (#167, step 2 of docs/design/oidc). See docs/decisions.md.
--
-- `user_identities` binds a person who signs in through the identity provider to a Northstar user: the provider's issuer and
-- the subject it gave them, which together name them for good, whatever their email or name later becomes. It is a household
-- table with audit columns, because a binding is a durable, security-sensitive fact that belongs in the change log, and unlike a
-- session it outlives everything: a user is only ever marked deleted, so their bindings stay and a later sign-in cannot get
-- around the deletion. A binding is never deleted and never moved to another user or identity by the application: replacing
-- one is an administrative procedure for a later release.
--
-- `sys_login_transactions` holds the short-lived state of a sign-in in progress (step 3 uses it). `sys_sessions` records how a
-- session was started and, for OIDC, which provider configuration it belongs to.

INSERT INTO sys_operation_kinds (kind) VALUES ('oidc');

CREATE TABLE user_identities (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users (id),
    -- The issuer exactly as it was configured when the person signed in, and the provider's subject (at most 255 characters).
    issuer     TEXT NOT NULL CHECK (length(issuer) BETWEEN 1 AND 256),
    subject    TEXT NOT NULL CHECK (length(subject) BETWEEN 1 AND 255),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by INTEGER NOT NULL REFERENCES users (id),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by INTEGER NOT NULL REFERENCES users (id),
    -- One person at one provider is one binding, and one user has at most one binding per issuer: a second subject presenting
    -- the same email is refused, never swapped in.
    UNIQUE (issuer, subject),
    UNIQUE (user_id, issuer)
);

CREATE TRIGGER user_identities_never_deleted BEFORE DELETE ON user_identities
BEGIN
    SELECT RAISE(ABORT, 'An identity binding cannot be deleted.');
END;
CREATE TRIGGER user_identities_fixed BEFORE UPDATE OF user_id, issuer, subject ON user_identities
BEGIN
    SELECT RAISE(ABORT, 'An identity binding cannot be changed.');
END;

INSERT INTO sys_audited_fields (tablename, fieldname, is_logged) VALUES
    ('user_identities', 'id', 0),
    ('user_identities', 'user_id', 1),
    ('user_identities', 'issuer', 1),
    ('user_identities', 'subject', 1),
    ('user_identities', 'created_at', 1),
    ('user_identities', 'created_by', 1),
    ('user_identities', 'updated_at', 0),
    ('user_identities', 'updated_by', 0);

-- One row per sign-in in progress. The state and the browser-binding value are kept only as hashes. The nonce and the PKCE verifier
-- are kept as they are because the exchange needs them, and are never logged. Rows are removed when used and when they expire.
CREATE TABLE sys_login_transactions (
    state_hash         TEXT PRIMARY KEY CHECK (length(state_hash) = 64),
    binding_hash       TEXT NOT NULL CHECK (length(binding_hash) = 64),
    nonce              TEXT NOT NULL CHECK (length(nonce) >= 16),
    code_verifier      TEXT NOT NULL CHECK (length(code_verifier) >= 43),
    return_path        TEXT NOT NULL CHECK (length(return_path) <= 2000),
    config_fingerprint TEXT NOT NULL CHECK (length(config_fingerprint) = 64),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    expires_at         TEXT NOT NULL
);
CREATE INDEX sys_login_transactions_expires_at ON sys_login_transactions (expires_at);

-- How a session was started. Every existing session is a local one and keeps its expiry. An OIDC session carries a fingerprint (a
-- SHA-256, as hex) of the issuer and client ID it was made under, and is refused once those no longer match the settings.
ALTER TABLE sys_sessions ADD COLUMN auth_method TEXT NOT NULL DEFAULT 'local' CHECK (auth_method IN ('local', 'oidc'));
ALTER TABLE sys_sessions ADD COLUMN config_fingerprint TEXT CHECK (config_fingerprint IS NULL OR length(config_fingerprint) = 64);

-- An OIDC session has a fingerprint and a local one has none. (A table check cannot be added to an existing table.)
CREATE TRIGGER sys_sessions_method_and_fingerprint BEFORE INSERT ON sys_sessions
WHEN (NEW.auth_method = 'oidc') <> (NEW.config_fingerprint IS NOT NULL)
BEGIN
    SELECT RAISE(ABORT, 'An OIDC session has a configuration fingerprint and a local session has none.');
END;
