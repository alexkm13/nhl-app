async function startIngestionForGame(gameId) {
    try {
        // Check game state to determine if this is live or backfill ingestion
        const gameCheckResponse = await fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`);
        let isFinal = false;

        if (gameCheckResponse.ok) {
            const gameData = await gameCheckResponse.json();

            // Validate gameData structure before using it
            if (gameData && gameData.game) {
                isFinal = gameData.game.game_state === 'OFF' || gameData.game.game_state === 'FINAL';

                if (isFinal) {
                    // For final games, this is a backfill operation
                    console.log(`[Backfill] Starting backfill for completed game ${gameId}`);
                } else {
                    // For live games, this is normal ingestion
                    console.log(`[Ingestion] Starting ingestion for live game ${gameId}`);
                }
            } else {
                console.warn('startIngestionForGame: invalid gameData structure', gameData);
                // Continue with ingestion attempt even if data is incomplete
            }
        }
        
        // Check ingestion status before starting
        // If ingestion is already in progress, don't fire /start again, just poll for results
        try {
            const statusResponse = await fetch(`${API_BASE}/v1/games/${gameId}/status`);
            if (statusResponse.ok) {
                const statusData = await statusResponse.json();
                
                if (statusData.ingestion_status === 'in_progress') {
                    console.log(`[Ingestion] Game ${gameId} ingestion already in progress, skipping /start and polling for results`);
                    pollForResults(gameId);
                    return;
                }
            }
        } catch (statusError) {
            // If status check fails, continue with starting ingestion
            console.warn(`[Ingestion] Status check failed for game ${gameId}, proceeding with /start:`, statusError);
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
        // Use incremental refresh to process only new events without clearing state
        // This prevents breaking the play-by-play feed during updates
        const response = await fetch(`${API_BASE}/v1/games/${gameId}/refresh`, {
            method: 'POST'
        });
        // Don't wait for response - fire and forget
    } catch (error) {
        // Silently fail - if refresh fails, fall back to polling
    }
}


async function pollForResults(gameId, retryCount = 0) {
    const MAX_RETRIES = 60; // Maximum 5 minutes of polling (60 * 5 seconds)

    // Check if we've exceeded max retries
    if (retryCount >= MAX_RETRIES) {
        console.error(`Max retries exceeded for game ${gameId}`);
        const placeholder = document.getElementById('game-content-placeholder');
        if (placeholder) {
            placeholder.innerHTML = `
                <div style="text-align: center; padding: 40px; color: #ee8888;">
                    <div style="font-size: 1.2em; margin-bottom: 10px;">Timeout</div>
                    <div>Game data took too long to load. Please try again.</div>
                </div>
            `;
        }
        return;
    }

    try {
        // Check if game is completed - for final games, wait for backfill to complete
        const gameCheckResponse = await fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`);
        if (gameCheckResponse.ok) {
            const gameData = await gameCheckResponse.json();
            const isFinal = gameData.game && (gameData.game.game_state === 'OFF' || gameData.game.game_state === 'FINAL');

            // For final games, only stop polling if we have a prediction
            // Otherwise continue polling to wait for backfill to complete
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
            await fetchResults(gameId, retryCount);
            return;
        }

        if (statusData.ingestion_status === 'in_progress') {
            // Update placeholder to show loading state
            const placeholder = document.getElementById('game-content-placeholder');
            if (placeholder) {
                placeholder.innerHTML = '<div class="spinner"></div><div style="text-align: center; color: #aaaaaa; margin-top: 20px;">Ingestion in progress. Waiting for results...</div>';
            }
            setTimeout(() => pollForResults(gameId, retryCount + 1), 5000);
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
        setTimeout(() => pollForResults(gameId, retryCount + 1), 5000);
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


