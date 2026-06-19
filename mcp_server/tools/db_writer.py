"""
mcp_server/tools/db_writer.py

Tool MCP: save_plan_to_db
Persiste el plan educativo completo en PostgreSQL usando psycopg2.
Comparte la misma base de datos que el backend TypeScript/Prisma.
"""
import json
import uuid
import structlog
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from config.settings import settings

logger = structlog.get_logger(__name__)


def get_connection():
    """Obtiene una conexión a PostgreSQL."""
    return psycopg2.connect(settings.DATABASE_URL)


def save_plan_to_db(course_id: str, plan_json: dict) -> dict:
    """
    MCP Tool: Persiste el plan educativo completo en PostgreSQL.

    Escribe en las tablas: CoursePlan, PlanWeek, Topic
    Comparte la misma DB que el backend TypeScript/Prisma.

    Args:
        course_id: UUID del curso ya creado en la DB
        plan_json: Plan estructurado generado por generate_course_plan

    Returns:
        dict con IDs creados y conteos
    """
    logger.info("save_plan_to_db.started", course_id=course_id)

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Crear CoursePlan
        plan_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute(
            """
            INSERT INTO "CoursePlan" (id, "courseId", "rawPlan", status, "createdAt", "updatedAt")
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT ("courseId") DO UPDATE
            SET "rawPlan" = EXCLUDED."rawPlan",
                status = 'DRAFT',
                "updatedAt" = EXCLUDED."updatedAt"
            RETURNING id
            """,
            (plan_id, course_id, json.dumps(plan_json), "TOPICS_SUGGESTED", now, now),
        )
        result = cur.fetchone()
        actual_plan_id = result["id"]

        # 2. Eliminar semanas previas si hay actualización
        cur.execute('DELETE FROM "PlanWeek" WHERE "planId" = %s', (actual_plan_id,))

        weeks = plan_json.get("weeks", [])
        week_ids = []
        total_topics = 0

        for week_data in weeks:
            # 3. Crear PlanWeek
            week_id = str(uuid.uuid4())
            objectives = week_data.get("objectives", [])

            cur.execute(
                """
                INSERT INTO "PlanWeek" (id, "planId", "weekNumber", title, objectives, "createdAt")
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    week_id,
                    actual_plan_id,
                    week_data.get("week_number", 0),
                    week_data.get("title", f"Semana {week_data.get('week_number', 0)}"),
                    objectives,
                    now,
                ),
            )
            week_ids.append(week_id)

            # 4. Crear Topics de la semana
            for topic_data in week_data.get("topics", []):
                topic_id = str(uuid.uuid4())
                resources = topic_data.get("resources", [])

                cur.execute(
                    """
                    INSERT INTO "Topic" (
                        id, "weekId", title, description,
                        "estimatedHours", resources, "isSelected", "createdAt"
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        topic_id,
                        week_id,
                        topic_data.get("title", ""),
                        topic_data.get("description", ""),
                        float(topic_data.get("estimated_hours", 2.0)),
                        resources,
                        False,
                        now,
                    ),
                )
                total_topics += 1

        # 5. Actualizar estado del plan
        cur.execute(
            'UPDATE "CoursePlan" SET status = %s, "updatedAt" = %s WHERE id = %s',
            ("TOPICS_SUGGESTED", now, actual_plan_id),
        )

        conn.commit()

        logger.info(
            "save_plan_to_db.completed",
            plan_id=actual_plan_id,
            weeks_created=len(week_ids),
            topics_created=total_topics,
        )

        return {
            "success": True,
            "tool": "save_plan_to_db",
            "result": {
                "plan_id": actual_plan_id,
                "course_id": course_id,
                "weeks_created": len(week_ids),
                "topics_created": total_topics,
                "status": "TOPICS_SUGGESTED",
            },
            "error": None,
        }

    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        logger.error("save_plan_to_db.db_error", error=str(e))
        return {
            "success": False,
            "tool": "save_plan_to_db",
            "result": None,
            "error": f"Error de base de datos: {str(e)}",
        }
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error("save_plan_to_db.unexpected_error", error=str(e))
        return {
            "success": False,
            "tool": "save_plan_to_db",
            "result": None,
            "error": str(e),
        }
    finally:
        if conn:
            conn.close()


def get_teacher_selections(course_id: str) -> dict:
    """
    MCP Tool: Lee los tópicos seleccionados por el profesor para un curso.

    Args:
        course_id: UUID del curso

    Returns:
        dict con los tópicos seleccionados agrupados por semana
    """
    logger.info("get_teacher_selections.started", course_id=course_id)

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                pw."weekNumber",
                pw.title as week_title,
                t.id as topic_id,
                t.title as topic_title,
                t.description,
                t."estimatedHours",
                t."isSelected",
                tts.notes,
                tts."selectedAt"
            FROM "CoursePlan" cp
            JOIN "PlanWeek" pw ON pw."planId" = cp.id
            JOIN "Topic" t ON t."weekId" = pw.id
            LEFT JOIN "TeacherTopicSelection" tts ON tts."topicId" = t.id
            WHERE cp."courseId" = %s
            ORDER BY pw."weekNumber", t."createdAt"
            """,
            (course_id,),
        )

        rows = cur.fetchall()

        # Agrupar por semana
        weeks_map = {}
        for row in rows:
            wn = row["weekNumber"]
            if wn not in weeks_map:
                weeks_map[wn] = {
                    "week_number": wn,
                    "week_title": row["week_title"],
                    "selected_topics": [],
                    "all_topics": [],
                }
            topic_info = {
                "topic_id": str(row["topic_id"]),
                "title": row["topic_title"],
                "description": row["description"],
                "estimated_hours": float(row["estimatedHours"]),
                "is_selected": row["isSelected"],
                "notes": row["notes"],
                "selected_at": row["selectedAt"].isoformat() if row["selectedAt"] else None,
            }
            weeks_map[wn]["all_topics"].append(topic_info)
            if row["isSelected"]:
                weeks_map[wn]["selected_topics"].append(topic_info)

        return {
            "success": True,
            "tool": "get_teacher_selections",
            "result": {
                "course_id": course_id,
                "weeks": list(weeks_map.values()),
                "total_selected": sum(
                    len(w["selected_topics"]) for w in weeks_map.values()
                ),
            },
            "error": None,
        }

    except Exception as e:
        logger.error("get_teacher_selections.error", error=str(e))
        return {
            "success": False,
            "tool": "get_teacher_selections",
            "result": None,
            "error": str(e),
        }
    finally:
        if conn:
            conn.close()
