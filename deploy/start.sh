#!/usr/bin/env bash
# Single-container startup: FastAPI + Streamlit as background processes,
# nginx as the foreground process reverse-proxying both behind one port.
# See deploy/nginx.conf.template for the routing rules.
set -euo pipefail

: "${PORT:=8080}"
export PORT

# Only ${PORT} is substituted — nginx's own $host/$http_upgrade/$remote_addr
# must survive untouched, so we don't run a bare `envsubst` with no arg list.
envsubst '${PORT}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
streamlit run frontend/streamlit_app.py \
    --server.address=0.0.0.0 --server.port=8501 --server.headless=true &

exec nginx -g "daemon off;"
