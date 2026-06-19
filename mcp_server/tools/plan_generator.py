"""
mcp_server/tools/plan_generator.py

Tool MCP: generate_course_plan
Genera un plan educativo estructurado usando GPT-4o vía OpenRouter.
Aplica las reglas activas definidas en settings.PLAN_RULES.
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

SYSTEM_PROMPT = """Eres "The Intelligence", un agente experto en diseño curricular y planificación educativa.
Tu rol es generar planes de estudio estructurados, progresivos y pedagógicamente sólidos.

REGLAS ACTIVAS que DEBES respetar siempre:
1. Cada semana debe tener entre {min_topics} y {max_topics} tópicos.
2. Las horas totales por semana no pueden superar {max_hours}h.
3. Para nivel BEGINNER: {theory_ratio_percent:.0f}% teoría, resto práctica.
4. Cada semana debe incluir: objectives (lista), topics (lista), resources (lista), assessment (string).
5. Los tópicos deben ser progresivos: semanas iniciales → fundamentos, semanas finales → proyectos aplicados.
6. Incluir al menos un recurso gratuito (YouTube, documentación oficial, artículo) por tópico.
7. El plan debe ser COMPLETO para las semanas solicitadas, sin omitir ninguna.

FORMATO DE RESPUESTA: JSON puro, sin markdown, sin explicaciones adicionales."""


def build_user_prompt(
    title: str,
    subject: str,
    duration_months: int,
    level: str,
    description: str,
) -> str:
    total_weeks = duration_months * 4
    rules = settings.PLAN_RULES
    theory_ratio = rules[f"{level.lower()}_theory_ratio"]

    return f"""Genera un plan de estudio completo con las siguientes características:

CURSO: {title}
MATERIA: {subject}
DESCRIPCIÓN: {description}
NIVEL: {level}
DURACIÓN: {duration_months} meses ({total_weeks} semanas)

RESPONDE EXACTAMENTE en este formato JSON:
{{
  "course_title": "{title}",
  "subject": "{subject}",
  "level": "{level}",
  "total_weeks": {total_weeks},
  "overview": "Descripción general del plan de {duration_months} meses",
  "weeks": [
    {{
      "week_number": 1,
      "title": "Título descriptivo de la semana",
      "objectives": ["Objetivo 1", "Objetivo 2", "Objetivo 3"],
      "topics": [
        {{
          "title": "Nombre del tópico",
          "description": "Descripción detallada de 2-3 oraciones de qué aprenderá el estudiante",
          "estimated_hours": 3.5,
          "type": "teoria|practica|proyecto",
          "resources": [
            "https://... — Nombre del recurso",
            "https://... — Otro recurso"
          ]
        }}
      ],
      "assessment": "Descripción de cómo se evaluará esta semana"
    }}
  ]
}}

Genera las {total_weeks} semanas completas. Aplica las reglas activas:
- Entre {rules['min_topics_per_week']} y {rules['max_topics_per_week']} tópicos por semana
- Máximo {rules['max_hours_per_week']} horas totales por semana
- Ratio teoría/práctica: {theory_ratio*100:.0f}% teoría para nivel {level}
"""


def generate_course_plan(
    title: str,
    subject: str,
    duration_months: int,
    level: str = "BEGINNER",
    description: str = "",
) -> dict:
    """
    MCP Tool: Genera un plan de curso completo usando GPT-4o.

    Args:
        title: Nombre del curso (ej: "Ingeniería en Inteligencia Artificial")
        subject: Materia/área (ej: "Inteligencia Artificial")
        duration_months: Duración en meses (ej: 6)
        level: BEGINNER | INTERMEDIATE | ADVANCED
        description: Descripción adicional del público objetivo y contexto

    Returns:
        dict con el plan estructurado y envelope estandarizado
    """
    logger.info(
        "generate_course_plan.started",
        title=title,
        subject=subject,
        duration_months=duration_months,
        level=level,
    )

    rules = settings.PLAN_RULES
    theory_ratio = rules.get(f"{level.lower()}_theory_ratio", 0.5)

    system_msg = SYSTEM_PROMPT.format(
        min_topics=rules["min_topics_per_week"],
        max_topics=rules["max_topics_per_week"],
        max_hours=rules["max_hours_per_week"],
        theory_ratio_percent=theory_ratio * 100,
    )

    user_msg = build_user_prompt(title, subject, duration_months, level, description)

    try:
        logger.info("generate_course_plan.calling_openai", model=settings.OPENROUTER_MODEL, api_key_exists=bool(settings.OPENROUTER_API_KEY))
        response = client.chat.completions.create(
            model=settings.OPENROUTER_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.7,
            max_tokens=6000,
            extra_headers={
                "HTTP-Referer": "https://hacklaton-intelligence.dev",
                "X-Title": "The Intelligence Agent",
            },
        )
        logger.info("generate_course_plan.openai_response_received")
        raw_content = response.choices[0].message.content.strip()

        # Limpiar posibles bloques markdown
        if raw_content.startswith("```"):
            raw_content = raw_content.split("```")[1]
            if raw_content.startswith("json"):
                raw_content = raw_content[4:]
        if raw_content.endswith("```"):
            raw_content = raw_content[:-3]

        plan_data = json.loads(raw_content.strip())

        # Validar reglas activas
        validation_errors = _validate_plan(plan_data)
        if validation_errors:
            logger.warning("generate_course_plan.validation_warnings", errors=validation_errors)

        logger.info(
            "generate_course_plan.completed",
            weeks_generated=len(plan_data.get("weeks", [])),
        )

        return {
            "success": True,
            "tool": "generate_course_plan",
            "result": plan_data,
            "validation_warnings": validation_errors,
            "error": None,
        }

    except json.JSONDecodeError as e:
        logger.error("generate_course_plan.json_parse_error", error=str(e))
        return {
            "success": False,
            "tool": "generate_course_plan",
            "result": None,
            "error": f"Error parseando respuesta del LLM: {str(e)}",
        }
    except Exception as e:
        logger.error("generate_course_plan.unexpected_error", error=str(e))
        return {
            "success": False,
            "tool": "generate_course_plan",
            "result": None,
            "error": str(e),
        }
    except BaseException as e:
        logger.error("generate_course_plan.base_exception", error=str(type(e)), details=str(e))
        return {
            "success": False,
            "tool": "generate_course_plan",
            "result": None,
            "error": f"BaseException: {str(e)}",
        }


def _validate_plan(plan: dict) -> list[str]:
    """Valida que el plan cumpla las reglas activas."""
    errors = []
    rules = settings.PLAN_RULES
    weeks = plan.get("weeks", [])

    for week in weeks:
        topics = week.get("topics", [])
        total_hours = sum(t.get("estimated_hours", 0) for t in topics)

        if len(topics) < rules["min_topics_per_week"]:
            errors.append(f"Semana {week.get('week_number')}: pocos tópicos ({len(topics)})")

        if len(topics) > rules["max_topics_per_week"]:
            errors.append(f"Semana {week.get('week_number')}: demasiados tópicos ({len(topics)})")

        if total_hours > rules["max_hours_per_week"]:
            errors.append(f"Semana {week.get('week_number')}: excede horas ({total_hours:.1f}h)")

        for section in rules["required_sections"]:
            if section not in week and section != "topics":
                errors.append(f"Semana {week.get('week_number')}: falta sección '{section}'")

    return errors
