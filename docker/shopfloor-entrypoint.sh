#!/usr/bin/env sh
set -eu

mode="${1:-mes}"

case "${mode}" in
    mes)
        mkdir -p /app/MES/data
        if [ ! -f /app/MES/data/error_notebook.json ] && [ -f /opt/shopfloor-seed/error_notebook.json ]; then
            cp /opt/shopfloor-seed/error_notebook.json /app/MES/data/error_notebook.json
        fi
        cd /app/MES
        exec streamlit run mes_app.py \
            --server.port="${STREAMLIT_SERVER_PORT:-8501}" \
            --server.address=0.0.0.0
        ;;
    mcp)
        cd /app/MCP
        exec python server.py
        ;;
    *)
        exec "$@"
        ;;
esac
