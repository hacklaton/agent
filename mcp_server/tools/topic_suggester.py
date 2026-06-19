"""
mcp_server/tools/topic_suggester.py

Tool MCP: suggest_weekly_topics
Expande los tópicos de una semana con más detalle:
recursos adicionales, subtemas, ejercicios prácticos.
"""
import json
import structlog
from openai import OpenAI
from config.settings import settings

logger = structlog.get_logger(__name__)

client = OpenAI(
    api_key=settings.OPENROUTER_API_KEY,
    base_url=settings.OPENROUTER_BASE_URL,
)


def suggest_weekly_topics(
    week_number: int,
    week_title: str,
    objectives: list[str],
    subject: str,
    level: str = "BEGINNER",
    existing_topics: list[dict] | None = None,
) -> dict:
    """
    MCP Tool: Sugiere tópicos adicionales enriquecidos para una semana específica.

    El profesor puede revisar estos tópicos y seleccionar cuáles implementar
    en su plan de clases.

    Args:
        week_number: Número de la semana (1-based)
        week_title: Título de la semana
        objectives: Lista de objetivos de aprendizaje de la semana
        subject: Materia/área del curso
        level: Nivel del curso
        existing_topics: Tópicos ya generados (para no duplicar)

    Returns:
        dict con lista de tópicos sugeridos enriquecidos
    """
    logger.info(
        "suggest_weekly_topics.started",
        week_number=week_number,
        week_title=week_title,
        level=level,
    )

    existing_titles = [t.get("title", "") for t in (existing_topics or [])]
    existing_str = "\n".join(f"- {t}" for t in existing_titles) if existing_titles else "Ninguno aún."

    user_prompt = f"""Para la semana {week_number} del curso de {subject} (nivel {level}):

TÍTULO DE LA SEMANA: {week_title}

OBJETIVOS:
{chr(10).join(f"• {obj}" for obj in objectives)}

TÓPICOS YA INCLUIDOS (no duplicar):
{existing_str}

Sugiere 3-5 TÓPICOS ADICIONALES enriquecidos que complementen esta semana.
Para cada tópico incluye actividades prácticas específicas, no solo teoría.

Responde en JSON puro:
{{
  "week_number": {week_number},
  "suggested_topics": [
    {{
      "title": "Nombre del tópico sugerido",
      "description": "Descripción de 2-3 oraciones explicando qué aprenderá",
      "estimated_hours": 2.5,
      "type": "teoria|practica|proyecto|laboratorio",
      "difficulty": "basico|intermedio|avanzado",
      "practical_activity": "Descripción de la actividad práctica concreta",
      "resources": [
        "https://... — Nombre recurso gratuito",
        "https://... — Otro recurso"
      ],
      "subtopics": ["Subtópico 1", "Subtópico 2"],
      "teacher_notes": "Sugerencias específicas para el profesor sobre cómo enseñar esto",
      "relevance_score": 0.85
    }}
  ],
  "weekly_integration_tip": "Cómo integrar estos tópicos con los ya existentes"
}}"""

    try:
        response = client.chat.completions.create(
            model=settings.OPENROUTER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres un experto en pedagogía y diseño instruccional. "
                        "Sugieres tópicos educativos detallados y prácticos. "
                        "Responde SOLO con JSON válido, sin markdown."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=3000,
            extra_headers={
                "HTTP-Referer": "https://hacklaton-intelligence.dev",
                "X-Title": "The Intelligence Agent",
            },
        )

        raw_content = response.choices[0].message.content.strip()

        # Limpiar markdown si existe
        if "```" in raw_content:
            parts = raw_content.split("```")
            raw_content = parts[1] if len(parts) > 1 else raw_content
            if raw_content.startswith("json"):
                raw_content = raw_content[4:]

        suggestions = json.loads(raw_content.strip())

        logger.info(
            "suggest_weekly_topics.completed",
            week_number=week_number,
            topics_suggested=len(suggestions.get("suggested_topics", [])),
        )

        return {
            "success": True,
            "tool": "suggest_weekly_topics",
            "result": suggestions,
            "error": None,
        }

    except Exception as e:
        logger.error("suggest_weekly_topics.error", week_number=week_number, error=str(e))
        return {
            "success": False,
            "tool": "suggest_weekly_topics",
            "result": None,
            "error": str(e),
        }
