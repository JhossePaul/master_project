"""``create_app``: middleware, errores, rutas de las secciones y el portal."""

from fastapi import FastAPI

from api_backend.errors import install_error_handlers
from api_backend.middleware import RequestContextMiddleware
from api_backend.sections.explanations.router import (
    router as explanations_router,
)
from api_backend.sections.hitl.router import router as hitl_router
from api_backend.sections.kpis.router import router as kpis_router
from api_backend.sections.landing.router import router as landing_router
from api_backend.sections.me.router import router as me_router
from api_backend.sections.reviews.router import router as reviews_router
from api_backend.settings import ApiSettings, get_settings
from api_backend.static import install_static


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or get_settings()
    docs = "/docs" if settings.docs_enabled else None
    app = FastAPI(
        title="BBVA VoC Analyzer",
        version="1",
        docs_url=docs,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.state.role_source = None
    app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "commit": settings.build_commit}

    app.include_router(me_router)
    app.include_router(landing_router)
    app.include_router(kpis_router)
    app.include_router(hitl_router)
    app.include_router(reviews_router)
    app.include_router(explanations_router)
    install_static(app, settings.static_dir)
    return app


def __getattr__(name: str) -> FastAPI:
    """``app`` se crea al pedirla, para importar el módulo sin configuración."""
    if name == "app":
        app = create_app()
        globals()["app"] = app
        return app
    raise AttributeError(name)
