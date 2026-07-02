#!/usr/bin/env bash
set -euo pipefail

echo "=== Rhombus Production Deploy ==="

# Build frontend
echo "[1/4] Building frontend..."
cd frontend && npm ci && npm run build && cd ..

# Copy env if missing
if [ ! -f .env.prod ]; then
  echo "[2/4] Creating .env.prod from template..."
  cp .env.prod.example .env.prod
  echo "  >> Edit .env.prod with your values, then re-run this script."
  exit 1
fi

# Run migrations
echo "[2/4] Running database migrations..."
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d db redis
sleep 5
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm web python manage.py migrate

# Start all services
echo "[3/4] Starting all services..."
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build

# Done
echo "[4/4] Done! App should be live at http://$(hostname -I | awk '{print $1}')"
echo "  Frontend: http://<HOST>"
echo "  API:      http://<HOST>/api/"
echo "  Admin:    http://<HOST>/admin/"
echo ""
echo "  View logs: docker compose -f docker-compose.prod.yml logs -f"