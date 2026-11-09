"""JSON endpoints for the signed-in user's own profile: the first endpoints that change data.

Like the other routes, these call the plain functions in users.py and add no rules of their own.
They only ever touch the signed-in user, so no admin is needed. A broken rule is a 422.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from northstar import clock, currencies, db, locales, throttle, users
from northstar.errors import ValidationError
from northstar.web.auth_routes import COOKIE, current_user, operation, run

router = APIRouter(prefix="/api/me")


class CurrencyOut(BaseModel):
    code: str
    name: str
    minor_units: int       # digits after the decimal point: 0, 2 or 3


class LocaleOut(BaseModel):
    tag: str                       # BCP 47, such as en-US
    label: str
    decimal_mark: str
    group_mark: str
    date_template: str             # {year} {month} {month2} {month_short} {day} {day2} and literal text
    currency_position: str         # "prefix" or "suffix"
    currency_code_spacing: str     # the exact text between a currency code and the number


class Me(BaseModel):
    id: int
    email: str
    display_name: str
    is_admin: bool
    theme: Literal["light", "dark"]
    has_password: bool                     # false for someone who signs in only through the identity provider
    currency: CurrencyOut | None = None    # the system currency every amount is shown in; null until an admin sets it
    locale: LocaleOut                      # how this person's numbers and dates are shown and typed


class ProfileChange(BaseModel):
    """Only the fields that are sent change."""
    display_name: str | None = None
    theme: Literal["light", "dark"] | None = None
    locale: str | None = None      # a tag in the catalog


class LocaleChoice(BaseModel):
    tag: str
    label: str


class LocaleChoices(BaseModel):
    locales: list[LocaleChoice]    # every number and date format a person can choose, by label
    default: str                   # the tag a new user starts with, the system default


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def _me(conn, user_id: int) -> dict:
    row = users.get_user(conn, user_id)
    return {**{key: row[key] for key in ("id", "email", "display_name", "theme")}, "is_admin": bool(row["is_admin"]),
            "has_password": users.has_password(conn, user_id), "currency": currencies.system_currency_dict(conn), "locale": locales.get(conn, row["locale"]).as_dict()}


@router.get("", response_model=Me)
def read_me(request: Request):
    user = current_user(request)
    return run(request, lambda conn: _me(conn, user["id"]))


@router.get("/locales", response_model=LocaleChoices)
def list_locales(request: Request):
    current_user(request)
    return run(request, lambda conn: {"locales": locales.catalog(conn), "default": locales.default_tag(conn)})


@router.patch("", response_model=Me)
def change_me(body: ProfileChange, request: Request):
    user = current_user(request)

    def action(conn):
        op = operation(request, conn)
        with db.write_transaction(conn):
            if body.display_name is not None:
                users.set_display_name(op, user["id"], body.display_name)
            if body.theme is not None:
                users.set_theme(op, user["id"], body.theme)
            if body.locale is not None:
                users.set_locale(op, user["id"], body.locale)
        return _me(conn, user["id"])

    return run(request, action)


@router.post("/password", status_code=204)
def change_password(body: PasswordChange, request: Request):
    user = current_user(request)
    address = throttle.address_of(request)

    def action(conn):
        # Guessing the current password is limited like signing in, so a stolen session cannot be used to
        # work out the password. An attempt in which the current password was right is not held against
        # the person, even when the new password is refused.
        _, wait = throttle.begin(conn, user["email"], address, clock.now())
        if wait is not None:
            raise HTTPException(status_code=429, headers={"Retry-After": str(wait)},
                                detail=f"Too many attempts. Try again in about {throttle.describe(wait)}.")
        try:
            users.change_own_password(operation(request, conn), user["id"], body.current_password, body.new_password,
                                      request.cookies.get(COOKIE))
        except users.WrongPasswordError:
            raise
        except ValidationError:
            throttle.clear(conn, user["email"], address)
            raise
        throttle.clear(conn, user["email"], address)

    run(request, action)
    return Response(status_code=204)
