"""
mcp_server/tools/biometric_analytics.py

Tools MCP para el Agente "The Intelligence" relacionados con el análisis predictivo.
Correlaciona datos de asistencia (PostgreSQL) con rendimiento académico utilizando FiftyOne.
"""
import os
import structlog
import asyncio
from datetime import datetime, timezone

logger = structlog.get_logger(__name__)

# Asegurar ruta de plugins de FiftyOne
if "FIFTYONE_PLUGINS_DIR" not in os.environ:
    os.environ["FIFTYONE_PLUGINS_DIR"] = "/app/plugins"

import fiftyone.operators as foo


async def run_clustering(dataset_name: str, fields: list[str], n_clusters: int = 4) -> dict:
    """
    MCP Tool: Clasifica a los estudiantes en clusters de riesgo según su asistencia y promedio académico.
    """
    logger.info("run_clustering.started", dataset_name=dataset_name, fields=fields, n_clusters=n_clusters)
    try:
        res = foo.execute_operator(
            "@org/predictive_analytics/run_clustering",
            params={
                "dataset_name": dataset_name,
                "fields": fields,
                "n_clusters": n_clusters
            }
        )
        if asyncio.iscoroutine(res) or asyncio.isfuture(res) or isinstance(res, asyncio.Future):
            res = await res
        return res.result
    except Exception as e:
        logger.error("run_clustering.error", error=str(e))
        return {
            "success": False,
            "operator_uri": "@org/predictive_analytics/run_clustering",
            "result": None,
            "error": str(e),
            "executed_at": datetime.now(timezone.utc).isoformat()
        }


async def get_dashboard_correlation(dataset_name: str) -> dict:
    """
    MCP Tool: Obtiene la URL de acceso del dashboard interactivo de FiftyOne.
    """
    logger.info("get_dashboard_correlation.started", dataset_name=dataset_name)
    try:
        res = foo.execute_operator(
            "@org/predictive_analytics/get_dashboard_correlation",
            params={
                "dataset_name": dataset_name
            }
        )
        if asyncio.iscoroutine(res) or asyncio.isfuture(res) or isinstance(res, asyncio.Future):
            res = await res
        return res.result
    except Exception as e:
        logger.error("get_dashboard_correlation.error", error=str(e))
        return {
            "success": False,
            "operator_uri": "@org/predictive_analytics/get_dashboard_correlation",
            "result": None,
            "error": str(e),
            "executed_at": datetime.now(timezone.utc).isoformat()
        }


async def flag_borderline_cases(threshold: float = 0.75) -> dict:
    """
    MCP Tool: Usa Active Learning para identificar estudiantes que rondan el umbral de deserción.
    """
    logger.info("flag_borderline_cases.started", threshold=threshold)
    try:
        res = foo.execute_operator(
            "@org/predictive_analytics/flag_borderline_cases",
            params={
                "threshold": threshold
            }
        )
        if asyncio.iscoroutine(res) or asyncio.isfuture(res) or isinstance(res, asyncio.Future):
            res = await res
        return res.result
    except Exception as e:
        logger.error("flag_borderline_cases.error", error=str(e))
        return {
            "success": False,
            "operator_uri": "@org/predictive_analytics/flag_borderline_cases",
            "result": None,
            "error": str(e),
            "executed_at": datetime.now(timezone.utc).isoformat()
        }


async def publish_risk_alert(student_id: str, evidence: dict) -> dict:
    """
    MCP Tool: Publica una alerta de riesgo de deserción al Message Broker.
    """
    logger.info("publish_risk_alert.started", student_id=student_id, evidence=evidence)
    try:
        res = foo.execute_operator(
            "@org/predictive_analytics/publish_risk_alert",
            params={
                "student_id": student_id,
                "evidence": evidence
            }
        )
        if asyncio.iscoroutine(res) or asyncio.isfuture(res) or isinstance(res, asyncio.Future):
            res = await res
        return res.result
    except Exception as e:
        logger.error("publish_risk_alert.error", error=str(e))
        return {
            "success": False,
            "operator_uri": "@org/predictive_analytics/publish_risk_alert",
            "result": None,
            "error": str(e),
            "executed_at": datetime.now(timezone.utc).isoformat()
        }


