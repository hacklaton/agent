"""
mcp_server/server.py

Servidor MCP "The Intelligence" construido con FastMCP.
Expone Tools, Resources y Prompts para el agente orquestador.

Transport: stdio (el agente lanza este proceso como subproceso)
"""
import sys
import structlog

# Configure structlog to output to stderr, so it doesn't pollute stdout (MCP stdio channel)
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(sys.stderr)
)

from mcp.server.fastmcp import FastMCP
from mcp_server.tools.plan_generator import generate_course_plan
from mcp_server.tools.topic_suggester import suggest_weekly_topics
from mcp_server.tools.db_writer import save_plan_to_db, get_teacher_selections
from mcp_server.tools.plan_finalizer import finalize_course_plan
from mcp_server.resources.course_context import get_course_context

logger = structlog.get_logger(__name__)

# ============================================================
# Instancia principal del servidor MCP
# ============================================================
mcp = FastMCP(
    name="the-intelligence",
    instructions=(
        "Eres 'The Intelligence', un agente de análisis predictivo educativo. "
        "Generas planes de cursos estructurados, sugieres tópicos pedagógicos "
        "y guardas todo en la base de datos. Aplica siempre las reglas activas "
        "definidas en settings.PLAN_RULES antes de generar cualquier contenido."
    ),
)

# ============================================================
# TOOLS — Acciones con efectos
# ============================================================

@mcp.tool()
def tool_generate_course_plan(
    title: str,
    subject: str,
    duration_months: int,
    level: str = "BEGINNER",
    description: str = "",
) -> dict:
    """
    Genera un plan de curso completo semana a semana usando GPT-4o.

    Parámetros:
    - title: Nombre del curso (ej: "Curso de IA para Principiantes")
    - subject: Materia o área (ej: "Inteligencia Artificial", "Python", "Matemáticas")
    - duration_months: Duración en meses (1-24)
    - level: Nivel del curso — BEGINNER | INTERMEDIATE | ADVANCED
    - description: Contexto adicional sobre el público objetivo

    Retorna el plan estructurado con semanas, tópicos, objetivos y recursos.
    Aplica reglas activas: límites de horas por semana, ratio teoría/práctica,
    progresión pedagógica.
    """
    logger.info("mcp.tool.generate_course_plan", title=title, level=level)
    return generate_course_plan(title, subject, duration_months, level, description)


@mcp.tool()
def tool_suggest_weekly_topics(
    week_number: int,
    week_title: str,
    objectives: list,
    subject: str,
    level: str = "BEGINNER",
    existing_topics: list = None,
) -> dict:
    """
    Sugiere tópicos adicionales enriquecidos para una semana específica.

    El profesor puede revisar y seleccionar cuáles implementar.
    Cada tópico incluye: descripción detallada, actividad práctica,
    recursos gratuitos, subtópicos y notas para el profesor.

    Parámetros:
    - week_number: Número de la semana (1-based)
    - week_title: Título de la semana
    - objectives: Lista de objetivos de aprendizaje
    - subject: Materia del curso
    - level: BEGINNER | INTERMEDIATE | ADVANCED
    - existing_topics: Tópicos ya incluidos (para no duplicar)
    """
    logger.info("mcp.tool.suggest_weekly_topics", week_number=week_number)
    return suggest_weekly_topics(
        week_number, week_title, objectives, subject, level, existing_topics or []
    )


@mcp.tool()
def tool_save_plan_to_db(course_id: str, plan_json: dict) -> dict:
    """
    Persiste el plan educativo completo en PostgreSQL.

    Escribe en las tablas: CoursePlan, PlanWeek, Topic.
    Si el plan ya existe, lo actualiza (upsert).

    Parámetros:
    - course_id: UUID del curso existente en la base de datos
    - plan_json: Plan estructurado retornado por tool_generate_course_plan
    """
    logger.info("mcp.tool.save_plan_to_db", course_id=course_id)
    return save_plan_to_db(course_id, plan_json)


@mcp.tool()
def tool_get_teacher_selections(course_id: str) -> dict:
    """
    Lee los tópicos seleccionados por el profesor para un curso.

    Retorna todos los tópicos agrupados por semana, indicando
    cuáles han sido seleccionados por el profesor y con qué notas.

    Parámetros:
    - course_id: UUID del curso
    """
    logger.info("mcp.tool.get_teacher_selections", course_id=course_id)
    return get_teacher_selections(course_id)


@mcp.tool()
def tool_finalize_course_plan(course_id: str) -> dict:
    """
    Finaliza el plan de un curso después de que el profesor haya
    seleccionado sus tópicos. Marca el plan como FINALIZED en la DB.

    Parámetros:
    - course_id: UUID del curso a finalizar
    """
    logger.info("mcp.tool.finalize_course_plan", course_id=course_id)
    return finalize_course_plan(course_id)


# ============================================================
# RESOURCES — Contexto de solo lectura
# ============================================================

@mcp.resource("course://{course_id}/context")
def resource_course_context(course_id: str) -> dict:
    """
    Contexto de solo lectura de un curso.

    Incluye: título, materia, nivel, estado del plan, estadísticas
    de semanas/tópicos y las reglas activas del sistema.
    Sin PII sensible (solo IDs internos y métricas agregadas).
    """
    logger.info("mcp.resource.course_context", course_id=course_id)
    return get_course_context(course_id)


# ============================================================
# PROMPTS — Plantillas reutilizables
# ============================================================

@mcp.prompt()
def prompt_generate_full_plan(
    course_id: str,
    title: str,
    subject: str,
    duration_months: int,
    level: str = "BEGINNER",
    description: str = "",
) -> str:
    """
    Plantilla reutilizable para el flujo completo de generación de plan.

    Orquesta: generate_course_plan → suggest_weekly_topics → save_plan_to_db
    """
    return f"""Eres 'The Intelligence'. Debes generar y guardar un plan completo para:

CURSO: {title}
MATERIA: {subject}
DURACIÓN: {duration_months} meses
NIVEL: {level}
CONTEXTO: {description}
COURSE_ID en DB: {course_id}

PASOS OBLIGATORIOS:
1. Lee el resource course://{course_id}/context para entender el estado actual
2. Usa tool_generate_course_plan para generar el plan completo
3. Para las primeras 4 semanas, usa tool_suggest_weekly_topics para enriquecer los tópicos
4. Usa tool_save_plan_to_db para persistir todo en la base de datos
5. Retorna un resumen con: plan_id, semanas_generadas, tópicos_totales

REGLAS ACTIVAS que debes verificar antes de guardar:
- Mínimo 2 tópicos por semana, máximo 6
- Máximo 20 horas totales por semana
- Para BEGINNER: 60% teoría, 40% práctica
- Cada semana debe tener objectives, topics, resources, assessment

No inventes datos. Si algo falla, reporta el error de forma estructurada."""


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    logger.info("mcp_server.starting", transport="stdio")
    mcp.run(transport="stdio")
