"""Serve the built web UI from the API server so everything runs on one port.

Build the UI once with ``cd mlx_audio/ui && npm run build``. That writes static
files to ``mlx_audio/ui/out``, which ``mount_ui`` then serves at ``/``. If the
folder does not exist the server keeps working as an API-only server.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

UI_DIST = Path(__file__).parent / "ui" / "out"


def ui_is_built() -> bool:
    return (UI_DIST / "index.html").is_file()


def mount_ui(app: FastAPI) -> bool:
    """Serve the exported UI at ``/``. Returns False if it has not been built.

    Call this after every API route is registered: the mount at ``/`` matches
    any path that no earlier route handled.
    """
    if not ui_is_built():
        return False

    # The API's JSON welcome message lives at "/"; the UI's home page replaces it.
    app.router.routes = [
        route for route in app.router.routes if getattr(route, "path", None) != "/"
    ]
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
    return True
