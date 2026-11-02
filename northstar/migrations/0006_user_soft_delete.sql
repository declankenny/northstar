-- User soft delete. See docs/spec.md, "Security" ("Users and roles"), and docs/design/v0.2-db-schema.
-- A deleted user keeps their row, id, email, name and creation metadata, so the audit columns that name them keep
-- pointing at a real person. They cannot sign in, are hidden, and have no sessions. Adding their email again
-- reactivates the same row. The email stays unique across deleted users too.

ALTER TABLE users ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1));
