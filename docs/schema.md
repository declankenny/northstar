# Northstar: database schema

The SQLite schema as the migrations in `northstar/migrations/` build it. The migrations are the source of truth, and `tests/test_schema_diagram.py` fails when this diagram and a migrated database disagree about tables, columns, types, keys or relationships, so a schema change cannot ship without updating it. The rules the data must obey are in `spec.md`.

```mermaid
erDiagram
    account_classes ||--o{ account_types : "class_id"
    account_classes ||--o{ accounts : "class_id"
    account_types ||--o{ accounts : "type_id, class_id"
    accounts ||--o{ balances : "account_id"
    users ||--o{ sys_sessions : "user_id"
    users ||--o{ account_classes : "created_by, updated_by"
    users ||--o{ account_types : "created_by, updated_by"
    users ||--o{ accounts : "created_by, updated_by"
    users ||--o{ balances : "created_by, updated_by"
    users ||--o{ users : "created_by, updated_by"

    account_classes {
        integer id PK
        text name UK "Asset or Liability"
        text created_at "UTC"
        integer created_by FK "who created it"
        text updated_at "UTC"
        integer updated_by FK "who last changed it"
    }
    account_types {
        integer id PK
        text name UK "case-insensitive"
        integer class_id FK
        integer stale_after_days "at least 1"
        text created_at "UTC"
        integer created_by FK "who created it"
        text updated_at "UTC"
        integer updated_by FK "who last changed it"
    }
    accounts {
        integer id PK
        text name
        integer class_id FK
        integer type_id FK
        integer is_open "0 or 1"
        text notes "optional"
        text created_at "UTC"
        integer created_by FK "who created it"
        text updated_at "UTC"
        integer updated_by FK "who last changed it"
    }
    balances {
        integer id PK
        integer account_id FK
        text as_of_date "YYYY-MM-DD"
        integer amount_cents
        text note "optional"
        text source "manual"
        text created_at "UTC"
        integer created_by FK "who created it"
        text updated_at "UTC"
        integer updated_by FK "who last changed it"
    }
    users {
        integer id PK
        text email UK "case-insensitive"
        text display_name
        text password_hash
        integer is_admin "0 or 1"
        text theme "light or dark"
        integer is_system "0 or 1, exactly one row is 1"
        text created_at "UTC"
        integer created_by FK "who created it"
        text updated_at "UTC"
        integer updated_by FK "who last changed it"
        integer deleted "0 or 1"
    }
    sys_sessions {
        text token_hash PK "SHA-256 of the cookie token"
        integer user_id FK
        text created_at "UTC"
        text expires_at "UTC"
    }
    sys_login_attempts {
        integer id PK
        text email_hash
        text address_hash "nullable"
        text attempted_at "UTC"
    }
    sys_schema_migrations {
        text version PK
        text applied_at "UTC"
    }
```

## Conventions

- Money is integer cents. A balance date is a calendar date, `YYYY-MM-DD`, with no timezone. Row timestamps are UTC text, `YYYY-MM-DDTHH:MM:SSZ`.
- `is_open` and `is_admin` are 0 or 1, because SQLite has no boolean type.
- `sys_schema_migrations` is created by the migration runner in `northstar/db.py`, not by a migration file. Releases before 0.2 called it `schema_migrations`, and the runner renames it (keeping its rows) the first time a newer version starts, after a backup.
- A table that starts with `sys_` is written by the application for itself: it has no audit columns and is never logged. Every other table has the four audit columns, and `created_by` and `updated_by` point at `users`. Rows that existed before the audit columns were added, and rows made by the command line, are authored by the system user: the one `users` row with `is_system = 1`, which nobody can sign in as.
- Every household table uses `AUTOINCREMENT`, so the id of a deleted row is never given to another row.
- `sys_login_attempts` has no relationships on purpose: it keeps only hashes of the email and the address, never the typed values.

## What the diagram cannot show

A person checks these against the migrations, because the test cannot read them from the diagram.

| Table | Constraint |
|---|---|
| `account_classes` | Exactly two rows, Asset (1) and Liability (2), inserted by the first migration. |
| `account_types` | `UNIQUE (id, class_id)`, which is the target of the composite key from `accounts`. The first migration also inserts the 11 starting types. |
| `accounts` | `FOREIGN KEY (type_id, class_id)` references `account_types (id, class_id)` with `ON UPDATE RESTRICT ON DELETE RESTRICT`, so an account's type always belongs to its class, and a type in use can be neither deleted nor moved to another class. |
| `accounts` (name) | Unique index `accounts_name_unique` on `name COLLATE NOCASE`: a name is unique ignoring ASCII case, across open and closed accounts. |
| `balances` | `UNIQUE (account_id, as_of_date)`: one balance per account per date. `as_of_date` must be a valid date. Deleting an account cascades to its balances. |
| `users` | `deleted` is 1 for a user who was deleted: the row stays, so the author columns that name them keep working, and adding their email again reactivates it. `is_system` is 1 for exactly one row, enforced by the partial unique index `users_one_system`. The `created_by` and `updated_by` columns of every household table reference it. |
| `sys_sessions` | Deleting a user cascades to their sessions. Index `sys_sessions_user_id` on `user_id`. |
| `sys_login_attempts` | Indexes on `(email_hash, attempted_at)` and `(address_hash, attempted_at)`. |
