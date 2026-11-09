"""JSON endpoints for the admin Users page. Every one needs an admin (403 otherwise).

Like the other routes, these call the plain functions in users.py and add no rules of their own.
A broken rule is a 422, an unknown user a 404. A user's own profile is in profile_api.py.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from northstar import users
from northstar.web.auth_routes import current_user, operation, require_admin, run

router = APIRouter(prefix="/api/users", dependencies=[Depends(require_admin)])


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_admin: bool
    created_at: str      # UTC
    sign_in: Literal["local", "oidc", "both", "none"]    # how they can sign in: a password, the identity provider, or both
    reactivated: bool = False     # only on a response to adding a user: the email belonged to a deleted user, now restored


class NewUser(BaseModel):
    email: str
    display_name: str
    password: str
    is_admin: bool = False
    locale: str | None = None    # a tag in the catalog; left out, the system default


class UserChange(BaseModel):
    """Any of the three; a field left out stays as it is."""
    email: str | None = None
    display_name: str | None = None
    is_admin: bool | None = None


class NewPassword(BaseModel):
    password: str


def _out(row) -> dict:
    return {**{key: row[key] for key in ("id", "email", "display_name", "created_at")},
            "is_admin": bool(row["is_admin"]), "sign_in": users.sign_in_methods(row)}


def _listed(conn, user_id: int) -> dict:
    return _out(next(row for row in users.list_users(conn) if row["id"] == user_id))


@router.get("", response_model=list[UserOut])
def list_users(request: Request):
    return run(request, lambda conn: [_out(row) for row in users.list_users(conn)])


@router.post("", response_model=UserOut, status_code=201)
def add_user(body: NewUser, request: Request):
    def action(conn):
        user_id, reactivated = users.add_user(operation(request, conn), body.email, body.display_name, body.password,
                                              body.is_admin, body.locale)
        return {**_listed(conn, user_id), "reactivated": reactivated}
    return run(request, action)


@router.patch("/{user_id}", response_model=UserOut)
def change_user(user_id: int, body: UserChange, request: Request):
    acting_id = current_user(request)["id"]

    def action(conn):
        users.update_user(operation(request, conn), user_id, acting_id, body.email, body.display_name, body.is_admin)
        return _listed(conn, user_id)
    return run(request, action)


@router.post("/{user_id}/password", status_code=204)
def reset_password(user_id: int, body: NewPassword, request: Request):
    if user_id == current_user(request)["id"]:
        raise HTTPException(status_code=422, detail="Use Change password on your Profile for your own account.")
    run(request, lambda conn: users.set_user_password(operation(request, conn), user_id, body.password))
    return Response(status_code=204)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, request: Request):
    acting_id = current_user(request)["id"]
    run(request, lambda conn: users.delete_user(operation(request, conn), user_id, acting_id))
    return Response(status_code=204)
