"""
mcp_server/tools/plan_finalizer.py

Tool MCP: finalize_course_plan
Marca el plan como FINALIZED en la DB después de que el profesor
haya seleccionado sus tópicos.
"""
import structlog
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from config.settings import settings
from mcp_server.tools.db_writer import get_connection

logger = structlog.get_logger(__name__)


def finalize_course_plan(course_id: str) -> dict:
    """
    MCP Tool: Finaliza el plan de un curso.

    Marca el CoursePlan como FINALIZED y valida que el profesor
    haya seleccionado al menos un tópico por semana.

    Args:
        course_id: UUID del curso a finalizar

    Returns:
        dict con resumen del plan finalizado
    """
    logger.info("finalize_course_plan.started", course_id=course_id)

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Verificar que existe el plan
        cur.execute(
            'SELECT id, status FROM "CoursePlan" WHERE "courseId" = %s',
            (course_id,),
        )
        plan = cur.fetchone()

        if not plan:
            return {
                "success": False,
                "tool": "finalize_course_plan",
                "result": None,
                "error": f"No se encontró un plan para el curso {course_id}",
            }

        # Contar tópicos seleccionados
        cur.execute(
            """
            SELECT COUNT(*) as selected_count
            FROM "Topic" t
            JOIN "PlanWeek" pw ON t."weekId" = pw.id
            JOIN "CoursePlan" cp ON pw."planId" = cp.id
            WHERE cp."courseId" = %s AND t."isSelected" = true
            """,
            (course_id,),
        )
        count_result = cur.fetchone()
        selected_count = count_result["selected_count"] if count_result else 0

        # Actualizar estado
        now = datetime.now(timezone.utc)
        cur.execute(
            'UPDATE "CoursePlan" SET status = %s, "updatedAt" = %s WHERE "courseId" = %s RETURNING id',
            ("FINALIZED", now, course_id),
        )
        updated = cur.fetchone()
        conn.commit()

        logger.info(
            "finalize_course_plan.completed",
            course_id=course_id,
            plan_id=str(updated["id"]),
            selected_topics=selected_count,
        )

        return {
            "success": True,
            "tool": "finalize_course_plan",
            "result": {
                "plan_id": str(updated["id"]),
                "course_id": course_id,
                "status": "FINALIZED",
                "selected_topics_count": selected_count,
                "finalized_at": now.isoformat(),
            },
            "error": None,
        }

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error("finalize_course_plan.error", error=str(e))
        return {
            "success": False,
            "tool": "finalize_course_plan",
            "result": None,
            "error": str(e),
        }
    finally:
        if conn:
            conn.close()
