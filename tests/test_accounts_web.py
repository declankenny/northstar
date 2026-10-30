from conftest import add_account, add_balance, type_id, with_db


def account_row(client, name):
    with with_db(client) as conn:
        return conn.execute(
            "SELECT a.*, c.name AS class_name, t.name AS type_name FROM accounts a "
            "JOIN account_classes c ON c.id = a.class_id JOIN account_types t ON t.id = a.type_id "
            "WHERE a.name = ?", (name,)).fetchone()


def make_account(client, name="Test account", class_id=1, type_name="Checking"):
    with with_db(client) as conn:
        return add_account(conn, name, class_id, type_name)


def tid(client, name):
    with with_db(client) as conn:
        return type_id(conn, name)


def test_empty_list_message_and_add_buttons(client):
    page = client.get("/accounts").text
    assert "No open accounts yet" in page
    assert "/accounts/new?class=asset" in page and "/accounts/new?class=liability" in page


def test_new_form_offers_only_types_of_that_class(client):
    asset_page = client.get("/accounts/new?class=asset").text
    assert "Checking" in asset_page and "Mortgage" not in asset_page
    liability_page = client.get("/accounts/new?class=liability").text
    assert "Mortgage" in liability_page and "Checking" not in liability_page


def test_new_form_with_unknown_class_is_refused(client):
    response = client.get("/accounts/new?class=equity")
    assert response.status_code == 400 and "Choose Asset or Liability" in response.text


def test_add_account(client):
    client.post("/accounts", data={"class": "liability", "name": "Test mortgage",
                                   "type_id": str(tid(client, "Mortgage")), "notes": "30 year"})
    row = account_row(client, "Test mortgage")
    assert (row["class_name"], row["type_name"], row["notes"], row["is_open"]) == ("Liability", "Mortgage", "30 year", 1)
    assert "Test mortgage" in client.get("/accounts").text


def test_add_with_type_from_the_other_class_is_refused(client):
    response = client.post("/accounts", data={"class": "asset", "name": "Sneaky",
                                              "type_id": str(tid(client, "Mortgage"))})
    assert response.status_code == 400 and "Choose a type" in response.text
    assert account_row(client, "Sneaky") is None


def test_add_error_keeps_input(client):
    response = client.post("/accounts", data={"class": "asset", "name": "", "notes": "keep me",
                                              "type_id": str(tid(client, "Savings"))})
    assert response.status_code == 400 and "Name is required" in response.text
    assert "keep me" in response.text


def test_edit_account(client):
    acct = make_account(client)
    page = client.get(f"/accounts/{acct}/edit").text
    assert "Change class" in page and "Mortgage" not in page
    client.post(f"/accounts/{acct}", data={"name": "Renamed", "type_id": str(tid(client, "Savings")), "notes": ""})
    row = account_row(client, "Renamed")
    assert (row["id"], row["type_name"], row["class_name"]) == (acct, "Savings", "Asset")


def test_edit_cannot_cross_classes(client):
    acct = make_account(client)
    response = client.post(f"/accounts/{acct}", data={"name": "Test account", "type_id": str(tid(client, "Loan"))})
    assert response.status_code == 400
    assert account_row(client, "Test account")["class_name"] == "Asset"


def test_names_are_escaped(client):
    make_account(client, name="<b>bold</b>")
    page = client.get("/accounts").text
    assert "<b>bold</b>" not in page and "&lt;b&gt;bold&lt;/b&gt;" in page


def test_change_class_page_shows_impact(client):
    acct = make_account(client)
    assert "no balances" in client.get(f"/accounts/{acct}/change-class").text
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-03-31", 100)
        add_balance(conn, acct, "2026-01-31", 100)
    page = client.get(f"/accounts/{acct}/change-class").text
    assert "2 balances" in page and "2026-01-31" in page
    assert "Loan" in page and "Savings" not in page  # only Liability types are offered


def test_change_class(client):
    acct = make_account(client)
    client.post(f"/accounts/{acct}/change-class", data={"type_id": str(tid(client, "Loan"))})
    row = account_row(client, "Test account")
    assert (row["class_name"], row["type_name"]) == ("Liability", "Loan")


def test_change_class_to_same_class_or_nothing_is_refused(client):
    acct = make_account(client)
    for data in ({"type_id": str(tid(client, "Savings"))}, {}):
        response = client.post(f"/accounts/{acct}/change-class", data=data)
        assert response.status_code == 400
    assert account_row(client, "Test account")["class_name"] == "Asset"


def test_close_and_reopen(client):
    acct = make_account(client)
    client.post(f"/accounts/{acct}/close")
    assert account_row(client, "Test account")["is_open"] == 0
    assert "Test account" not in client.get("/accounts").text
    assert "Test account" in client.get("/accounts?show=closed").text
    client.post(f"/accounts/{acct}/reopen")
    assert account_row(client, "Test account")["is_open"] == 1


def test_close_refused_with_nonzero_balance(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-01-31", 5000)
    response = client.post(f"/accounts/{acct}/close")
    assert response.status_code == 400 and "final zero balance" in response.text
    assert account_row(client, "Test account")["is_open"] == 1


def test_delete_confirmation_then_delete(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-01-31", 100)
        add_balance(conn, acct, "2026-02-28", 200)
    page = client.get(f"/accounts/{acct}/delete").text
    assert "2 balances" in page
    assert account_row(client, "Test account") is not None  # the GET did not delete
    client.post(f"/accounts/{acct}/delete")
    assert account_row(client, "Test account") is None
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 0


def test_missing_account_shows_message(client):
    for path in ("/accounts/999/edit", "/accounts/999/change-class", "/accounts/999/delete"):
        response = client.get(path)
        assert response.status_code == 404 and "no longer exists" in response.text
    assert client.post("/accounts/999/delete").status_code == 404


def test_type_in_use_cannot_be_deleted_from_types_page(client):
    make_account(client)
    response = client.post(f"/types/{tid(client, 'Checking')}/delete")
    assert response.status_code == 400 and "1 account uses this type" in response.text


def test_cross_site_post_to_delete_is_refused(client):
    acct = make_account(client)
    response = client.post(f"/accounts/{acct}/delete", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert account_row(client, "Test account") is not None
