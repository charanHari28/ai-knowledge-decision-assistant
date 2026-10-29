"""FastAPI application entry point.

    uvicorn app.main:app --reload --port 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, settings
from app.db import init_db
from app.routers import admin, auth, public
from app.security import resolve_assistant_token
from app.services import llm
from app.services.pdf_processing import DocumentError
from app.services.pipeline import PipelineError
from app.system1.classifier import get_classifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = BASE_DIR / "static"

@asynccontextmanager
async def lifespan(_app):
    init_db()
    get_classifier()  # train the System-1 question classifier once at boot (~1-2 s)
    logging.getLogger("app").info("LLM: %s", llm.provider_label())
    yield


app = FastAPI(title="AI Knowledge & Decision Assistant", version="1.0.0", lifespan=lifespan)

# Only the public visitor endpoints may be called cross-origin (from embedding sites).
# Admin APIs are same-origin only (the dashboard is served by this app).
PUBLIC_PATHS = ("/api/ask", "/api/public/")


@app.middleware("http")
async def scoped_cors(request: Request, call_next):
    is_public = request.url.path.startswith(PUBLIC_PATHS)
    if request.method == "OPTIONS" and is_public:
        response = JSONResponse({}, status_code=204)
    else:
        response = await call_next(request)
    if is_public:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Assistant-Token"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"  # don't leak the assistant token via Referer
    return response


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(public.router)


# ---------------------------------------------------------------- errors -> consistent JSON
def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.exception_handler(DocumentError)
async def _doc_err(_, exc: DocumentError):
    return _err(exc.status_code, exc.code, exc.message)


@app.exception_handler(PipelineError)
async def _pipe_err(_, exc: PipelineError):
    return _err(exc.status_code, exc.code, exc.message)


@app.exception_handler(HTTPException)
async def _http_err(_, exc: HTTPException):
    codes = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict", 413: "too_large", 429: "rate_limited"}
    return _err(exc.status_code, codes.get(exc.status_code, "error"), str(exc.detail))


@app.exception_handler(RequestValidationError)
async def _validation_err(_, exc: RequestValidationError):
    return _err(422, "invalid_request", "The request was missing required fields or had invalid values.")


# ---------------------------------------------------------------- pages
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC / "dashboard.html")


@app.get("/a/{token}", include_in_schema=False)
def assistant_page(token: str):
    if not resolve_assistant_token(token):  # validated server-side before rendering
        return HTMLResponse((STATIC / "invalid.html").read_text(), status_code=404)
    return FileResponse(STATIC / "chat.html")


@app.get("/embed.js", include_in_schema=False)
def embed_js():
    return FileResponse(STATIC / "embed.js", media_type="application/javascript")


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True, "llm": llm.provider_label()}
