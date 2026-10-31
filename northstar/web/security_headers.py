"""Security headers for every response.

The content security policy allows only this site's own scripts and styles: no inline script or style
(the theme script is the file static/theme.js), no eval, no other site's content and no embedding of
these pages in a frame. React sets its inline styles one property at a time through the browser's
style API, which the policy allows, unlike a style attribute written into the HTML.

HSTS is deliberately not set here: the app may be served over plain HTTP in a trial, where it would be
wrong, and it belongs to the reverse proxy that provides HTTPS (see the README).
"""

from fastapi import FastAPI

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self'",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}


def install(app: FastAPI) -> None:
    """Add the headers to every response. Install it last, so it is the outermost middleware and also
    covers the redirects and the 401s that the other middleware produces. A header a route set itself
    is left alone."""

    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        for name, value in HEADERS.items():
            response.headers.setdefault(name, value)
        return response
