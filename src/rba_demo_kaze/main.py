"""Kaze Labs' employee portal (U-5): a second relying party, styled as its own
product, that signs in through RokuSec's light login (ADR-0036) and asks the
IdP on every request what the session may do (ADR-0029). Never calls the PDP."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rba_demo_kaze.config import Settings, get_settings
from rba_demo_kaze.idp import HttpIdpClient, IdpClient, IdpError

WEB_DIR = Path(__file__).resolve().parent / "web"

# The three things this relying party checks (seeded on the IdP as kaze-portal's
# permissions). The portal never sees a role or a group, only these strings.
PERM_READ = "portal:read"
PERM_PROJECTS = "projects:write"
PERM_SETTINGS = "settings:manage"


@dataclass
class Project:
    name: str
    owner: str
    status: str  # "En curso" | "En revisión" | "Pausado"
    due: str


@dataclass
class Workspace:
    """Demo state, in memory: enough to show a write being allowed or refused."""

    name: str = "Kaze Labs"
    require_passkey_for_admins: bool = True
    session_hours: int = 8
    projects: list[Project] = field(
        default_factory=lambda: [
            Project("Portal de clientes v2", "Martín", "En curso", "15 nov"),
            Project("Migración a Graviton", "Lucas", "En revisión", "3 nov"),
            Project("Onboarding con passkeys", "Valen", "En curso", "28 nov"),
            Project("Tablero de costos", "Martín", "Pausado", "—"),
        ]
    )


ANNOUNCEMENTS = (
    ("Desde hoy entrás con passkey", "El acceso al portal lo protege RokuSec. Si algo se ve distinto, te va a pedir confirmar.", "22 oct"),
    ("Viernes de demo", "Mostramos el portal de clientes v2 a las 16 h.", "20 oct"),
)


def display_name(email: str) -> str:
    return email.split("@", 1)[0].replace(".", " ").title()


def greeting(hour: int) -> str:
    return "Buen día" if hour < 13 else "Buenas tardes" if hour < 20 else "Buenas noches"


def login_url(settings: Settings) -> str:
    callback = f"{settings.public_url.rstrip('/')}/callback"
    query = urlencode({"client_id": settings.client_id, "redirect_uri": callback})
    return f"{settings.idp_public_url.rstrip('/')}/login?{query}"


def create_app(settings: Settings | None = None, *, idp_client: IdpClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    idp = idp_client or HttpIdpClient(settings)
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    workspace = Workspace()

    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.workspace = workspace
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    def to_login(clear: bool = False) -> Response:
        response = RedirectResponse(login_url(settings), status_code=302)
        if clear:
            response.delete_cookie(settings.session_cookie, path="/")
        return response

    def page(request: Request, name: str, session, granted: set[str], status: int = 200, **context):
        return templates.TemplateResponse(
            request=request,
            name=name,
            status_code=status,
            context={
                "email": session.user.email,
                "name": display_name(session.user.email),
                "can_projects": PERM_PROJECTS in granted,
                "can_settings": PERM_SETTINGS in granted,
                "workspace": workspace,
                **context,
            },
        )

    def require(request: Request, permission: str):
        """The session and its grants, or the response that refuses them.

        Asked of the IdP on every request: a role removed in the console stops
        working on the next click, not at the next login.
        """
        token = request.cookies.get(settings.session_cookie)
        if not token:
            return None, None, to_login()
        try:
            session = idp.get_session(token)
        except IdpError:
            return None, None, to_login(clear=True)
        granted = set(session.permissions)
        if permission not in granted:
            return None, None, page(request, "denied.html", session, granted, status=403, permission=permission)
        return session, granted, None

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def home(request: Request):
        session, granted, refused = require(request, PERM_READ)
        if refused is not None:
            return refused
        return page(
            request,
            "home.html",
            session,
            granted,
            active="home",
            greeting=greeting(datetime.now().hour),
            announcements=ANNOUNCEMENTS,
            today=date.today(),
        )

    @app.get("/proyectos")
    def projects(request: Request, creado: str | None = None):
        session, granted, refused = require(request, PERM_READ)
        if refused is not None:
            return refused
        return page(request, "projects.html", session, granted, active="projects", created=creado)

    @app.post("/proyectos")
    def create_project(request: Request, nombre: str = Form(...)):
        # The write path checks again: hiding the button is presentation, this
        # is the control.
        session, granted, refused = require(request, PERM_PROJECTS)
        if refused is not None:
            return refused
        clean = nombre.strip()[:80] or "Proyecto sin nombre"
        workspace.projects.insert(0, Project(clean, display_name(session.user.email), "En curso", "—"))
        return RedirectResponse(f"/proyectos?{urlencode({'creado': clean})}", status_code=303)

    @app.get("/configuracion")
    def settings_page(request: Request, guardado: int = 0):
        session, granted, refused = require(request, PERM_SETTINGS)
        if refused is not None:
            return refused
        return page(request, "settings.html", session, granted, active="settings", saved=bool(guardado))

    @app.post("/configuracion")
    def save_settings(request: Request, nombre: str = Form(...), horas: int = Form(...), passkey_admins: str | None = Form(None)):
        session, granted, refused = require(request, PERM_SETTINGS)
        if refused is not None:
            return refused
        workspace.name = nombre.strip()[:60] or workspace.name
        workspace.session_hours = max(1, min(horas, 24))
        workspace.require_passkey_for_admins = passkey_admins is not None
        return RedirectResponse("/configuracion?guardado=1", status_code=303)

    @app.get("/callback")
    def callback(code: str | None = None):
        if not code:
            return to_login()
        try:
            exchanged = idp.exchange(code)
        except IdpError:
            return to_login()
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            settings.session_cookie,
            exchanged.session.token,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            path="/",
        )
        return response

    @app.post("/logout")
    def logout(request: Request) -> Response:
        token = request.cookies.get(settings.session_cookie)
        if token:
            idp.logout(token)
        response = RedirectResponse("/", status_code=302)
        response.delete_cookie(settings.session_cookie, path="/")
        return response

    return app


app = create_app()
