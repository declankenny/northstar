-- The sys_ prefix marks a table the application writes for itself: no audit columns, never logged. See
-- docs/spec.md, "Architecture", and docs/design/v0.2-db-schema. The record of applied migrations was renamed by the
-- runner; these two follow, with their indexes.

ALTER TABLE sessions RENAME TO sys_sessions;
DROP INDEX sessions_user_id;
CREATE INDEX sys_sessions_user_id ON sys_sessions (user_id);

ALTER TABLE login_attempts RENAME TO sys_login_attempts;
DROP INDEX login_attempts_email;
DROP INDEX login_attempts_address;
CREATE INDEX sys_login_attempts_email ON sys_login_attempts (email_hash, attempted_at);
CREATE INDEX sys_login_attempts_address ON sys_login_attempts (address_hash, attempted_at);
