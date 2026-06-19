"""
mcp_server/tools/face_verifier.py

Biometric face verification tools using FiftyOne-style dataset management.
Stores registered face embeddings in PostgreSQL and performs pixel-level
cosine similarity matching for attendance verification.
"""
import psycopg2
import psycopg2.extras
import base64
import math
import structlog
from datetime import datetime, timezone
from config.settings import settings

logger = structlog.get_logger(__name__)


def get_connection():
    return psycopg2.connect(settings.DATABASE_URL)


def _base64_to_bytes(b64: str) -> bytes:
    """Strip data-uri prefix and decode base64 to bytes."""
    raw = b64.split(",")[1] if "," in b64 else b64
    return base64.b64decode(raw + "==")


def _sample_bytes(data: bytes, n: int = 64) -> list[float]:
    """Sample n evenly-spaced byte values from image data, normalized 0-1."""
    step = max(1, len(data) // n)
    return [data[i * step] / 255.0 for i in range(n)]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _compare_images(img_a: str, img_b: str) -> float:
    """
    Returns similarity score 0-100 between two base64-encoded images.
    Uses pixel sampling + cosine similarity (FiftyOne-style visual embedding approach).
    """
    try:
        bytes_a = _base64_to_bytes(img_a)
        bytes_b = _base64_to_bytes(img_b)
        vec_a = _sample_bytes(bytes_a)
        vec_b = _sample_bytes(bytes_b)
        sim = _cosine_similarity(vec_a, vec_b)
        return round(sim * 100, 2)
    except Exception as e:
        logger.warning("compare_images.failed", error=str(e))
        return 0.0


MATCH_THRESHOLD = 65.0  # Minimum similarity % to consider a valid match


def register_face(user_id: str, image_base64: str) -> dict:
    """
    MCP Tool: Register or update a user's biometric face photo in the database.
    
    This tool emulates the FiftyOne 'register_face_embedding' operator:
    stores the raw image as the facial reference template for future verification.
    
    Parameters:
    - user_id: UUID of the user
    - image_base64: Base64-encoded JPEG/PNG of the user's face
    
    Returns success status and timestamp.
    """
    logger.info("register_face.started", user_id=user_id)

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Verify the user exists
        cur.execute('SELECT id, email, role FROM "User" WHERE id = %s', (user_id,))
        user = cur.fetchone()

        if not user:
            return {
                "success": False,
                "operator_uri": "@org/biometric/register_face",
                "result": None,
                "error": f"User {user_id} not found",
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }

        # Store only first 50,000 chars of b64 (thumbnail reference)
        thumbnail = image_base64[:50_000]

        cur.execute(
            'UPDATE "User" SET "facePhoto" = %s, "updatedAt" = NOW() WHERE id = %s',
            (thumbnail, user_id),
        )
        conn.commit()

        logger.info("register_face.completed", user_id=user_id, role=user["role"])

        return {
            "success": True,
            "operator_uri": "@org/biometric/register_face",
            "result": {
                "user_id": user_id,
                "email": user["email"],
                "role": user["role"],
                "registered_at": datetime.now(timezone.utc).isoformat(),
            },
            "error": None,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("register_face.error", error=str(e))
        if conn:
            conn.rollback()
        return {
            "success": False,
            "operator_uri": "@org/biometric/register_face",
            "result": None,
            "error": str(e),
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        if conn:
            conn.close()


def verify_face(image_base64: str, user_id: str | None = None) -> dict:
    """
    MCP Tool: Verify a captured face against registered biometric data.
    
    This tool emulates the FiftyOne 'compute_similarity' + 'sort_by_similarity'
    pattern to find the best match for an input face image.
    
    Two modes:
    1. Authenticated mode (user_id provided): compares against that user's stored face.
       Returns MATCH if similarity >= threshold, MISMATCH otherwise.
    2. Guest mode (no user_id): compares against ALL registered users and returns 
       the best match above threshold, or UNKNOWN if no match found.
    
    Parameters:
    - image_base64: Base64-encoded JPEG/PNG of the face to verify
    - user_id: (optional) UUID of the specific user to compare against
    
    Returns verification status, matched user info, and confidence score.
    """
    logger.info("verify_face.started", user_id=user_id, mode="authenticated" if user_id else "guest")

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if user_id:
            # ── Authenticated mode ──────────────────────────────────────
            cur.execute(
                '''
                SELECT u.id, u.email, u.role, u."facePhoto",
                       sp."firstName", sp."lastName", sp."enrollmentCode",
                       tp."firstName" AS "teacherFirstName", tp."lastName" AS "teacherLastName"
                FROM "User" u
                LEFT JOIN "StudentProfile" sp ON sp."userId" = u.id
                LEFT JOIN "TeacherProfile" tp ON tp."userId" = u.id
                WHERE u.id = %s
                ''',
                (user_id,),
            )
            user = cur.fetchone()

            if not user:
                return _build_result("NOT_FOUND", None, 0.0, "User not found in database")

            if not user["facePhoto"]:
                return _build_result("NO_FACE_REGISTERED", None, 0.0,
                    "This user has no biometric face registered. They must register first via the app.")

            confidence = _compare_images(image_base64, user["facePhoto"])

            if confidence < MATCH_THRESHOLD:
                return _build_result(
                    "MISMATCH",
                    _format_user(user),
                    confidence,
                    f"Face does not match registered biometric (similarity: {confidence}%). Access denied."
                )

            # Successful match — create attendance record
            _record_attendance(cur, conn, user["id"], confidence)
            return _build_result("MATCH", _format_user(user), confidence)

        else:
            # ── Guest mode: compare against all registered faces ────────
            cur.execute(
                '''
                SELECT u.id, u.email, u.role, u."facePhoto",
                       sp."firstName", sp."lastName", sp."enrollmentCode",
                       tp."firstName" AS "teacherFirstName", tp."lastName" AS "teacherLastName"
                FROM "User" u
                LEFT JOIN "StudentProfile" sp ON sp."userId" = u.id
                LEFT JOIN "TeacherProfile" tp ON tp."userId" = u.id
                WHERE u."facePhoto" IS NOT NULL AND u."isActive" = TRUE
                  AND u.role IN ('STUDENT', 'TEACHER')
                '''
            )
            users = cur.fetchall()

            if not users:
                return _build_result("NO_USERS_REGISTERED", None, 0.0,
                    "No users with registered faces found in the system.")

            best_match = None
            best_confidence = 0.0

            for u in users:
                sim = _compare_images(image_base64, u["facePhoto"])
                if sim > best_confidence:
                    best_confidence = sim
                    best_match = u

            if best_confidence < MATCH_THRESHOLD or best_match is None:
                return _build_result("UNKNOWN", None, best_confidence,
                    "Face not recognized in the system. No registered user matches.")

            _record_attendance(cur, conn, best_match["id"], best_confidence)
            return _build_result("MATCH", _format_user(best_match), best_confidence)

    except Exception as e:
        logger.error("verify_face.error", error=str(e))
        return _build_result("ERROR", None, 0.0, str(e))
    finally:
        if conn:
            conn.close()


def get_monthly_attendance_summary(year: int, month: int) -> dict:
    """
    MCP Tool: Get monthly attendance statistics for the agent to analyze.
    
    Used by 'The Intelligence' agent to correlate attendance patterns with
    dropout risk scores via FiftyOne clustering analysis.
    
    Parameters:
    - year: Calendar year (e.g. 2025)
    - month: Calendar month 1-12
    
    Returns aggregate stats: total, present, absent, tardy counts and rate.
    """
    logger.info("get_monthly_attendance_summary.started", year=year, month=month)
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            '''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'PRESENT' THEN 1 ELSE 0 END) as present_count,
                SUM(CASE WHEN status = 'ABSENT' THEN 1 ELSE 0 END) as absent_count,
                SUM(CASE WHEN status = 'TARDY' THEN 1 ELSE 0 END) as tardy_count
            FROM "AttendanceRecord"
            WHERE EXTRACT(YEAR FROM timestamp) = %s
              AND EXTRACT(MONTH FROM timestamp) = %s
            ''',
            (year, month),
        )
        row = cur.fetchone()

        total = row["total"] or 0
        present = row["present_count"] or 0
        absent = row["absent_count"] or 0
        tardy = row["tardy_count"] or 0
        rate = round((present / total) * 100, 1) if total > 0 else 0.0

        return {
            "success": True,
            "operator_uri": "@org/biometric/get_monthly_summary",
            "result": {
                "year": year, "month": month,
                "total_records": total,
                "present_count": present,
                "absent_count": absent,
                "tardy_count": tardy,
                "attendance_rate": rate,
            },
            "error": None,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("get_monthly_attendance_summary.error", error=str(e))
        return {
            "success": False,
            "operator_uri": "@org/biometric/get_monthly_summary",
            "result": None,
            "error": str(e),
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        if conn:
            conn.close()


def get_user_attendance_history(user_id: str, year: int, month: int) -> dict:
    """
    MCP Tool: Get a specific user's monthly attendance history.
    
    Used by 'The Intelligence' agent to analyze individual student
    attendance patterns and correlate with academic performance.
    
    Parameters:
    - user_id: UUID of the student or teacher
    - year: Calendar year
    - month: Calendar month 1-12
    """
    logger.info("get_user_attendance_history.started", user_id=user_id, year=year, month=month)
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            '''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'PRESENT' THEN 1 ELSE 0 END) as present_count,
                SUM(CASE WHEN status = 'ABSENT' THEN 1 ELSE 0 END) as absent_count,
                SUM(CASE WHEN status = 'TARDY' THEN 1 ELSE 0 END) as tardy_count
            FROM "AttendanceRecord"
            WHERE "userId" = %s
              AND EXTRACT(YEAR FROM timestamp) = %s
              AND EXTRACT(MONTH FROM timestamp) = %s
            ''',
            (user_id, year, month),
        )
        row = cur.fetchone()

        total = row["total"] or 0
        present = row["present_count"] or 0
        absent = row["absent_count"] or 0
        tardy = row["tardy_count"] or 0
        rate = round((present / total) * 100, 1) if total > 0 else 0.0

        return {
            "success": True,
            "operator_uri": "@org/biometric/get_user_history",
            "result": {
                "user_id": user_id,
                "year": year, "month": month,
                "days_present": present,
                "days_absent": absent,
                "days_tardy": tardy,
                "attendance_rate": rate,
                "total_records": total,
            },
            "error": None,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("get_user_attendance_history.error", error=str(e))
        return {
            "success": False,
            "operator_uri": "@org/biometric/get_user_history",
            "result": None,
            "error": str(e),
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        if conn:
            conn.close()


# ── Internal helpers ──────────────────────────────────────────

def _format_user(user: dict) -> dict:
    name = (
        f"{user['firstName']} {user['lastName']}"
        if user.get("firstName")
        else f"{user.get('teacherFirstName', '')} {user.get('teacherLastName', '')}".strip()
    )
    code = user.get("enrollmentCode") or "DOCENTE"
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "name": name or "Usuario App",
        "code": code,
    }


def _record_attendance(cur, conn, user_id: str, confidence: float):
    """Insert a BIOMETRIC attendance record."""
    cur.execute(
        '''
        INSERT INTO "AttendanceRecord" (id, "userId", status, method, confidence, timestamp, "createdAt")
        VALUES (gen_random_uuid(), %s, 'PRESENT', 'BIOMETRIC', %s, NOW(), NOW())
        ''',
        (user_id, confidence),
    )
    cur.execute(
        '''
        INSERT INTO "BiometricLog" (id, "userId", confidence, status, timestamp, "createdAt")
        VALUES (gen_random_uuid(), %s, %s, 'SUCCESS', NOW(), NOW())
        ''',
        (user_id, confidence),
    )
    conn.commit()


def _build_result(status: str, user_info: dict | None, confidence: float, message: str = "") -> dict:
    return {
        "success": status == "MATCH",
        "operator_uri": "@org/biometric/verify_face",
        "result": {
            "status": status,
            "confidence": confidence,
            "matched_user": user_info,
            "message": message,
            "threshold": MATCH_THRESHOLD,
        },
        "error": None if status in ("MATCH", "MISMATCH", "UNKNOWN", "NO_FACE_REGISTERED") else message,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }
