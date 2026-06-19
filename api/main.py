"""
api/main.py

FastAPI HTTP Bridge — "The Intelligence" Agent
Expone endpoints HTTP para que el backend TypeScript pueda invocar el agente.

Puerto: 8000 (configurable via AGENT_PORT en .env)
"""
import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal
from agent.intelligence_agent import run_generate_plan_flow
from config.settings import settings

# Configurar logging estructurado
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="The Intelligence — Agent API",
    description=(
        "API HTTP para el agente de generación de planes educativos. "
        "Recibe parámetros del backend TypeScript y orquesta el flujo MCP."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — solo el backend local puede llamar al agente
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Schemas de Request/Response
# ============================================================

class GeneratePlanRequest(BaseModel):
    course_id: str = Field(..., description="UUID del curso ya creado en PostgreSQL")
    title: str = Field(..., min_length=3, max_length=200, description="Nombre del curso")
    subject: str = Field(..., min_length=2, max_length=100, description="Materia o área del curso")
    duration_months: int = Field(..., ge=1, le=24, description="Duración en meses (1-24)")
    level: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"] = Field(
        default="BEGINNER",
        description="Nivel del curso",
    )
    description: str = Field(
        default="",
        max_length=1000,
        description="Contexto adicional sobre el público objetivo",
    )
    enrich_first_weeks: int = Field(
        default=4,
        ge=0,
        le=12,
        description="Cuántas semanas enriquecer con tópicos adicionales sugeridos",
    )


class GeneratePlanResponse(BaseModel):
    success: bool
    course_id: str
    plan_id: str | None = None
    title: str
    subject: str
    level: str
    duration_months: int
    weeks_generated: int
    topics_generated: int
    weeks_enriched: int
    plan_status: str
    validation_warnings: list[str] = []
    next_step: str | None = None
    error: str | None = None


class SuggestTopicsRequest(BaseModel):
    course_id: str
    week_number: int = Field(..., ge=1)
    week_title: str
    objectives: list[str]
    subject: str
    level: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"] = "BEGINNER"


# ============================================================
# Endpoints
# ============================================================

@app.get("/health")
async def health():
    """Health check del agente."""
    return {
        "status": "healthy",
        "agent": "the-intelligence",
        "version": "1.0.0",
        "llm_model": settings.OPENROUTER_MODEL,
    }


@app.post(
    "/generate-plan",
    response_model=GeneratePlanResponse,
    summary="Genera un plan educativo completo",
    description=(
        "Recibe los parámetros del curso y orquesta el flujo MCP completo: "
        "genera el plan semana a semana, enriquece con tópicos adicionales "
        "y persiste todo en PostgreSQL."
    ),
)
async def generate_plan(request: GeneratePlanRequest):
    """
    Endpoint principal — genera y guarda un plan educativo completo.

    El backend TypeScript llama a este endpoint al crear un nuevo curso.
    """
    logger.info(
        "api.generate_plan.request",
        course_id=request.course_id,
        title=request.title,
        duration_months=request.duration_months,
        level=request.level,
    )

    try:
        result = await run_generate_plan_flow(
            course_id=request.course_id,
            title=request.title,
            subject=request.subject,
            duration_months=request.duration_months,
            level=request.level,
            description=request.description,
            enrich_first_weeks=request.enrich_first_weeks,
        )

        if not result.get("success"):
            logger.error(
                "api.generate_plan.failed",
                course_id=request.course_id,
                step=result.get("step"),
                error=result.get("error"),
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "error": result.get("error", "Error interno del agente"),
                    "step": result.get("step"),
                    "course_id": request.course_id,
                },
            )

        logger.info(
            "api.generate_plan.success",
            course_id=request.course_id,
            plan_id=result.get("plan_id"),
            weeks=result.get("weeks_generated"),
        )

        return GeneratePlanResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("api.generate_plan.unexpected_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "course_id": request.course_id},
        )


@app.post(
    "/suggest-topics",
    summary="Sugiere tópicos adicionales para una semana",
    description=(
        "Genera sugerencias de tópicos enriquecidos para una semana específica. "
        "El profesor elige cuáles implementar."
    ),
)
async def suggest_topics(request: SuggestTopicsRequest):
    """
    Genera sugerencias de tópicos para una semana del curso.
    Se puede llamar en cualquier momento después de crear el plan.
    """
    from mcp_server.tools.topic_suggester import suggest_weekly_topics

    logger.info(
        "api.suggest_topics.request",
        course_id=request.course_id,
        week_number=request.week_number,
    )

    result = suggest_weekly_topics(
        week_number=request.week_number,
        week_title=request.week_title,
        objectives=request.objectives,
        subject=request.subject,
        level=request.level,
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))

    return result


@app.get(
    "/courses/{course_id}/context",
    summary="Obtiene el contexto del curso para el agente",
)
async def get_course_context(course_id: str):
    """Lee el contexto del curso desde la base de datos."""
    from mcp_server.resources.course_context import get_course_context as _get_context
    result = _get_context(course_id)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=result.get("error", "Curso no encontrado"))
    return result


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=settings.AGENT_PORT,
        reload=True,
        log_level="info",
    )
