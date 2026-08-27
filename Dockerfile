# Single container: FastAPI + Streamlit + nginx reverse proxy, one public
# port. Replaces the old backend/Dockerfile + frontend/Dockerfile pair
# (two separate Render services) — see README's Deployment section for why.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx gettext-base \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --retries 5 --timeout 120 --no-cache-dir $(awk '/^(fastapi|uvicorn|pydantic|pydantic-settings|sqlalchemy|httpx|python-dotenv|pyyaml|google-generativeai|psycopg)/ {print $1}' requirements.txt)
RUN pip install --retries 5 --timeout 120 --no-cache-dir $(awk '/^(streamlit|plotly|pandas|numpy|pyarrow)/ {print $1}' requirements.txt)
RUN pip install --retries 5 --timeout 120 --no-cache-dir $(awk '/^(scikit-learn|torch|transformers|sentence-transformers)/ {print $1}' requirements.txt)

COPY backend/ backend/
COPY frontend/ frontend/
COPY scripts/ scripts/
COPY data/ data/
COPY config/ config/
COPY artifacts/ artifacts/
COPY .streamlit/ .streamlit/
COPY deploy/nginx.conf.template /etc/nginx/nginx.conf.template
COPY deploy/start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 8080

CMD ["/app/start.sh"]
