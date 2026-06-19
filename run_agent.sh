#!/bin/bash
# run_agent.sh — Lanza el servidor HTTP del agente "The Intelligence"
# Uso: bash run_agent.sh

set -e

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================="
echo "🧠 The Intelligence Agent — Starting"
echo "=============================================="
echo "📁 Directory: $AGENT_DIR"
echo "🐍 Python: $(python3 --version)"
echo ""

# Cargar .env
if [ -f "$AGENT_DIR/.env" ]; then
    export $(grep -v '^#' "$AGENT_DIR/.env" | xargs)
    echo "✅ Environment loaded from .env"
fi

# Verificar conexión a PostgreSQL
echo "🔌 Testing PostgreSQL connection..."
python3 -c "
import psycopg2
import os
try:
    conn = psycopg2.connect(os.environ.get('DATABASE_URL', ''))
    conn.close()
    print('✅ PostgreSQL: Connected')
except Exception as e:
    print(f'⚠️  PostgreSQL: {e}')
"

echo ""
echo "🚀 Starting FastAPI server on port ${AGENT_PORT:-8000}"
echo "📖 Docs: http://localhost:${AGENT_PORT:-8000}/docs"
echo "=============================================="

cd "$AGENT_DIR"
python3 -m uvicorn api.main:app \
    --host 0.0.0.0 \
    --port "${AGENT_PORT:-8000}" \
    --reload \
    --log-level info
