# Single container: FastAPI + Streamlit + nginx reverse proxy, one public
# port. Replaces the old backend/Dockerfile + frontend/Dockerfile pair
# (two separate Render services) — see README's Deployment section for why.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx gettext-base \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY config/ config/
COPY .streamlit/ .streamlit/
COPY deploy/nginx.conf.template /etc/nginx/nginx.conf.template
COPY deploy/start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 8080

CMD ["/app/start.sh"]
