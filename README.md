# The Intelligence — Agente de Análisis Predictivo Educativo

Agente MCP para generación de planes educativos estructurados, construido para el Hackathon Voxel51/FiftyOne.

## Arquitectura

```
[POST /courses (Backend TS)] → [FastAPI Bridge :8000] → [MCP Client]
                                                               ↓
                                                    [FastMCP Server (stdio)]
                                                         Tools:
                                                    ├── generate_course_plan
                                                    ├── suggest_weekly_topics
                                                    ├── save_plan_to_db
                                                    ├── get_teacher_selections
                                                    └── finalize_course_plan
                                                               ↓
                                                    [GPT-4o via OpenRouter]
                                                               ↓
                                                    [PostgreSQL compartida]
```

## Instalación

```bash
python3 -m pip install mcp fastmcp openai fastapi uvicorn psycopg2-binary \
    python-dotenv pydantic httpx structlog
```

## Configuración

Edita `.env`:
```
OPENROUTER_API_KEY=sk-or-v1-...
DATABASE_URL=postgresql://postgres:postgres@localhost:5435/hacklaton_db
AGENT_PORT=8000
```

## Inicio

```bash
bash run_agent.sh
```

El agente queda disponible en `http://localhost:8000`

## Endpoints

| Método | URL | Descripción |
|--------|-----|-------------|
| GET | `/health` | Health check del agente |
| POST | `/generate-plan` | Genera plan educativo completo |
| POST | `/suggest-topics` | Sugerencias adicionales por semana |
| GET | `/courses/{id}/context` | Contexto del curso |
| GET | `/docs` | Swagger UI (FastAPI) |

## Flujo del Profesor

1. **Crear curso** → `POST /courses` (backend TS) → el agente genera el plan automáticamente
2. **Ver tópicos** → `GET /courses/:id/topics` → lista por semana
3. **Seleccionar tópicos** → `PATCH /courses/:id/topics/:topicId/select`
4. **Pedir más sugerencias** → `POST /courses/:id/weeks/:n/suggest`
5. **Finalizar** → `POST /courses/:id/finalize`

## Tools MCP

```python
# Generar plan completo (6 meses de IA para principiantes)
tool_generate_course_plan(
    title="Ingeniería en IA",
    subject="Inteligencia Artificial",
    duration_months=6,
    level="BEGINNER",
    description="Para universitarios sin experiencia previa"
)

# Sugerir tópicos adicionales para la semana 3
tool_suggest_weekly_topics(
    week_number=3,
    week_title="Fundamentos de Machine Learning",
    objectives=["Entender regresión lineal", "Implementar k-means"],
    subject="IA",
    level="BEGINNER"
)
```

## Reglas Activas

El agente aplica estas reglas en cada plan generado:

- **Min tópicos/semana**: 2
- **Max tópicos/semana**: 6
- **Max horas/semana**: 20h
- **BEGINNER**: 60% teoría / 40% práctica
- **INTERMEDIATE**: 50% / 50%
- **ADVANCED**: 30% teoría / 70% práctica

## Stack

- Python 3.11+ / FastAPI / FastMCP
- GPT-4o via OpenRouter
- PostgreSQL 15 (compartida con backend TS)
- Prisma schema compatible (tablas: Course, CoursePlan, PlanWeek, Topic)