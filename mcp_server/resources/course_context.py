"""
mcp_server/resources/course_context.py

MCP Resource: course://course/{course_id}/context
Expone metadatos del curso como contexto de solo lectura para que
el agente entienda el schema antes de razonar.
"""
import structlog
import psycopg2
import psycopg2.extras
from config.settings import settings
from mcp_server.tools.db_writer import get_connection

logger = structlog.get_logger(__name__)


def get_course_context(course_id: str) -> dict:
    """
    MCP Resource: Obtiene el contexto completo de un curso.

    Returns metadatos: título, materia, nivel, profesor, plan status,
    conteo de semanas y tópicos. Sin PII sensible.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                c.id,
                c.title,
                c.description,
                c."durationMonths",
                c."targetLevel",
                c.subject,
                c."createdAt",
                tp."firstName" || ' ' || tp."lastName" as teacher_name,
                tp.department,
                cp.status as plan_status,
                COUNT(DISTINCT pw.id) as weeks_count,
                COUNT(DISTINCT t.id) as topics_count,
                COUNT(DISTINCT CASE WHEN t."isSelected" THEN t.id END) as selected_topics_count
            FROM "Course" c
            LEFT JOIN "TeacherProfile" tp ON c."teacherId" = tp.id
            LEFT JOIN "CoursePlan" cp ON cp."courseId" = c.id
            LEFT JOIN "PlanWeek" pw ON pw."planId" = cp.id
            LEFT JOIN "Topic" t ON t."weekId" = pw.id
            WHERE c.id = %s
            GROUP BY c.id, tp."firstName", tp."lastName", tp.department, cp.status
            """,
            (course_id,),
        )

        row = cur.fetchone()

        if not row:
            return {"error": f"Course {course_id} not found", "found": False}

        return {
            "found": True,
            "course_id": str(row["id"]),
            "title": row["title"],
            "description": row["description"],
            "duration_months": row["durationMonths"],
            "level": row["targetLevel"],
            "subject": row["subject"],
            "teacher": row["teacher_name"],
            "department": row["department"],
            "plan_status": row["plan_status"],
            "stats": {
                "weeks_count": row["weeks_count"],
                "topics_count": row["topics_count"],
                "selected_topics_count": row["selected_topics_count"],
            },
            "active_rules": settings.PLAN_RULES,
            "created_at": row["createdAt"].isoformat() if row["createdAt"] else None,
        }

    except Exception as e:
        logger.error("get_course_context.error", course_id=course_id, error=str(e))
        return {"error": str(e), "found": False}
    finally:
        if conn:
            conn.close()
