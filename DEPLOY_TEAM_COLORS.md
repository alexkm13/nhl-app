# Team Colors Implementation - Deployment Checklist

## ✅ Changes Made

1. **Created `services/gateway/static/team_colors.json`**
   - Contains all 32 NHL team abbreviations with secondary colors
   - Accessible at `/static/team_colors.json`

2. **Backend Updated (`services/gateway/main.py`)**
   - Added `abbrev` field to `/v1/games/{game_id}/stats` response
   - Both `home_team` and `away_team` now include `abbrev` field

3. **Frontend Updated (`services/gateway/static/index.html`)**
   - Added `loadTeamColors()` function to load and cache team colors
   - Updated `createStatRow()` to accept and use team abbreviations
   - Applied team secondary colors to stat bars via inline styles
   - Updated all `createStatRow()` calls to pass abbreviations

## 🚀 Deployment Steps

### Option 1: Using Docker Compose (Recommended)

```bash
# Rebuild and restart the gateway service
cd /Users/alex/nhl-app
docker compose build gateway
docker compose up -d gateway

# Verify the service is running
docker compose ps gateway

# Check if team_colors.json is accessible
curl http://localhost:8000/static/team_colors.json
```

### Option 2: Using Makefile

```bash
# Rebuild and restart all services
make down
make up

# Or just restart gateway
docker compose restart gateway
```

## ✅ Verification Steps

1. **Check if team_colors.json is accessible:**
   ```bash
   curl http://localhost:8000/static/team_colors.json
   ```
   Should return your JSON with all 32 teams.

2. **Check if API returns abbreviations:**
   ```bash
   curl http://localhost:8000/v1/games/{game_id}/stats | jq '.home_team.abbrev, .away_team.abbrev'
   ```
   Should return team abbreviations like "TOR", "BOS", etc.

3. **Test on website:**
   - Open a game
   - Click on the "Game" tab
   - View the head-to-head stats
   - Verify that the bars show team colors (not default gray/blue)

4. **Check browser console:**
   - Open browser DevTools (F12)
   - Check Console tab for any errors loading team_colors.json
   - Should see team colors loaded successfully

## 🐛 Troubleshooting

### If team_colors.json is not accessible:
- Check that the file exists: `ls -la services/gateway/static/team_colors.json`
- Verify FastAPI static files are mounted correctly
- Check gateway logs: `docker compose logs gateway`

### If colors aren't showing:
- Check browser console for JavaScript errors
- Verify abbreviations are being returned from API
- Check that `loadTeamColors()` is being called before `createStatRow()`
- Verify abbreviations match JSON keys (case-insensitive)

### If API doesn't return abbreviations:
- Check that the backend code was saved correctly
- Verify the NHL API returns `abbrev` field in boxscore data
- Check gateway logs for errors: `docker compose logs gateway --tail=50`

## 📝 Notes

- Team colors are cached after first load (no need to reload on every request)
- Falls back to default colors (#444 for home, #0066cc for away) if abbreviation not found
- All abbreviations are converted to uppercase for matching
- The JSON file is served statically by FastAPI's StaticFiles middleware

