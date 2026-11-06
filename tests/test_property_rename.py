"""The stale-days system property was renamed by a migration. An installation that already has the old name, with its own value,
keeps the value, the validators and the row's id under the new name."""

import shutil

from northstar import db

OLD, NEW = "balance.stale", "system.balance.stale_days"


def migrations_before_the_rename(tmp_path):
    folder = tmp_path / "before"
    folder.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0012":
            shutil.copy(path, folder / path.name)
    return folder


def test_the_rename_keeps_the_value_the_row_and_its_validators(tmp_path):
    path = tmp_path / "northstar.db"
    db.upgrade(path, migrations_before_the_rename(tmp_path))
    conn = db.connect(path)
    conn.execute("UPDATE system_properties SET value = '45' WHERE name = ?", (OLD,))
    conn.commit()
    before = conn.execute("SELECT id FROM system_properties WHERE name = ?", (OLD,)).fetchone()["id"]
    validators = conn.execute("SELECT validator FROM ref_property_validators WHERE property_id = ?", (before,)).fetchall()
    assert validators, "the property has a validator to keep"
    conn.close()

    assert db.upgrade(path) == ["0012_rename_stale_days_property", "0013_exchange_rates", "0014_system_timezone"]

    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM system_properties WHERE name = ?", (OLD,)).fetchone()[0] == 0
    row = conn.execute("SELECT id, value FROM system_properties WHERE name = ?", (NEW,)).fetchone()
    assert (row["id"], row["value"]) == (before, "45")
    assert conn.execute("SELECT validator FROM ref_property_validators WHERE property_id = ?", (before,)).fetchall() == validators


def test_a_new_database_has_only_the_new_name(tmp_path):
    path = tmp_path / "northstar.db"
    db.upgrade(path)
    names = [row["name"] for row in db.connect(path).execute("SELECT name FROM system_properties")]
    assert NEW in names and OLD not in names
