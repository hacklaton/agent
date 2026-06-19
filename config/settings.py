"""
config/settings.py — Configuración centralizada del Agente "The Intelligence"
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # OpenRouter / LLM
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # Backend
    BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:3001")

    # Agent
    AGENT_PORT: int = int(os.getenv("AGENT_PORT", "8000"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Active rules para la generación de planes
    PLAN_RULES = {
        "max_hours_per_week": 20,
        "min_topics_per_week": 2,
        "max_topics_per_week": 6,
        "beginner_theory_ratio": 0.6,   # 60% teoría, 40% práctica para principiantes
        "intermediate_theory_ratio": 0.5,
        "advanced_theory_ratio": 0.3,
        "required_sections": ["objectives", "topics", "resources", "assessment"],
        "risk_score_threshold": 0.75,   # Umbral para alertas de deserción
    }


settings = Settings()
