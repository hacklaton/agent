"""
agent/intelligence_agent.py

Agente orquestador "The Intelligence".
Usa el MCP Client (stdio) para interactuar con el servidor MCP
y orquestra el flujo completo de generación de planes educativos.

Arquitectura:
  FastAPI request → intelligence_agent.run() → MCP Server (subprocess)
                                              → LLM (GPT-4o via OpenRouter)
                                              → PostgreSQL (compartida)
"""
import json
import asyncio
import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from config.settings import settings
import sys
import os

logger = structlog.get_logger(__name__)

# Path al servidor MCP
SERVER_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "mcp_server", "server.py")


async def run_generate_plan_flow(
    course_id: str,
    title: str,
    subject: str,
    duration_months: int,
    level: str = "BEGINNER",
    description: str = "",
    enrich_first_weeks: int = 4,
) -> dict:
    """
    Flujo principal del agente:
    1. Lee el Resource del curso (contexto)
    2. Genera el plan completo (generate_course_plan tool)
    3. Enriquece las primeras N semanas con tópicos adicionales (suggest_weekly_topics)
    4. Guarda todo en PostgreSQL (save_plan_to_db tool)
    5. Retorna resumen estructurado

    Args:
        course_id: UUID del curso ya creado en la DB
        title: Título del curso
        subject: Materia/área
        duration_months: Duración en meses
        level: BEGINNER | INTERMEDIATE | ADVANCED
        description: Descripción adicional del público objetivo
        enrich_first_weeks: Cuántas semanas enriquecer con suggest_weekly_topics (default: 4)

    Returns:
        dict con el resultado del flujo completo
    """
    logger.info(
        "intelligence_agent.run_generate_plan_flow.started",
        course_id=course_id,
        title=title,
        duration_months=duration_months,
        level=level,
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        env=dict(os.environ),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Inicializar sesión MCP
            await session.initialize()

            logger.info("intelligence_agent.mcp_session.initialized")

            # ── Paso 1: Leer Resource (contexto del curso) ──────────────────
            try:
                context_result = await session.read_resource(f"course://{course_id}/context")
                # El resource retorna una lista de contenido
                context_data = {}
                if context_result.contents:
                    content = context_result.contents[0]
                    if hasattr(content, "text"):
                        context_data = json.loads(content.text)
                logger.info(
                    "intelligence_agent.context_read",
                    found=context_data.get("found", False),
                    plan_status=context_data.get("plan_status"),
                )
            except Exception as e:
                logger.warning("intelligence_agent.context_read.failed", error=str(e))
                context_data = {}

            # ── Paso 2: Generar plan completo ────────────────────────────────
            logger.info("intelligence_agent.generating_plan")
            plan_result = await session.call_tool(
                "tool_generate_course_plan",
                arguments={
                    "title": title,
                    "subject": subject,
                    "duration_months": duration_months,
                    "level": level,
                    "description": description,
                },
            )

            # Extraer resultado del tool
            plan_response = _extract_tool_result(plan_result)

            if not plan_response.get("success"):
                return {
                    "success": False,
                    "step": "generate_course_plan",
                    "error": plan_response.get("error", "Error desconocido generando el plan"),
                    "course_id": course_id,
                }

            plan_data = plan_response["result"]
            weeks = plan_data.get("weeks", [])
            logger.info(
                "intelligence_agent.plan_generated",
                weeks_count=len(weeks),
                warnings=len(plan_response.get("validation_warnings", [])),
            )

            # ── Paso 3: Enriquecer las primeras N semanas ────────────────────
            enriched_weeks = 0
            for week in weeks[:enrich_first_weeks]:
                try:
                    suggest_result = await session.call_tool(
                        "tool_suggest_weekly_topics",
                        arguments={
                            "week_number": week.get("week_number", 0),
                            "week_title": week.get("title", ""),
                            "objectives": week.get("objectives", []),
                            "subject": subject,
                            "level": level,
                            "existing_topics": week.get("topics", []),
                        },
                    )
                    suggest_response = _extract_tool_result(suggest_result)

                    if suggest_response.get("success") and suggest_response.get("result"):
                        # Agregar los tópicos sugeridos al plan (como opcionales)
                        additional = suggest_response["result"].get("suggested_topics", [])
                        for t in additional:
                            t["is_suggestion"] = True  # Marcar como sugerencia del agente
                        week.setdefault("suggested_additional_topics", []).extend(additional)
                        enriched_weeks += 1
                        logger.info(
                            "intelligence_agent.week_enriched",
                            week_number=week.get("week_number"),
                            additional_topics=len(additional),
                        )
                except Exception as e:
                    logger.warning(
                        "intelligence_agent.week_enrichment.failed",
                        week=week.get("week_number"),
                        error=str(e),
                    )

            # ── Paso 4: Guardar en PostgreSQL ─────────────────────────────────
            logger.info("intelligence_agent.saving_to_db", course_id=course_id)
            save_result = await session.call_tool(
                "tool_save_plan_to_db",
                arguments={
                    "course_id": course_id,
                    "plan_json": plan_data,
                },
            )
            save_response = _extract_tool_result(save_result)

            if not save_response.get("success"):
                return {
                    "success": False,
                    "step": "save_plan_to_db",
                    "error": save_response.get("error", "Error guardando en la base de datos"),
                    "course_id": course_id,
                    "plan_generated": True,  # El plan se generó pero no se guardó
                }

            save_data = save_response["result"]

            # ── Resultado final ───────────────────────────────────────────────
            result = {
                "success": True,
                "course_id": course_id,
                "plan_id": save_data.get("plan_id"),
                "title": title,
                "subject": subject,
                "level": level,
                "duration_months": duration_months,
                "weeks_generated": len(weeks),
                "topics_generated": save_data.get("topics_created", 0),
                "weeks_enriched": enriched_weeks,
                "plan_status": "TOPICS_SUGGESTED",
                "validation_warnings": plan_response.get("validation_warnings", []),
                "next_step": "El profesor puede revisar y seleccionar tópicos via PATCH /courses/{course_id}/topics/{topicId}/select",
            }

            logger.info(
                "intelligence_agent.run_generate_plan_flow.completed",
                **{k: v for k, v in result.items() if k != "next_step"},
            )

            return result


def _extract_tool_result(mcp_result) -> dict:
    """
    Extrae el contenido del resultado de un tool MCP.
    Los resultados MCP vienen como lista de TextContent.
    """
    try:
        if mcp_result.content:
            content = mcp_result.content[0]
            if hasattr(content, "text"):
                data = json.loads(content.text)
                return data
        return {"success": False, "error": "Resultado vacío del tool MCP"}
    except Exception as e:
        return {"success": False, "error": f"Error parseando resultado MCP: {str(e)}"}


# ── Para testing directo ──────────────────────────────────────────────────────

async def _test_flow():
    """Test local del flujo completo."""
    import uuid
    test_course_id = str(uuid.uuid4())
    print(f"\nTest con course_id ficticio: {test_course_id}")
    print("NOTA: Este test requiere un course_id real en la DB.\n")

    result = await run_generate_plan_flow(
        course_id=test_course_id,
        title="Curso de Inteligencia Artificial para Principiantes",
        subject="Inteligencia Artificial",
        duration_months=6,
        level="BEGINNER",
        description="Curso diseñado para estudiantes universitarios sin experiencia previa en IA",
        enrich_first_weeks=2,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import structlog
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
    asyncio.run(_test_flow())
