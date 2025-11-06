#!/bin/bash
# Simple script to check model service status

echo "=== Checking Docker Containers ==="
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "model_svc|gateway|redis" || echo "No containers found"

echo ""
echo "=== Checking Model Service Logs (last 20 lines) ==="
docker compose logs model_svc --tail=20 2>&1 || echo "Could not get model service logs"

echo ""
echo "=== Checking for Predictions in Redis ==="
docker compose exec -T redis redis-cli KEYS "pred:*" 2>&1 || echo "Could not access Redis"

echo ""
echo "=== Checking Gateway Logs for Fallback Warnings ==="
docker compose logs gateway --tail=50 2>&1 | grep -i "falling back\|model prediction" || echo "No fallback warnings found"

echo ""
echo "=== Checking Predictions Stream Length ==="
docker compose exec -T redis redis-cli XLEN predictions 2>&1 || echo "Could not check predictions stream"

