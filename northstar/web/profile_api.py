"""JSON endpoints for the signed-in user's own profile: the first endpoints that change data.

Like the other routes, these call the plain functions in users.py and add no rules of their own.
They only ever touch the signed-in user, so no admin is needed. A broken rule is a 422.
"""

from contextlib import closing
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from northstar import db, users
from northstar.errors import ValidationError
from northstar.web.auth_routes import COOKIE, current_user

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
        conn.execute("BEGIN")
        try:
            if body.display_name is not None:
                users.set_display_name(conn, user["id"], body.display_name)
            if body.theme is not None:
                users.set_theme(conn, user["id"], body.theme)
        except ValidationError:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        return _me(conn, user["id"])

    return _run(request, action)


@router.post("/password", status_code=204)
def change_password(body: PasswordChange, request: Request):
    user = current_user(request)
    _run(request, lambda conn: users.change_own_password(
        conn, user["id"], body.current_password, body.new_password, request.cookies.get(COOKIE)))
    return Response(status_code=204)
