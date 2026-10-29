"""Central configuration, read once from environment variables (.env supported)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader so we don't need python-dotenv. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


class Settings:
    # --- storage ---
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
    DB_PATH: Path = Path(os.getenv("DB_PATH", DATA_DIR / "app.db"))
    UPLOAD_DIR: Path = DATA_DIR / "uploads"  # private, never served statically

    # --- public URL used when building assistant / embed links ---
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

    # --- knowledge-base limits (from the assignment) ---
    MAX_DOCS_PER_ORG: int = int(os.getenv("MAX_DOCS_PER_ORG", 10))
    MAX_PAGES_PER_PDF: int = int(os.getenv("MAX_PAGES_PER_PDF", 20))
    MAX_PDF_BYTES: int = int(os.getenv("MAX_PDF_MB", 10)) * 1024 * 1024

    # --- auth ---
    SESSION_TTL_HOURS: int = int(os.getenv("SESSION_TTL_HOURS", 24))

    # --- LLM provider: gemini | openai | anthropic | offline ---
    # "openai" also covers any OpenAI-compatible API (Groq, Ollama, Together...) via LLM_BASE_URL.
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini").lower()
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", 30))

    # --- retrieval ---
    CHUNK_SIZE_WORDS: int = int(os.getenv("CHUNK_SIZE_WORDS", 180))
    CHUNK_OVERLAP_WORDS: int = int(os.getenv("CHUNK_OVERLAP_WORDS", 40))
    TOP_K: int = int(os.getenv("TOP_K", 5))
    # Minimum System-1 relevance score (0..1) before we treat the KB as having an answer.
    RELEVANCE_THRESHOLD: float = float(os.getenv("RELEVANCE_THRESHOLD", 0.35))

    # --- public /api/ask abuse protection ---
    ASK_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("ASK_RATE_LIMIT_PER_MINUTE", 30))
    MAX_QUESTION_CHARS: int = 1000

    @property
    def llm_enabled(self) -> bool:
        if self.LLM_PROVIDER == "offline":
            return False
        # Ollama via the openai provider needs no key.
        if self.LLM_PROVIDER == "openai" and self.LLM_BASE_URL and "localhost" in self.LLM_BASE_URL:
            return True
        return bool(self.LLM_API_KEY)


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
