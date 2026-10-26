"""Sirve ``dist/`` del portal y la vuelta a ``index.html`` de la SPA."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse

from api_backend.errors import ApiError, ErrorCode

IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"
INDEX = "index.html"


def install_static(app: FastAPI, static_dir: str) -> None:
    root = Path(static_dir)

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request) -> FileResponse:
        if path.startswith("api/") or path == "healthz":
            raise ApiError(ErrorCode.NOT_FOUND, "No existe esa ruta")
        index = root / INDEX
        if not index.is_file():
            raise ApiError(ErrorCode.NOT_FOUND, "El portal no está instalado")
        candidate = (root / path).resolve()
        if (
            path
            and candidate.is_file()
            and candidate.is_relative_to(root.resolve())
        ):
            immutable = (
                candidate.relative_to(root.resolve()).parts[0] == "assets"
            )
            return FileResponse(
                candidate,
                headers={"Cache-Control": IMMUTABLE if immutable else NO_CACHE},
            )
        return FileResponse(index, headers={"Cache-Control": NO_CACHE})
