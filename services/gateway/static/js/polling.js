// Polling interval constants (named constants for all intervals)
const POLLING_INTERVALS = {
    GAMES_LIST: 2000,           // 2 seconds
    GOAL_CHECK: 500,             // 500ms for fast goal detection
    FEED_UPDATE: 1000,           // 1 second for feed updates
    LIVE_SCORE: 2000,            // 2 seconds
    POWER_PLAY: 3000,            // 3 seconds
    WIN_PROB: 3000,              // 3 seconds
    RETRY_DELAY: 5000            // 5 seconds for retries
};

function startGamesListPolling(date) {
    // Stop any existing polling
    stopGamesListPolling();
    
    // Poll every 2 seconds for games list updates (to refresh live game periods/times more frequently)
    gamesListPollInterval = setInterval(async () => {
        // Only poll if we're on the games list (not in game details)
        const mainContainer = document.querySelector('.main-container');
        if (mainContainer && mainContainer.style.display !== 'none') {
            // Reload games list in background to update live game info
            try {
                const dateStr = formatDateLocal(date || new Date());
                const url = `${API_BASE}/v1/games?date=${dateStr}`;
                const response = await fetch(url);
                if (!response.ok) {
                    // Silently fail - will retry on next poll
                    return;
                }
                const data = await response.json();
                
                if (data.games && data.games.length > 0) {
                    // Update basic game info for instant display
                    data.games.forEach(game => {
                        gamesListData[game.game_id] = {
                            game_id: game.game_id,
                            home_team_name: game.home_team_name || game.home_team,
                            away_team_name: game.away_team_name || game.away_team,
                            home_team: game.home_team || '', // Abbreviation from API
                            away_team: game.away_team || '', // Abbreviation from API
                            home_team_logo: game.home_team_logo || '',
                            away_team_logo: game.away_team_logo || '',
                            home_score: game.home_score || 0,
                            away_score: game.away_score || 0,
                            game_state: game.game_state,
                            period: game.period,
                            time_in_period: game.time_in_period,
                            overtime_type: game.overtime_type || null, // OT, SO, or null
                            is_live: game.game_state === 'LIVE' || game.game_state === 'CRIT'
                        };
                    });
                    
                    // Check if there are still live games
                    const hasLiveGames = data.games.some(g => g.game_state === 'LIVE' || g.game_state === 'CRIT');
                    if (!hasLiveGames) {
                        stopGamesListPolling();
                        stopAllLiveGameFeedPolling();
                    } else {
                        // Start/update polling for all live games
                        updateLiveGameFeedPolling(data.games);
                    }
                    
                    // Only update if we're still on the games list
                    const mainContainerCheck = document.querySelector('.main-container');
                    if (mainContainerCheck && mainContainerCheck.style.display !== 'none') {
                        // Re-render games list with updated data
                        const gamesList = document.getElementById('gamesList');
                        if (gamesList) {
                            // Use the same rendering logic as loadGamesList
                            gamesList.innerHTML = data.games.map(game => {
                                const isFinal = game.game_state === 'OFF' || game.game_state === 'FINAL';
                                const homeScore = game.home_score || 0;
                                const awayScore = game.away_score || 0;
                                const homeIsWinner = homeScore > awayScore;
                                const awayIsWinner = awayScore > homeScore;
                                const isTie = homeScore === awayScore;
                                
                                // Format final status text
                                let finalStatusText = "▼ Final";
                                if (isFinal && game.overtime_type === "OT") {
                                    finalStatusText = "▼ Final/OT";
                                } else if (isFinal && game.overtime_type === "SO") {
                                    finalStatusText = "▼ Final/SO";
                                }
                                
                                if (isFinal && !isTie) {
                                    // Final game display (same as before)
                                    const awayRow = awayIsWinner ?
                                        `<div class="game-score-row winner">
                                            <div class="game-winner-indicator">▶</div>
                                            <img src="${game.away_team_logo || ''}" alt="${game.away_team_name}" class="game-team-logo" onerror="this.style.display='none'">
                                            <div class="game-team-name">${game.away_team_name || game.away_team}</div>
                                            <div class="game-team-score">${awayScore}</div>
                                        </div>` :
                                        `<div class="game-score-row loser">
                                            <img src="${game.away_team_logo || ''}" alt="${game.away_team_name}" class="game-team-logo" onerror="this.style.display='none'">
                                            <div class="game-team-name">${game.away_team_name || game.away_team}</div>
                                            <div class="game-team-score">${awayScore}</div>
                                        </div>`;
                                    
                                    const homeRow = homeIsWinner ?
                                        `<div class="game-score-row winner">
                                            <div class="game-winner-indicator">▶</div>
                                            <img src="${game.home_team_logo || ''}" alt="${game.home_team_name}" class="game-team-logo" onerror="this.style.display='none'">
                                            <div class="game-team-name">${game.home_team_name || game.home_team}</div>
                                            <div class="game-team-score">${homeScore}</div>
                                        </div>` :
                                        `<div class="game-score-row loser">
                                            <img src="${game.home_team_logo || ''}" alt="${game.home_team_name}" class="game-team-logo" onerror="this.style.display='none'">
                                            <div class="game-team-name">${game.home_team_name || game.home_team}</div>
                                            <div class="game-team-score">${homeScore}</div>
                                        </div>`;
                                    
                                    return `
                                        <div class="game-card" onclick="selectGame('${game.game_id}')">
                                            <div class="game-card-header">
                                                <span class="game-status-text">${finalStatusText}</span>
                                            </div>
                                            <div class="game-score-teams">
                                                ${awayRow}
                                                ${homeRow}
                                            </div>
                                        </div>
                                    `;
                                } else {
                                    // Live or future game display (same as before)
                                    const isLive = game.game_state === 'LIVE' || game.game_state === 'CRIT';
                                    
                                    let gameTimeDisplay = 'TBD';
                                    let periodDisplay = '';
                                    if (isLive) {
                                        // For live games, always try to show period and time remaining
                                        const period = game.period || game.periodDescriptor?.number || null;
                                        const timeInPeriod = game.time_in_period || game.timeInPeriod || null;
                                        
                                        if (period && timeInPeriod) {
                                            // Format period: "1st", "2nd", "3rd", "OT", etc.
                                            let periodLabel;
                                            if (period === 1) {
                                                periodLabel = '1st';
                                            } else if (period === 2) {
                                                periodLabel = '2nd';
                                            } else if (period === 3) {
                                                periodLabel = '3rd';
                                            } else if (period === 4) {
                                                periodLabel = 'OT';
                                            } else {
                                                periodLabel = `${period}th`;
                                            }
                                            
                                            // Convert time based on source
                                            // If is_time_remaining is true, timeInPeriod is already time remaining
                                            // If false or undefined, timeInPeriod is elapsed time and needs conversion
                                            const isTimeRemaining = game.is_time_remaining === true;
                                            let formattedTime;
                                            if (timeInPeriod && timeInPeriod !== '00:00') {
                                                if (isTimeRemaining) {
                                                    // Already time remaining, use directly
                                                    const [minutes, seconds] = timeInPeriod.split(':').map(Number);
                                                    formattedTime = `${minutes}:${seconds.toString().padStart(2, '0')}`;
                                                } else {
                                                    // Convert elapsed time to remaining
                                                    const [elapsedMinutes, elapsedSeconds] = timeInPeriod.split(':').map(Number);
                                                    const elapsedTotalSeconds = elapsedMinutes * 60 + elapsedSeconds;
                                                    
                                                    // Determine period length: 20 minutes (1200 seconds) for regulation, 5 minutes (300 seconds) for OT
                                                    const periodLengthSeconds = (period <= 3) ? 1200 : 300;
                                                    const remainingTotalSeconds = Math.max(0, periodLengthSeconds - elapsedTotalSeconds);
                                                    
                                                    const remainingMinutes = Math.floor(remainingTotalSeconds / 60);
                                                    const remainingSecs = remainingTotalSeconds % 60;
                                                    formattedTime = `${remainingMinutes}:${remainingSecs.toString().padStart(2, '0')}`;
                                                }
                                            } else {
                                                // If time is 00:00, show full period time remaining
                                                formattedTime = (period <= 3) ? '20:00' : '5:00';
                                            }
                                            
                                            // Separate time and period for display
                                            gameTimeDisplay = formattedTime;
                                            periodDisplay = periodLabel;
                                        } else {
                                            // If period/time data is missing, show default time remaining
                                            gameTimeDisplay = '20:00';
                                            periodDisplay = '1st';
                                        }
                                    } else if (game.start_time_utc) {
                                        try {
                                            const utcDate = new Date(game.start_time_utc);
                                            const localTime = utcDate.toLocaleTimeString('en-US', {
                                                hour: 'numeric',
                                                minute: '2-digit',
                                                hour12: true
                                            });
                                            gameTimeDisplay = localTime;
                                        } catch (e) {
                                            gameTimeDisplay = 'TBD';
                                        }
                                    }
                                    
                                    const showRecords = !isLive;
                                    const awayRecord = showRecords && game.away_team_record ? `<div class="game-team-record">${game.away_team_record}</div>` : '';
                                    const homeRecord = showRecords && game.home_team_record ? `<div class="game-team-record">${game.home_team_record}</div>` : '';
                                    
                                    return `
                                        <div class="game-card ${isLive ? 'live' : ''}" onclick="selectGame('${game.game_id}')">
                                            <div class="game-live-score">
                                                <div class="game-live-team-left">
                                                    <img src="${game.away_team_logo || ''}" alt="${game.away_team_name}" class="game-live-logo" onerror="this.style.display='none'">
                                                    <div class="game-live-score-num">${awayScore}</div>
                                                    <div class="game-live-team-name">${game.away_team_name || game.away_team}</div>
                                                    ${awayRecord}
                                                </div>
                                                <div class="game-live-time-container">
                                                    ${isLive ? '<div class="game-live-indicator"></div>' : ''}
                                                    <div class="game-live-time">${gameTimeDisplay}</div>
                                                    ${isLive ? 
                                                        `<div class="game-spread">${periodDisplay}</div>` :
                                                        (game.spread !== null && game.spread !== undefined ? 
                                                            `<div class="game-spread">${game.spread_favorite === 'home' ? game.home_team_name : game.away_team_name} ${game.spread > 0 ? '+' : ''}${game.spread}</div>` : 
                                                            '<div class="game-spread">N/A</div>')}
                                                </div>
                                                <div class="game-live-team-right">
                                                    <img src="${game.home_team_logo || ''}" alt="${game.home_team_name}" class="game-live-logo" onerror="this.style.display='none'">
                                                    <div class="game-live-score-num">${homeScore}</div>
                                                    <div class="game-live-team-name">${game.home_team_name || game.home_team}</div>
                                                    ${homeRecord}
                                                </div>
                                            </div>
                                        </div>
                                    `;
                                }
                            }).join('');
                        }
                    }
                }
            } catch (error) {
                // Silently handle network errors - don't spam console
                // Only log if it's a non-network error
                if (error.name !== 'TypeError' || !error.message.includes('fetch')) {
                    console.error('Error polling games list:', error);
                }
                // Will retry on next poll interval
            }
        } else {
            stopGamesListPolling();
        }
    }, POLLING_INTERVALS.GAMES_LIST); // Poll every 2 seconds for faster updates (scoreboards and times always updated)
}


function stopGamesListPolling() {
    if (gamesListPollInterval !== null) {
        clearInterval(gamesListPollInterval);
        gamesListPollInterval = null;
    }
}

// Function to update polling for all live games
// Polling is now only active when viewing a specific game, not for all games in background

function updateLiveGameFeedPolling(games) {
    const liveGames = games.filter(g => g.game_state === 'LIVE' || g.game_state === 'CRIT');
    
    // Stop polling for games that are no longer live (only if they're not currently being viewed)
    const currentLiveGameIds = new Set(liveGames.map(g => g.game_id));
    for (const gameId in liveGamesPolling) {
        // Only stop if game is no longer live AND not currently being viewed
        if (!currentLiveGameIds.has(gameId) && currentGameId !== gameId) {
            // Game is no longer live and not being viewed, stop its polling
            stopGameFeedPolling(gameId);
        }
    }
    
    // DON'T start polling for all games - only poll when viewing a specific game
    // This prevents freezing from too many simultaneous updates
}

// Function to start polling for a specific game (ONLY when viewing it)

function startGameFeedPolling(gameId, gameData) {
    // Only poll if this is the currently viewed game
    if (currentGameId !== gameId) {
        return; // Don't poll games we're not viewing
    }

    // Stop any existing polling for this game to prevent memory leaks
    stopGameFeedPolling(gameId);

    // Reset feed tracking when starting to view a new game
    renderedEventIds.clear();
    lastRenderedEventCount = 0;

    // Clear processed stoppages for previous games to prevent memory leak
    // Keep only current game's stoppages
    const currentGameStoppages = Array.from(processedStoppages).filter(id => id.startsWith(`${gameId}-`));
    processedStoppages.clear();
    currentGameStoppages.forEach(id => processedStoppages.add(id));

    // Initialize cache for this game if it doesn't exist
    if (!liveGamesFeedCache[gameId]) {
        liveGamesFeedCache[gameId] = {
            homeTeam: gameData.home_team_name || '',
            awayTeam: gameData.away_team_name || '',
            homeLogo: gameData.home_team_logo || '',
            awayLogo: gameData.away_team_logo || '',
            isLive: true
        };
    }

    // Update feed cache immediately
    updateGameFeedCache(gameId);

    // Ultra-fast polling (every 500ms) specifically for goals - goals must appear immediately
    const goalCheckInterval = setInterval(async () => {
        // Only poll if we're still viewing this game
        if (currentGameId !== gameId) {
            clearInterval(goalCheckInterval);
            if (liveGamesPolling[gameId]) {
                liveGamesPolling[gameId].goalCheckInterval = null;
            }
            return;
        }

        try {
            const response = await fetch(`${API_BASE}/v1/games/${gameId}/playbyplay?limit=10`);
            if (response.ok) {
                const data = await response.json();
                if (data.events && data.events.length > 0) {
                    const currentGoalCount = data.events.filter(e => e.event_type === 'GOAL').length;
                    const currentEventCount = data.events.length;

                    // Cache the feed data
                    if (liveGamesFeedCache[gameId]) {
                        liveGamesFeedCache[gameId].eventCount = currentEventCount;
                        liveGamesFeedCache[gameId].goalCount = currentGoalCount;
                    }

                    // If we detect ANY new events (not just goals), refresh the full feed immediately
                    const cached = liveGamesFeedCache[gameId];
                    if (cached && (currentGoalCount > (cached.lastGoalCount || 0) || currentEventCount > (cached.lastEventCount || 0))) {
                        // New events detected! Refresh full feed immediately (non-blocking)
                        // Don't await - let it run in background
                        updateGameFeedCache(gameId).catch(() => {
                            // Silently fail - errors are logged in updateGameFeedCache
                        });
                    }
                }
            }
        } catch (error) {
            // Silently handle network errors - don't spam console
            // Only log if it's a non-network error
            if (error.name !== 'TypeError' || !error.message.includes('fetch')) {
                console.error('Error in goal check interval:', error);
            }
            // Don't stop polling on errors - will retry on next poll
        }
    }, POLLING_INTERVALS.GOAL_CHECK); // Check every 500ms for goals and new events (ultra-fast for immediate goal display)

    // Normal polling every 1 second for general updates (faster feed updates)
    const pollInterval = setInterval(async () => {
        // Only poll if we're still viewing this game
        if (currentGameId !== gameId) {
            clearInterval(pollInterval);
            if (liveGamesPolling[gameId]) {
                liveGamesPolling[gameId].interval = null;
            }
            return;
        }

        try {
            // Always update feed cache for live games (faster updates) - non-blocking
            updateGameFeedCache(gameId).catch(() => {
                // Silently fail - errors are logged in updateGameFeedCache
            });

            // Also check if game is still live
            const response = await fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`);
            if (response.ok) {
                const data = await response.json();
                const isLive = data.game && (data.game.is_live || data.game.game_state === 'LIVE' || data.game.game_state === 'CRIT');

                if (!isLive) {
                    // Game is no longer live, stop polling
                    stopGameFeedPolling(gameId);
                }
            }
        } catch (error) {
            // Silently handle network errors - don't spam console
            // Only log if it's a non-network error
            if (error.name !== 'TypeError' || !error.message.includes('fetch')) {
                console.error('Error in normal polling interval:', error);
            }
            // On error, continue polling (game might still be live)
        }
    }, POLLING_INTERVALS.FEED_UPDATE); // Poll every 1 second for faster feed updates

    // Store intervals for this game
    liveGamesPolling[gameId] = {
        interval: pollInterval,
        goalCheckInterval: goalCheckInterval,
        gameData: gameData
    };
}

// Track ongoing updates to prevent conflicts
// Note: ongoingFeedUpdates is defined in state.js

// Function to update feed cache for a game (background update)

function stopGameFeedPolling(gameId) {
    if (liveGamesPolling[gameId]) {
        if (liveGamesPolling[gameId].interval) {
            clearInterval(liveGamesPolling[gameId].interval);
        }
        if (liveGamesPolling[gameId].goalCheckInterval) {
            clearInterval(liveGamesPolling[gameId].goalCheckInterval);
        }
        delete liveGamesPolling[gameId];
    }
}

// Function to stop all background game feed polling

function stopAllLiveGameFeedPolling() {
    for (const gameId in liveGamesPolling) {
        stopGameFeedPolling(gameId);
    }
    liveGamesPolling = {};
}

// Function to stop polling when navigating away from a game

function stopPollingForCurrentGame() {
    if (currentGameId) {
        stopGameFeedPolling(currentGameId);
    }
}


function stopPlayByPlayPolling() {
    if (playByPlayPollInterval !== null) {
        clearInterval(playByPlayPollInterval);
        playByPlayPollInterval = null;
    }
    if (goalCheckPollInterval !== null) {
        clearInterval(goalCheckPollInterval);
        goalCheckPollInterval = null;
    }
}


function startPowerPlayPolling(gameId) {
    // Stop any existing polling
    stopPowerPlayPolling();
    
    // Poll every 1 second for power play status updates (more frequent for better responsiveness)
    powerPlayPollInterval = setInterval(async () => {
        // Only check if we're still viewing this game
        const powerPlayDisplay = document.getElementById('powerplay-display');
        if (!powerPlayDisplay || currentGameId !== gameId) {
            stopPowerPlayPolling();
            return;
        }
        
        // Update power play status
        loadPowerPlayStatus(gameId);
    }, POLLING_INTERVALS.POWER_PLAY); // Poll every 3 seconds
}


function stopPowerPlayPolling() {
    if (powerPlayPollInterval !== null) {
        clearInterval(powerPlayPollInterval);
        powerPlayPollInterval = null;
    }
}


function startLiveScorePolling(gameId) {
    // Stop any existing polling
    stopLiveScorePolling();
    
    // Poll every 2 seconds for live scores and times
    liveScorePollInterval = setInterval(async () => {
        // Only poll if we're still viewing this game and it's still live
        if (currentGameId === gameId && currentGameIsLive) {
            try {
                const response = await fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`);
                if (response.ok) {
                    const data = await response.json();
                    // Update only the score display, not the entire page
                    updateLiveScoreDisplay(data);
                    // Also update currentGameIsLive in case it changed
                    const isLive = data.game && (data.game.is_live || data.game.game_state === 'LIVE' || data.game.game_state === 'CRIT');
                    currentGameIsLive = isLive;
                    if (!isLive) {
                        stopLiveScorePolling();
                    }
                }
            } catch (error) {
                // Silently handle network errors - don't spam console
                // Only log if it's a non-network error
                if (error.name !== 'TypeError' || !error.message.includes('fetch')) {
                    console.error('Error updating live score:', error);
                }
            }
        } else {
            // Stop polling if we've navigated away or game is no longer live
            stopLiveScorePolling();
        }
    }, POLLING_INTERVALS.LIVE_SCORE); // Poll every 2 seconds for live score updates
}


function stopLiveScorePolling() {
    if (liveScorePollInterval !== null) {
        clearInterval(liveScorePollInterval);
        liveScorePollInterval = null;
    }
}


function updateLiveScoreDisplay(data) {
    const game = data.game;
    const score = data.score;
    
    // Guard against missing score data - the endpoint may return minimal payload
    // before ingestion finishes or if the game isn't in Redis yet
    if (!score || !score.home || !score.away) {
        console.warn('Live score update missing score info', data);
        return; // Skip update if score data is incomplete
    }
    
    // Guard against missing game data
    if (!game) {
        console.warn('Live score update missing game info', data);
        return;
    }
    
    const homeScore = score.home.goals;
    const awayScore = score.away.goals;
    const period = game.period || 1;
    const timeInPeriod = game.time_in_period || '00:00';
    const isLive = game.is_live || false;
    
    // Convert time elapsed to time remaining
    // timeInPeriod is elapsed time in MM:SS format (e.g., "00:30" = 30 seconds elapsed)
    // We need to convert to time remaining
    let timeDisplay = '';
    if (timeInPeriod && timeInPeriod !== '00:00') {
        const [elapsedMinutes, elapsedSeconds] = timeInPeriod.split(':').map(Number);
        const elapsedTotalSeconds = elapsedMinutes * 60 + elapsedSeconds;
        
        // Determine period length: 20 minutes (1200 seconds) for regulation, 5 minutes (300 seconds) for OT
        const periodLengthSeconds = (period <= 3) ? 1200 : 300;
        const remainingTotalSeconds = Math.max(0, periodLengthSeconds - elapsedTotalSeconds);
        
        const remainingMinutes = Math.floor(remainingTotalSeconds / 60);
        const remainingSecs = remainingTotalSeconds % 60;
        timeDisplay = `${remainingMinutes}:${remainingSecs.toString().padStart(2, '0')}`;
    } else {
        // If time is 00:00, show full period time remaining
        timeDisplay = (period <= 3) ? '20:00' : '5:00';
    }
    
    // Format period - use the same format as in displayResults
    let periodDisplay = '';
    if (period === 1) {
        periodDisplay = '1st';
    } else if (period === 2) {
        periodDisplay = '2nd';
    } else if (period === 3) {
        periodDisplay = '3rd';
    } else if (period === 4) {
        periodDisplay = 'OT';
    } else {
        periodDisplay = `${period}th`;
    }
    
    // Update score displays
    const scoreElements = document.querySelectorAll('.live-team-score');
    if (scoreElements.length >= 2) {
        scoreElements[0].textContent = awayScore;
        scoreElements[1].textContent = homeScore;
    }
    
    // Update time and period - these must be updated in real-time
    const timeElement = document.querySelector('.live-time-remaining');
    if (timeElement) {
        timeElement.textContent = timeDisplay;
    }
    
    const periodElement = document.querySelector('.live-period');
    if (periodElement) {
        periodElement.textContent = periodDisplay;
    }
    
    // Update live indicator
    const liveIndicator = document.querySelector('.live-status-info');
    if (liveIndicator && !isLive) {
        // Game ended, stop polling
        stopLiveScorePolling();
        currentGameIsLive = false;
    }
}


async function updateGameFeedCache(gameId) {
    // Prevent multiple simultaneous updates for the same game
    // Use timestamp tracking to make check-and-set atomic
    const updateKey = `${gameId}-${Date.now()}`;
    if (ongoingFeedUpdates.has(gameId)) {
        return;
    }

    ongoingFeedUpdates.add(gameId);
    const startTime = Date.now();
    try {
        const response = await fetch(`${API_BASE}/v1/games/${gameId}/playbyplay?limit=50`);
        if (!response.ok) {
            console.error(`[Feed] Failed to fetch play-by-play for ${gameId}: ${response.status} ${response.statusText}`);
            return;
        }
        
        const data = await response.json();
        // Only log if we have events to help debug
        if (data.events && data.events.length > 0) {
            console.log(`[Feed] Received data for ${gameId}:`, {
                hasEvents: !!data.events,
                eventCount: data.events?.length || 0,
                gameState: data.game_state
            });
        }
        
        if (data.events) {
            const cached = liveGamesFeedCache[gameId];
            if (cached) {
                cached.events = data.events;
                cached.lastEventCount = data.events.length;
                cached.lastGoalCount = data.events.filter(e => e.event_type === 'GOAL').length;
                cached.lastUpdate = Date.now();
                // Update game state from API response
                if (data.game_state) {
                    cached.gameState = data.game_state;
                }
                
                // If this is the currently viewed game, update the display
                if (currentGameId === gameId) {
                    const feed = document.getElementById('playbyplay-feed');
                    if (feed) {
                        try {
                            // Update the feed display using cached data
                            const isLive = cached.isLive !== undefined ? cached.isLive : (data.game_state === 'LIVE' || data.game_state === 'CRIT');
                            renderFeedEvents(cached.events, cached.homeTeam, cached.awayTeam, cached.homeLogo, cached.awayLogo, isLive, gameId, data.game_state);
                        } catch (renderError) {
                            console.error('Error rendering feed events:', renderError);
                            // Don't stop polling on render errors
                        }
                    }
                }
            } else {
                // Initialize cache if it doesn't exist
                if (!liveGamesFeedCache[gameId]) {
                    const gameData = liveGamesPolling[gameId]?.gameData || {};
                    liveGamesFeedCache[gameId] = {
                        homeTeam: gameData.home_team_name || '',
                        awayTeam: gameData.away_team_name || '',
                        homeLogo: gameData.home_team_logo || '',
                        awayLogo: gameData.away_team_logo || '',
                        isLive: true
                    };
                }
                const cached = liveGamesFeedCache[gameId];
                if (cached) {
                    cached.events = data.events || [];
                    cached.lastEventCount = data.events ? data.events.length : 0;
                    cached.lastGoalCount = data.events ? data.events.filter(e => e.event_type === 'GOAL').length : 0;
                    cached.lastUpdate = Date.now();
                }
            }
        }
    } catch (error) {
        // Silently handle network errors - don't spam console
        // Only log if it's a non-network error or if it's the first error
        if (error.name !== 'TypeError' || !error.message.includes('fetch')) {
            console.error('Error updating feed cache:', error);
        }
        // Don't stop polling on errors - will retry on next poll
    } finally {
        // Only remove if this is still the most recent update (prevent race condition)
        // Check if enough time has passed to ensure this update completed
        const elapsed = Date.now() - startTime;
        if (elapsed > 0) {  // Always true, but ensures we're in finally block
            ongoingFeedUpdates.delete(gameId);
        }
    }
}

// Function to stop polling for a specific game

