# Full Docker Restart Instructions

The team colors endpoint isn't working. Let's do a complete restart to ensure everything is fresh.

## Step 1: Stop All Services
```bash
cd /Users/alex/nhl-app
docker compose down
```

## Step 2: Rebuild Gateway Service (No Cache)
```bash
docker compose build --no-cache gateway
```

This ensures the file is copied into the container.

## Step 3: Start Gateway Service
```bash
docker compose up -d gateway
```

## Step 4: Wait for Service to Start
```bash
sleep 5
```

## Step 5: Verify File Exists in Container
```bash
docker compose exec gateway ls -la /app/static/team_colors.json
```

Should show: `-rw-r--r-- 1 root root ... team_colors.json`

## Step 6: Test the Endpoint
```bash
curl http://localhost:8000/api/team_colors.json
```

Should return JSON with 32 teams.

## Step 7: Check Logs
```bash
docker compose logs gateway --tail=50 | grep -i "TEAM_COLORS"
```

Should show log messages like:
- `[TEAM_COLORS] Looking for team_colors.json at: ...`
- `[TEAM_COLORS] Successfully loaded team colors: 32 teams`

## Troubleshooting

If the file doesn't exist in the container:
```bash
# Check if file exists locally
ls -la services/gateway/static/team_colors.json

# If it exists, rebuild with --no-cache
docker compose build --no-cache gateway
docker compose restart gateway
```

If the endpoint still returns 404:
```bash
# Check all routes
curl http://localhost:8000/docs

# Check if service is running
docker compose ps gateway

# Check logs for errors
docker compose logs gateway --tail=100
```

## Alternative: Restart All Services
```bash
docker compose down
docker compose up -d --build
```

This will restart everything and rebuild all services.

