#!/bin/bash
# Verify team colors deployment

echo "🔍 Verifying Team Colors Deployment..."
echo ""

# Check if team_colors.json exists
if [ -f "services/gateway/static/team_colors.json" ]; then
    echo "✅ team_colors.json file exists"
    TEAM_COUNT=$(python3 -c "import json; f=open('services/gateway/static/team_colors.json'); d=json.load(f); print(len(d))")
    echo "   Found $TEAM_COUNT teams in JSON"
else
    echo "❌ team_colors.json file not found"
    exit 1
fi

# Check if Docker is running
if docker ps > /dev/null 2>&1; then
    echo "✅ Docker is running"
    
    # Check if gateway container exists
    if docker compose ps gateway | grep -q gateway; then
        echo "✅ Gateway container exists"
        
        # Rebuild gateway
        echo ""
        echo "🔨 Rebuilding gateway service..."
        docker compose build gateway
        
        # Restart gateway
        echo ""
        echo "🔄 Restarting gateway service..."
        docker compose up -d gateway
        
        # Wait for service to start
        echo ""
        echo "⏳ Waiting for service to start..."
        sleep 5
        
        # Check if team_colors.json is accessible
        echo ""
        echo "🌐 Checking if team_colors.json is accessible..."
        if curl -s http://localhost:8000/static/team_colors.json | grep -q "ANA"; then
            echo "✅ team_colors.json is accessible at http://localhost:8000/static/team_colors.json"
        else
            echo "⚠️  team_colors.json may not be accessible yet (service may still be starting)"
        fi
        
        # Check gateway logs
        echo ""
        echo "📋 Recent gateway logs:"
        docker compose logs gateway --tail=5 | grep -v "^$"
        
    else
        echo "⚠️  Gateway container not running. Starting it..."
        docker compose up -d gateway
    fi
else
    echo "⚠️  Docker is not running. Please start Docker first."
    exit 1
fi

echo ""
echo "✅ Deployment verification complete!"
echo ""
echo "To test on the website:"
echo "1. Open http://localhost:8000"
echo "2. Select a game"
echo "3. Click on the 'Game' tab"
echo "4. View the head-to-head stats"
echo "5. Verify bars show team-specific colors"

