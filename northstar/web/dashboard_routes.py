"""Dashboard: the home page."""

from contextlib import closing

from fastapi import APIRouter, Request

from northstar import balances, clock, db, networth

router = APIRouter()


@router.get("/")
def dashboard(request: Request):
    today = clock.today()
    with closing(db.connect(request.app.state.db_path)) as conn:
        current = networth.net_worth_on(conn, today)
        months = networth.net_worth_by_month(conn, today)
        rows = balances.update_rows(conn, today, today)   # open accounts with latest balance and age
    context = {
        "today": today.isoformat(),
        "current": current,
        "months": list(reversed(months)),                  # newest first
        "rows": rows,
    }
    return request.app.state.templates.TemplateResponse(request, "dashboard.html", context)
