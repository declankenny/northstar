# Northstar: database schema

The SQLite schema as the migrations in `northstar/migrations/` build it. The migrations are the source of truth, and `tests/test_schema_diagram.py` fails when this diagram and a migrated database disagree about tables, columns, types, keys or relationships, so a schema change cannot ship without updating it. The rules the data must obey are in `spec.md`.

```mermaid
erDiagram
    account_classes ||--o{ account_types : "class_id"
    account_classes ||--o{ accounts : "class_id"
    account_types ||--o{ accounts : "type_id, class_id"
    accounts ||--o{ balances : "account_id"
    users ||--o{ sessions : "user_id"

    account_classes {
        integer id PK
        text name UK "Asset or Liability"
    }
    account_types {
        integer id PK
        text name UK "case-insensitive"
        integer class_id FK
        integer stale_after_days "at least 1"
        text created_at "UTC"
    }
    accounts {
        integer id PK
        text name
        integer class_id FK
        integer type_id FK
        integer is_open "0 or 1"
        text notes "optional"
        text created_at "UTC"
    }
    balances {
        integer id PK
        integer account_id FK
        text as_of_date "YYYY-MM-DD"
        integer amount_cents
        text note "optional"
        text source "manual"
        text created_at "UTC"
        text updated_at "UTC"
    }
    users {
        integer id PK
        text email UK "case-insensitive"
        text display_name
        text password_hash
        integer is_admin "0 or 1"
        text theme "light or dark"
        text created_at "UTC"
    }
    sessions {
        text token_hash PK "SHA-256 of the cookie token"
        integer user_id FK
        text created_at "UTC"
        text expires_at "UTC"
    }
    login_attempts {
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
- `login_attempts` has no relationships on purpose: it keeps only hashes of the email and the address, never the typed values.

## What the diagram cannot show

A person checks these against the migrations, because the test cannot read them from the diagram.

| Table | Constraint |
|---|---|
| `account_classes` | Exactly two rows, Asset (1) and Liability (2), inserted by the first migration. |
| `account_types` | `UNIQUE (id, class_id)`, which is the target of the composite key from `accounts`. The first migration also inserts the 11 starting types. |
| `accounts` | `FOREIGN KEY (type_id, class_id)` references `account_types (id, class_id)` with `ON UPDATE RESTRICT ON DELETE RESTRICT`, so an account's type always belongs to its class, and a type in use can be neither deleted nor moved to another class. |
| `balances` | `UNIQUE (account_id, as_of_date)`: one balance per account per date. `as_of_date` must be a valid date. Deleting an account cascades to its balances. |
| `sessions` | Deleting a user cascades to their sessions. Index `sessions_user_id` on `user_id`. |
| `login_attempts` | Indexes on `(email_hash, attempted_at)` and `(address_hash, attempted_at)`. |
