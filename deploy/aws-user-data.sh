#!/bin/bash
set -euo pipefail
REGION=us-east-1
ACCOUNT=115717305650
IMAGE="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/raut-iq:latest"

dnf install -y docker
systemctl enable --now docker
mkdir -p /opt/raut-iq
umask 077
GOOGLE_API_KEY=$(aws ssm get-parameter --name /raut-iq/GOOGLE_API_KEY --with-decryption --region "$REGION" --query Parameter.Value --output text)
OPENROUTER_API_KEY=$(aws ssm get-parameter --name /raut-iq/OPENROUTER_API_KEY --with-decryption --region "$REGION" --query Parameter.Value --output text)
DATABASE_URL=$(aws ssm get-parameter --name /raut-iq/DATABASE_URL --with-decryption --region "$REGION" --query Parameter.Value --output text)
printf 'GOOGLE_API_KEY=%s\nOPENROUTER_API_KEY=%s\nDATABASE_URL=%s\nROUTER_MODE=local\n' "$GOOGLE_API_KEY" "$OPENROUTER_API_KEY" "$DATABASE_URL" > /opt/raut-iq/app.env
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
docker pull "$IMAGE"
docker run --rm --env-file /opt/raut-iq/app.env "$IMAGE" python -m scripts.bootstrap_db
docker run -d --name raut-iq --restart unless-stopped --env-file /opt/raut-iq/app.env -p 8080:8080 "$IMAGE"
