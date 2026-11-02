"""JSON endpoints for the signed-in user's own profile: the first endpoints that change data.

Like the other routes, these call the plain functions in users.py and add no rules of their own.
They only ever touch the signed-in user, so no admin is needed. A broken rule is a 422.
"""

from contextlib import closing
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from northstar import clock, db, throttle, users
from northstar.errors import ValidationError
from northstar.web.auth_routes import COOKIE, current_user, operation

router = APIRouter(prefix="/api/me")


class Me(BaseModel):
    id: int
    email: str
    display_name: str
    is_admin: bool
    theme: Literal["light", "dark"]


class ProfileChange(BaseModel):
    """Only the fields that are sent change."""
    display_name: str | None = None
    theme: Literal["light", "dark"] | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def _me(conn, user_id: int) -> dict:
    row = users.get_user(conn, user_id)
    return {**{key: row[key] for key in ("id", "email", "display_name", "theme")}, "is_admin": bool(row["is_admin"])}


def _run(request: Request, action):
    """Run a function from users.py on a connection, turning a broken rule into a 422."""
    with closing(db.connect(request.app.state.db_path)) as conn:
        try:
            return action(conn)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error))


@router.get("", response_model=Me)
def read_me(request: Request):
    user = current_user(request)
    return _run(request, lambda conn: _me(conn, user["id"]))


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
        return _me(conn, user["id"])

    return _run(request, action)


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

    _run(request, action)
    return Response(status_code=204)
