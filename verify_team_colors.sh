#!/bin/bash
echo "=== Verifying Team Colors Setup ==="
echo ""

echo "1. Checking if file exists locally..."
ls -la services/gateway/static/team_colors.json
echo ""

echo "2. Checking Docker container status..."
docker compose ps gateway
echo ""

echo "3. Checking if file exists in container..."
docker compose exec gateway ls -la /app/static/team_colors.json 2>&1 || echo "Container not running or file not found"
echo ""

echo "4. Testing /api/team_colors.json endpoint..."
curl -s http://localhost:8000/api/team_colors.json | head -3
echo ""

echo "5. Checking gateway logs for TEAM_COLORS..."
docker compose logs gateway --tail=30 2>&1 | grep -i "TEAM_COLORS" | tail -5
echo ""

echo "=== Verification Complete ==="

