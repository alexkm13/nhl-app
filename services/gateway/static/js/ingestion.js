async function startIngestionForGame(gameId) {
    try {
        // Check if game is completed - don't start ingestion for completed games
        const gameCheckResponse = await fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`);
        if (gameCheckResponse.ok) {
            const gameData = await gameCheckResponse.json();
            const isFinal = gameData.game && (gameData.game.game_state === 'OFF' || gameData.game.game_state === 'FINAL');
            if (isFinal) {
                // Game is completed - don't start ingestion, just display results
                if (currentGameId === gameId) {
                    displayResults(gameData);
                }
                return;
            }
        }
        
        const response = await fetch(`${API_BASE}/v1/games/${gameId}/start`, {
            method: 'POST'
        });
        const data = await response.json();

        if (response.ok) {
            pollForResults(gameId);
        } else {
            // Show error message in game details with back button already visible
            const gameDetails = document.getElementById('gameDetails');
            const placeholder = document.getElementById('game-content-placeholder');
            if (placeholder) {
                placeholder.innerHTML = `
                    <div style="text-align: center; padding: 40px; color: #ee8888;">
                        <div style="font-size: 1.2em; margin-bottom: 10px;">Error</div>
                        <div>${data.detail || 'Unknown error'}</div>
                    </div>
                `;
            }
        }
    } catch (error) {
        // Show error message in game details with back button already visible
        const gameDetails = document.getElementById('gameDetails');
        const placeholder = document.getElementById('game-content-placeholder');
        if (placeholder) {
            placeholder.innerHTML = `
                <div style="text-align: center; padding: 40px; color: #ee8888;">
                    <div style="font-size: 1.2em; margin-bottom: 10px;">Error</div>
                    <div>${error.message}</div>
                </div>
            `;
        }
    }
}

// Function to trigger model refresh for live games (on view or stoppage)

async function triggerModelRefresh(gameId) {
    // Only refresh for live games
    if (!currentGameIsLive || currentGameId !== gameId) {
        return;
    }
    
    try {
        // Re-run ingestion to process new events and trigger new predictions
        // The backend will skip if already in progress, so this is safe
        const response = await fetch(`${API_BASE}/v1/games/${gameId}/start`, {
            method: 'POST'
        });
        // Don't wait for response - fire and forget
    } catch (error) {
        // Silently fail
    }
}


async function pollForResults(gameId) {
    try {
        // Check if game is completed - stop polling for completed games
        const gameCheckResponse = await fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`);
        if (gameCheckResponse.ok) {
            const gameData = await gameCheckResponse.json();
            const isFinal = gameData.game && (gameData.game.game_state === 'OFF' || gameData.game.game_state === 'FINAL');
            if (isFinal) {
                // Game is completed - stop polling and display results if we haven't already
                if (currentGameId === gameId && (!gameDataCache[gameId] || gameDataCache[gameId].game.id !== gameData.game.id)) {
                    displayResults(gameData);
                }
                return;
            }
        }
        
        const statusResponse = await fetch(`${API_BASE}/v1/games/${gameId}/status`);
        
        if (!statusResponse.ok) {
            throw new Error(`HTTP ${statusResponse.status}: ${statusResponse.statusText}`);
        }
        
        let statusData;
        try {
            statusData = await statusResponse.json();
        } catch (jsonError) {
            const text = await statusResponse.text();
            throw new Error(`Invalid JSON response: ${text.substring(0, 100)}`);
        }

        if (statusData.has_prediction) {
            await fetchResults(gameId);
            return;
        }

        if (statusData.ingestion_status === 'in_progress') {
            // Update placeholder to show loading state
            const placeholder = document.getElementById('game-content-placeholder');
            if (placeholder) {
                placeholder.innerHTML = '<div class="spinner"></div><div style="text-align: center; color: #aaaaaa; margin-top: 20px;">Ingestion in progress. Waiting for results...</div>';
            }
            setTimeout(() => pollForResults(gameId), 5000);
            return;
        }

        if (statusData.ingestion_status === 'failed') {
            // Show error message in game details with back button already visible
            const gameDetails = document.getElementById('gameDetails');
            const placeholder = document.getElementById('game-content-placeholder');
            if (placeholder) {
                placeholder.innerHTML = `
                    <div style="text-align: center; padding: 40px; color: #ee8888;">
                        <div style="font-size: 1.2em; margin-bottom: 10px;">Ingestion Failed</div>
                        <div>${statusData.error || 'Unknown error'}</div>
                    </div>
                `;
            }
            return;
        }

        // Update placeholder to show processing state
        const placeholder = document.getElementById('game-content-placeholder');
        if (placeholder) {
            placeholder.innerHTML = '<div class="spinner"></div><div style="text-align: center; color: #aaaaaa; margin-top: 20px;">Processing... Please wait</div>';
        }
        setTimeout(() => pollForResults(gameId), 5000);
    } catch (error) {
        console.error('Status check error:', error);
        const errorMsg = error.message || 'Network error';
        // Show error message in game details
        const placeholder = document.getElementById('game-content-placeholder');
        if (placeholder) {
            placeholder.innerHTML = `
                <div style="text-align: center; padding: 40px; color: #ee8888;">
                    <div style="font-size: 1.2em; margin-bottom: 10px;">Error</div>
                    <div>${errorMsg}</div>
                </div>
            `;
        }
    }
}


