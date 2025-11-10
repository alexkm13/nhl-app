async function displayResults(data) {
    const gameDetails = document.getElementById('gameDetails');
    
    // Validate required data structure - guard against missing/incomplete data
    if (!data) {
        console.error('displayResults called with undefined data');
        if (gameDetails) {
            gameDetails.innerHTML = `
                <div class="back-button-container">
                    <button class="back-button" onclick="showGamesList()">← Back to Games</button>
                </div>
                <div style="text-align: center; padding: 40px; color: #ee8888;">
                    <div style="font-size: 1.2em; margin-bottom: 10px;">Error Loading Game</div>
                    <div>Invalid data received</div>
                </div>
            `;
            gameDetails.style.display = 'block';
            gameDetails.classList.add('show');
        }
        return;
    }
    
    // Validate game data
    if (!data.game) {
        console.error('displayResults: missing game data', data);
        if (gameDetails) {
            gameDetails.innerHTML = `
                <div class="back-button-container">
                    <button class="back-button" onclick="showGamesList()">← Back to Games</button>
                </div>
                <div style="text-align: center; padding: 40px; color: #ee8888;">
                    <div style="font-size: 1.2em; margin-bottom: 10px;">Error Loading Game</div>
                    <div>Game data not available</div>
                </div>
            `;
            gameDetails.style.display = 'block';
            gameDetails.classList.add('show');
        }
            return;
        }
    
    // Validate score data
    if (!data.score || !data.score.home || !data.score.away) {
        console.error('displayResults: missing score data', data);
        if (gameDetails) {
            gameDetails.innerHTML = `
                <div class="back-button-container">
                    <button class="back-button" onclick="showGamesList()">← Back to Games</button>
                </div>
                <div style="text-align: center; padding: 40px; color: #ee8888;">
                    <div style="font-size: 1.2em; margin-bottom: 10px;">Error Loading Game</div>
                    <div>Score data not available. The game may still be loading.</div>
                </div>
            `;
            gameDetails.style.display = 'block';
            gameDetails.classList.add('show');
        }
        return;
    }
    
    // Validate win probability data
    if (!data.win_probability) {
        console.error('displayResults: missing win_probability data', data);
        // Continue with default probabilities rather than failing completely
    }
    
    const game = data.game;
    const score = data.score;
    const situation = data.current_situation;
    const winProb = data.win_probability || {};

    // Validate team names exist in score data
    const homeTeam = score.home.team || 'Home Team';
    const awayTeam = score.away.team || 'Away Team';
    const homeScore = score.home.goals !== undefined ? score.home.goals : 0;
    const awayScore = score.away.goals !== undefined ? score.away.goals : 0;

    // Get win probabilities with fallbacks
    const homeProb = winProb[homeTeam] !== undefined ? winProb[homeTeam] : 50.0;
    const awayProb = winProb[awayTeam] !== undefined ? winProb[awayTeam] : 50.0;

    // Validate game ID exists
    if (!data.game.id) {
        console.error('displayResults: missing game ID', data);
        if (gameDetails) {
            gameDetails.innerHTML = `
                <div class="back-button-container">
                    <button class="back-button" onclick="showGamesList()">← Back to Games</button>
                </div>
                <div style="text-align: center; padding: 40px; color: #ee8888;">
                    <div style="font-size: 1.2em; margin-bottom: 10px;">Error Loading Game</div>
                    <div>Game ID not available</div>
                </div>
            `;
            gameDetails.style.display = 'block';
            gameDetails.classList.add('show');
        }
        return;
    }

    const gameId = data.game.id;
    const isLive = data.game.is_live || data.game.game_state === 'LIVE' || data.game.game_state === 'CRIT';
    const isFinal = data.game.game_state === 'OFF' || data.game.game_state === 'FINAL';
    
    // Start ingestion for all games (live or final) to ensure backfill for offline games
    // This ensures that even games not watched live will have model predictions and play-by-play data
        if (!ingestionStartedForGames.has(gameId)) {
            ingestionStartedForGames.add(gameId);
            startIngestionForGame(gameId).catch(() => {
                // Silently fail - ingestion may already be in progress or game may not exist
                // Remove from set if it fails so we can retry later if needed
                ingestionStartedForGames.delete(gameId);
            });
        } else if (isLive) {
            // For live games we've already started, trigger a refresh to get latest state
            triggerModelRefresh(gameId).catch(() => {
                // Silently fail
            });
    }
    
    // Hide games list and show game details
    showGameDetails();
    
    // Fetch historical win probability data for graphing
    let historyData = [];
    try {
        const historyResponse = await fetch(`${API_BASE}/v1/games/${gameId}/winprob/history`);
        if (historyResponse.ok) {
            const historyResult = await historyResponse.json();
            historyData = historyResult.data || [];
        }
        
        // For LIVE games only: Add current prediction to history array
        // Completed games already have full history in database
        if (isLive) {
            try {
                const currentPredResponse = await fetch(`${API_BASE}/v1/games/${gameId}/winprob`);
                if (currentPredResponse.ok) {
                    const currentPred = await currentPredResponse.json();
                    
                    // Get game start time to calculate relative time
                    // The history endpoint returns data with relative time (ts from game start)
                    // We need to calculate relative time for current prediction
                    let relativeTime = 0;
                    
                    if (historyData.length > 0) {
                        // Estimate relative time from last history point
                        // Assume current prediction is a few seconds after last point
                        const lastPoint = historyData[historyData.length - 1];
                        relativeTime = lastPoint.ts + 10; // Add 10 seconds as estimate
                    } else {
                        // No history yet, estimate from game state
                        // Get period and time info from the data we already have
                        const period = data.game.period || 1;
                        const timeInPeriod = data.game.time_in_period || '00:00';
                        
                        // Calculate elapsed time - validate time format before parsing
                        try {
                            if (timeInPeriod && typeof timeInPeriod === 'string' && timeInPeriod.includes(':')) {
                                const parts = timeInPeriod.split(':');
                                if (parts.length === 2) {
                                    const minutes = Number(parts[0]);
                                    const seconds = Number(parts[1]);
                                    // Validate that both are finite numbers
                                    if (Number.isFinite(minutes) && Number.isFinite(seconds)) {
                            const elapsedInPeriod = minutes * 60 + seconds;
                            const periodOffset = (period - 1) * 1200; // 20 minutes per period
                            relativeTime = periodOffset + elapsedInPeriod;
                                    } else {
                                        // Invalid numbers, use fallback
                                        relativeTime = 10;
                                    }
                                } else {
                                    // Invalid format, use fallback
                                    relativeTime = 10;
                                }
                            } else {
                                // Invalid time format, use fallback
                                relativeTime = 10;
                            }
                        } catch (e) {
                            // Fallback: use a small positive value
                            console.warn('Error parsing timeInPeriod:', timeInPeriod, e);
                            relativeTime = 10;
                        }
                    }
                    
                    const currentPoint = {
                        ts: Math.max(0, relativeTime), // Ensure non-negative
                        p_home_win: currentPred.p_home_win
                    };
                    
                    // Add to history if not already present (check by timestamp proximity)
                    const exists = historyData.some(h => Math.abs(h.ts - currentPoint.ts) < 5);
                    if (!exists) {
                        historyData.push(currentPoint);
                        // Sort by timestamp
                        historyData.sort((a, b) => a.ts - b.ts);
                    }
                }
            } catch (error) {
                // Silently fail - current prediction may not be available yet
            }
        }
    } catch (error) {
        console.error('Error fetching win probability history:', error);
    }
    
    // If history data is sparse or missing, generate probability points from game events
    // This ensures the graph shows changes even if database predictions are limited
    if (historyData.length < 10) {
        try {
            // Fetch play-by-play to generate probability points from game events
            const playByPlayResponse = await fetch(`${API_BASE}/v1/games/${gameId}/playbyplay`);
            if (playByPlayResponse.ok) {
                const playByPlayData = await playByPlayResponse.json();
                const events = playByPlayData.events || [];
                
                // Filter for crucial events (goals, major score changes)
                const crucialEvents = events.filter(e => e.event_type === 'GOAL' || e.event_type === 'PENALTY');
                
                // Generate probability points at these events
                // We'll use a simple calculation: probability changes based on score differential and time
                let homeScore = 0;
                let awayScore = 0;
                let gameTime = 0;
                const generatedPoints = [];
                
                // Add initial point at game start (50/50)
                generatedPoints.push({ ts: 0, p_home_win: 0.5 });
                
                // Process events chronologically (oldest first)
                // Events come from backend most recent first, so we need to sort chronologically
                // time_in_period from play-by-play events is TIME REMAINING, not elapsed
                // More remaining = earlier in period, less remaining = later in period
                const sortedEvents = [...crucialEvents].sort((a, b) => {
                    // Sort by period (ascending), then by time_in_period (descending for remaining time)
                    if (a.period !== b.period) return a.period - b.period;
                    // Convert time_in_period from MM:SS to seconds for comparison
                    // time_in_period is REMAINING time, so larger = more remaining = earlier in period
                    const aTime = a.time_in_period ? (parseInt(a.time_in_period.split(':')[0]) * 60 + parseInt(a.time_in_period.split(':')[1]) || 0) : 0;
                    const bTime = b.time_in_period ? (parseInt(b.time_in_period.split(':')[0]) * 60 + parseInt(b.time_in_period.split(':')[1]) || 0) : 0;
                    return bTime - aTime; // Descending order (most remaining = oldest first)
                });
                
                // Calculate game time and probability for each event
                for (const event of sortedEvents) {
                    // Update score BEFORE calculating probability (so probability reflects score after this goal)
                    if (event.event_type === 'GOAL') {
                        if (event.team === 'HOME') {
                            homeScore++;
    } else {
                            awayScore++;
                        }
                    }
                    
                    // Calculate game time in seconds
                    const period = event.period || 1;
                    const timeInPeriod = event.time_in_period || '20:00';
                    // Check split returns exactly 2 elements before parsing
                    const timeParts = timeInPeriod.split(':');
                    const minutes = (timeParts.length === 2) ? Number(timeParts[0]) || 0 : 0;
                    const secs = (timeParts.length === 2) ? Number(timeParts[1]) || 0 : 0;
                    const timeInPeriodSeconds = minutes * 60 + secs;
                    
                    // time_in_period is TIME REMAINING in period, so convert to elapsed
                    const periodLength = period <= 3 ? 1200 : 300; // 20 min for regulation, 5 min for OT
                    const elapsedInPeriod = Math.max(0, periodLength - timeInPeriodSeconds);
                    
                    // Total game time (elapsed from game start)
                    if (period <= 3) {
                        gameTime = (period - 1) * 1200 + elapsedInPeriod;
                    } else {
                        gameTime = 3600 + (period - 4) * 300 + elapsedInPeriod;
                    }
                    
                    // Calculate probability based on score differential and time remaining
                    const scoreDiff = homeScore - awayScore;
                    const timeRemaining = (period <= 3 ? 3600 : 3900) - gameTime;
                    
                    // Use simplified calculation that matches backend logic exactly
                    let prob;
                    if (scoreDiff === 0) {
                        prob = 0.5;
                    } else {
                        // Calculate total time remaining in seconds
                        const regulationTimeTotal = 3600; // 60 minutes
                        const totalTimeRemaining = Math.max(0, timeRemaining);
                        
                        // Use the same simple logic as backend's calculate_win_probability
                        // This ensures consistency with the backend calculation
                        if (homeScore > awayScore) {
                            // Home team is leading
                            const leadSize = homeScore - awayScore;
                            if (totalTimeRemaining < 300) {
                                // Less than 5 minutes remaining
                                prob = Math.min(0.95, 0.5 + (leadSize * 0.15));
                            } else if (totalTimeRemaining < 600) {
                                // Less than 10 minutes remaining
                                prob = Math.min(0.90, 0.5 + (leadSize * 0.12));
                            } else {
                                // More than 10 minutes remaining
                                prob = Math.min(0.85, 0.5 + (leadSize * 0.10));
                            }
                        } else {
                            // Away team is leading (home is trailing)
                            const leadSize = awayScore - homeScore;
                            if (totalTimeRemaining < 300) {
                                // Less than 5 minutes remaining
                                prob = Math.max(0.05, 0.5 - (leadSize * 0.15));
                            } else if (totalTimeRemaining < 600) {
                                // Less than 10 minutes remaining
                                prob = Math.max(0.10, 0.5 - (leadSize * 0.12));
                            } else {
                                // More than 10 minutes remaining
                                prob = Math.max(0.15, 0.5 - (leadSize * 0.10));
                            }
                        }
                        
                        // Clamp to reasonable bounds
                        prob = Math.max(0.05, Math.min(0.95, prob));
                    }
                    
                    generatedPoints.push({ ts: gameTime, p_home_win: prob });
                }
                
                // Merge with existing history data (prefer database data, but fill gaps with generated)
                if (generatedPoints.length > 0) {
                    // If we have database history, use it; otherwise use generated
                    if (historyData.length > 0) {
                        // Merge both datasets, preferring database data when timestamps are close
                        const merged = [...historyData];
                        for (const genPoint of generatedPoints) {
                            // Check if there's a database point close to this time
                            const closePoint = historyData.find(h => Math.abs(h.ts - genPoint.ts) < 30);
                            if (!closePoint) {
                                merged.push(genPoint);
                            }
                        }
                        historyData = merged.sort((a, b) => a.ts - b.ts);
                    } else {
                        // No database history, use generated points
                        historyData = generatedPoints;
                    }
                }
            }
        } catch (error) {
            console.error('Error generating probability from game events:', error);
        }
    }
    
    // Check if game is final
    let gameIsFinal = false;
    let finalData = null;
    try {
        const finalResponse = await fetch(`${API_BASE}/v1/games/${gameId}/final`);
        if (finalResponse.ok) {
            finalData = await finalResponse.json();
            gameIsFinal = finalData.is_final;
        }
    } catch (error) {
        console.error('Error checking final score:', error);
    }
    
    // Get overtime type from finalData if available (for accurate OT/SO display)
    const overtimeType = finalData?.overtime_type || null;
    
    // If game is final, show final score display
    if (gameIsFinal && finalData) {
        const finalHomeTeam = finalData.home_team;
        const finalAwayTeam = finalData.away_team;
        const finalHomeScore = finalData.home_score;
        const finalAwayScore = finalData.away_score;
        const winner = finalData.winner;
        
        // Determine winner and loser
        const homeIsWinner = winner === "HOME";
        const awayIsWinner = winner === "AWAY";
        const isTie = winner === "TIE";
        
        const finalHomeLogo = finalData.home_logo || '';
        const finalAwayLogo = finalData.away_logo || '';
        
        // Order: Top team = Away team, Bottom team = Home team
        // Away team row (always on top)
        const awayRow = awayIsWinner ? 
            `<div class="final-team-row winner">
                <div class="final-winner-indicator">▶</div>
                <img src="${finalAwayLogo}" alt="${finalAwayTeam}" class="final-team-logo" onerror="this.style.display='none'">
                <div class="final-team-name">${finalAwayTeam}</div>
                <div class="final-team-score">${finalAwayScore}</div>
            </div>` :
            `<div class="final-team-row loser">
                <img src="${finalAwayLogo}" alt="${finalAwayTeam}" class="final-team-logo" onerror="this.style.display='none'">
                <div class="final-team-name">${finalAwayTeam}</div>
                <div class="final-team-score">${finalAwayScore}</div>
            </div>`;
        
        // Home team row (always on bottom)
        const homeRow = homeIsWinner ?
            `<div class="final-team-row winner">
                <div class="final-winner-indicator">▶</div>
                <img src="${finalHomeLogo}" alt="${finalHomeTeam}" class="final-team-logo" onerror="this.style.display='none'">
                <div class="final-team-name">${finalHomeTeam}</div>
                <div class="final-team-score">${finalHomeScore}</div>
            </div>` :
            `<div class="final-team-row loser">
                <img src="${finalHomeLogo}" alt="${finalHomeTeam}" class="final-team-logo" onerror="this.style.display='none'">
                <div class="final-team-name">${finalHomeTeam}</div>
                <div class="final-team-score">${finalHomeScore}</div>
            </div>`;
        
        // Format final status text
        let finalStatusText = "▼ Final";
        if (finalData.overtime_type === "OT") {
            finalStatusText = "▼ Final/OT";
        } else if (finalData.overtime_type === "SO") {
            finalStatusText = "▼ Final/SO";
        }
        
        gameDetails.innerHTML = `
            <div class="scoreboard-winprob-container">
                <div class="final-score-container">
                    <div class="final-score-header">
                        <button class="back-button" onclick="showGamesList()">← Back to Games</button>
                        <span class="final-status">${finalStatusText}</span>
                    </div>
                    <div class="final-score-teams">
                        ${awayRow}
                        ${homeRow}
                    </div>
                </div>
                <div class="win-prob">
                    <div class="win-prob-title">Win Probability</div>
                    ${generateWinProbGraph(historyData, homeTeam, awayTeam, homeProb, awayProb, false, finalHomeLogo, finalAwayLogo, finalData.home_abbrev || '', finalData.away_abbrev || '')}
                </div>
            </div>

        <div class="game-tabs">
            <div class="tab active" onclick="switchTab('feed', '${gameId}')" id="feed-tab">Feed</div>
            <div class="tab" onclick="switchTab('game', '${gameId}')" id="game-tab">Game</div>
            <div class="tab" onclick="switchTab('away-team', '${gameId}')" id="away-team-tab">${finalData.away_abbrev || awayTeam.substring(0, 3).toUpperCase()}</div>
            <div class="tab" onclick="switchTab('home-team', '${gameId}')" id="home-team-tab">${finalData.home_abbrev || homeTeam.substring(0, 3).toUpperCase()}</div>
        </div>
        <div id="powerplay-display" style="display: none;"></div>
        <div id="feed-content" class="tab-content active">
            <div id="playbyplay-feed" class="playbyplay-feed">
                <div class="spinner"></div>
            </div>
        </div>
        <div id="game-content" class="tab-content">
            <div id="game-stats-container">
                <div class="spinner"></div>
            </div>
        </div>
        <div id="away-team-content" class="tab-content">
            <div id="away-team-stats-container">
                <div class="spinner"></div>
            </div>
        </div>
        <div id="home-team-content" class="tab-content">
            <div id="home-team-stats-container">
                <div class="spinner"></div>
            </div>
        </div>
        `;
        
        // Stop any existing polling (for final games)
        stopPlayByPlayPolling();
        currentGameId = gameId;
        currentGameIsLive = false;
        currentHomeTeam = homeTeam;
        currentAwayTeam = awayTeam;
        currentHomeLogo = finalHomeLogo;
        currentAwayLogo = finalAwayLogo;
        loadPlayByPlay(gameId, homeTeam, awayTeam, finalHomeLogo, finalAwayLogo, false);
        gameDetails.style.display = 'block';
        gameDetails.classList.add('show');
        gameDetails.scrollIntoView({ behavior: 'smooth' });
        return;
    }
    
    const homeLogo = score.home.logo || '';
    const awayLogo = score.away.logo || '';
    const gameIsLive = game.is_live || false;
    const gameState = game.game_state || '';
    const period = game.period || 1;
    const timeInPeriod = game.time_in_period || '00:00';
    const gameOvertimeType = game.overtime_type || data.overtime_type || null;
    
    // Format time and period for live games, or final status for finished games
    let timeDisplay = '';
    let periodDisplay = '';
    let statusDisplay = '';
    
    if (isFinal) {
        // For finished games, show "Final", "Final/OT", or "Final/SO"
        if (gameOvertimeType === 'OT') {
            statusDisplay = 'Final/OT';
        } else if (gameOvertimeType === 'SO') {
            statusDisplay = 'Final/SO';
        } else {
            statusDisplay = 'Final';
        }
        // For final games, hide time and period, show final status instead
        timeDisplay = '';
        periodDisplay = '';
    } else {
        // Convert time elapsed to time remaining
        // timeInPeriod is elapsed time in MM:SS format (e.g., "00:30" = 30 seconds elapsed)
        // We need to convert to time remaining
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
        
        // Format period: 1st, 2nd, 3rd, OT, SO
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
    }
    
    gameDetails.innerHTML = `
        <div class="back-button-container">
            <button class="back-button" onclick="showGamesList()">← Back to Games</button>
        </div>
        <div class="scoreboard-winprob-container">
            <div class="live-score-container">
                <div class="live-score-teams">
                    <div class="live-team-row">
                        <img src="${awayLogo}" alt="${awayTeam}" class="live-team-logo" onerror="this.style.display='none'">
                        <div class="live-team-info">
                            <div class="live-team-score">${awayScore}</div>
                            <div class="live-team-name">${awayTeam}</div>
                        </div>
                    </div>
                    <div class="live-team-row">
                        <img src="${homeLogo}" alt="${homeTeam}" class="live-team-logo" onerror="this.style.display='none'">
                        <div class="live-team-info">
                            <div class="live-team-score">${homeScore}</div>
                            <div class="live-team-name">${homeTeam}</div>
                        </div>
                    </div>
                </div>
                <div class="live-status-info">
                    ${gameIsLive ? '<div class="live-indicator-red"></div>' : ''}
                    ${gameIsFinal ? 
                        `<div class="live-time-remaining" style="font-size: 1.1em; font-weight: 500;">${statusDisplay}</div>
                         <div class="live-period" style="display: none;"></div>` :
                        `<div class="live-time-remaining">${timeDisplay}</div>
                         <div class="live-period">${periodDisplay}</div>`
                    }
                </div>
            </div>
            <div class="win-prob">
                <div class="win-prob-title">Win Probability</div>
                ${generateWinProbGraph(historyData, homeTeam, awayTeam, homeProb, awayProb, gameIsLive, homeLogo, awayLogo, score.home.abbrev || '', score.away.abbrev || '')}
            </div>
        </div>

        <div class="game-tabs">
            <div class="tab active" onclick="switchTab('feed', '${gameId}')" id="feed-tab">Feed</div>
            <div class="tab" onclick="switchTab('game', '${gameId}')" id="game-tab">Game</div>
            <div class="tab" onclick="switchTab('away-team', '${gameId}')" id="away-team-tab">${score.away.abbrev || awayTeam.substring(0, 3).toUpperCase()}</div>
            <div class="tab" onclick="switchTab('home-team', '${gameId}')" id="home-team-tab">${score.home.abbrev || homeTeam.substring(0, 3).toUpperCase()}</div>
        </div>
        <div id="feed-content" class="tab-content active">
            <div id="playbyplay-feed" class="playbyplay-feed">
                <div class="spinner"></div>
            </div>
        </div>
        <div id="game-content" class="tab-content">
            <div id="game-stats-container">
                <div class="spinner"></div>
            </div>
        </div>
        <div id="away-team-content" class="tab-content">
            <div id="away-team-stats-container">
                <div class="spinner"></div>
            </div>
        </div>
        <div id="home-team-content" class="tab-content">
            <div id="home-team-stats-container">
                <div class="spinner"></div>
            </div>
        </div>
    `;
    
    // Stop any existing polling before starting new one
    stopPlayByPlayPolling();
    stopLiveScorePolling();
    currentGameId = gameId;
    currentGameIsLive = gameIsLive;
    currentHomeTeam = homeTeam;
    currentAwayTeam = awayTeam;
    currentHomeLogo = homeLogo;
    currentAwayLogo = awayLogo;
    
    // Start live score polling if game is live (always keep scoreboard and times updated)
    if (gameIsLive) {
        startLiveScorePolling(gameId);
    }
    
    // Always load play-by-play (will fetch fresh data immediately)
    loadPlayByPlay(gameId, homeTeam, awayTeam, homeLogo, awayLogo, gameIsLive);
    gameDetails.style.display = 'block';
    gameDetails.classList.add('show');
    gameDetails.scrollIntoView({ behavior: 'smooth' });
}


function generateWinProbGraph(historyData, homeTeam, awayTeam, homeProb, awayProb, isLive, homeLogo = '', awayLogo = '', homeAbbrev = '', awayAbbrev = '') {
    // Determine graph dimensions
    const width = 400;
    const height = 120;
    const padding = { top: 20, right: 20, bottom: 30, left: 40 };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;
    
    let points = [];
    let minTime, maxTime, timeRange;
    
    // Validate and convert input probabilities to numbers with defaults
    const homeProbNum = Number(homeProb);
    const awayProbNum = Number(awayProb);
    const safeHomeProb = Number.isFinite(homeProbNum) ? homeProbNum : 50.0;
    const safeAwayProb = Number.isFinite(awayProbNum) ? awayProbNum : 50.0;
    
    // If no historical data, create a single point at current probability
    if (!historyData || historyData.length === 0) {
        // Create a simple horizontal line at current probability
        // Guard against missing/invalid data
        const currentProb = Number(safeHomeProb) / 100;
        if (Number.isFinite(currentProb)) {
        const x1 = padding.left;
        const x2 = width - padding.right;
        const y = padding.top + chartHeight - (currentProb * chartHeight);
            
            // Only add points if coordinates are finite
            if (Number.isFinite(x1) && Number.isFinite(x2) && Number.isFinite(y)) {
        points = [
            { x: x1, y: y },
            { x: x2, y: y }
        ];
            }
        }
        minTime = 0;
        maxTime = 3600; // Assume 60 minutes (3 periods * 20 minutes) for a full game
        timeRange = maxTime - minTime;
    } else {
        // Filter historyData to skip invalid entries
        // Skip entries where ts is not a number or p_home_win is NaN/undefined
        const validHistoryData = historyData.filter(d => {
            const ts = Number(d.ts);
            const p_home_win = Number(d.p_home_win);
            return typeof d.ts === 'number' && Number.isFinite(ts) && 
                   typeof d.p_home_win === 'number' && Number.isFinite(p_home_win) &&
                   !Number.isNaN(p_home_win);
        });
        
        if (validHistoryData.length === 0) {
            // No valid historical data, fall back to current probability
            const currentProb = Number(safeHomeProb) / 100;
            if (Number.isFinite(currentProb)) {
                const x1 = padding.left;
                const x2 = width - padding.right;
                const y = padding.top + chartHeight - (currentProb * chartHeight);
                
                if (Number.isFinite(x1) && Number.isFinite(x2) && Number.isFinite(y)) {
                    points = [
                        { x: x1, y: y },
                        { x: x2, y: y }
                    ];
                }
            }
            minTime = 0;
            maxTime = 3600;
        timeRange = maxTime - minTime;
    } else {
        // Use relative game time (seconds elapsed from game start)
        // The data should already be in relative time from the backend
            const times = validHistoryData.map(d => Number(d.ts)).filter(t => Number.isFinite(t));
        if (times.length === 0) {
            minTime = 0;
            maxTime = 3600;
        } else {
        minTime = Math.min(...times);
        maxTime = Math.max(...times);
            }
        
        // Ensure we start from 0 (game start)
        minTime = Math.min(0, minTime);
        
        // For a typical NHL game: 3 periods * 20 minutes = 3600 seconds
        // If maxTime is significantly less, it might be a game in progress
        // If maxTime is greater, it might include overtime
        // Set a reasonable max for display (e.g., up to 3900 seconds for OT games)
        const typicalGameTime = 3600; // 3 periods * 20 minutes
        const maxDisplayTime = Math.max(typicalGameTime, maxTime + 300); // Add buffer
        
        timeRange = maxDisplayTime - minTime || 1;
        
        // Interpolate between points to show smoother changes
        // Add intermediate points every 30 seconds between major events
        const interpolatedData = [];
            for (let i = 0; i < validHistoryData.length; i++) {
                const current = validHistoryData[i];
                const currentTs = Number(current.ts);
                const currentProb = Number(current.p_home_win);
                
                // Validate before adding to interpolated data
                if (Number.isFinite(currentTs) && Number.isFinite(currentProb)) {
                    interpolatedData.push({ ts: currentTs, p_home_win: currentProb });
                }
                
                // Add intermediate points between this and next point
                if (i < validHistoryData.length - 1) {
                    const next = validHistoryData[i + 1];
                    const nextTs = Number(next.ts);
                    const nextProb = Number(next.p_home_win);
                    
                    // Only interpolate if both points are valid
                    if (Number.isFinite(nextTs) && Number.isFinite(nextProb)) {
                        const timeDiff = nextTs - currentTs;
                        const probDiff = nextProb - currentProb;
                        
                        // Add points every 30 seconds if gap is large enough
                        if (timeDiff > 60 && Number.isFinite(timeDiff)) {
                            const numPoints = Math.floor(timeDiff / 30);
                            for (let j = 1; j <= numPoints; j++) {
                                const t = currentTs + (timeDiff * j / (numPoints + 1));
                                const p = currentProb + (probDiff * j / (numPoints + 1));
                                
                                // Only add if interpolated values are finite
                                if (Number.isFinite(t) && Number.isFinite(p)) {
                                    interpolatedData.push({ ts: t, p_home_win: p });
                                }
                            }
                        }
                    }
            }
        }
        
        // Sort by time to ensure correct order
            interpolatedData.sort((a, b) => Number(a.ts) - Number(b.ts));
        
        // Map data points to SVG coordinates
        // X-axis: 0 seconds (game start) = left, maxTime = right
            // Only push points if both x and y are finite numbers
            points = [];
            for (const d of interpolatedData) {
                const ts = Number(d.ts);
                const p_home_win = Number(d.p_home_win);
                
                if (Number.isFinite(ts) && Number.isFinite(p_home_win)) {
                    const x = padding.left + (ts - minTime) / timeRange * chartWidth;
                    const y = padding.top + chartHeight - (p_home_win * chartHeight);
                    
                    // Only push if both coordinates are finite
                    if (Number.isFinite(x) && Number.isFinite(y)) {
                        points.push({ x, y });
                    }
                }
            }
        
        // Add current point if it's not already in the data
        // Check if the last point is close to the current probability
            const lastDataPoint = interpolatedData.length > 0 ? interpolatedData[interpolatedData.length - 1] : null;
            const currentProb = Number(safeHomeProb) / 100;
            
            // Only add current point if probability is valid
            if (Number.isFinite(currentProb)) {
        const shouldAddCurrentPoint = !lastDataPoint || 
                    Math.abs(Number(lastDataPoint.p_home_win) - currentProb) > 0.01 || 
                    Math.abs(Number(lastDataPoint.ts) - maxTime) > 30;
        
                if (shouldAddCurrentPoint && Number.isFinite(maxTime) && Number.isFinite(minTime) && Number.isFinite(timeRange) && timeRange > 0) {
            // Use maxTime for current point if available, otherwise use the calculated max
            const currentX = padding.left + (maxTime - minTime) / timeRange * chartWidth;
            const currentY = padding.top + chartHeight - (currentProb * chartHeight);
                    
                    // Only push if both coordinates are finite
                    if (Number.isFinite(currentX) && Number.isFinite(currentY)) {
            points.push({ x: currentX, y: currentY });
        }
                }
            }
        }
    }
    
    // Build SVG path
    let path = '';
    if (points.length > 0) {
        path = `M ${points[0].x} ${points[0].y}`;
        for (let i = 1; i < points.length; i++) {
            path += ` L ${points[i].x} ${points[i].y}`;
        }
    }
    
    // Create area above line for away team probability (inverse of home team)
    // The area should fill from the line up to the top
    let areaPath = '';
    if (points.length > 0) {
        areaPath = `M ${points[0].x} ${padding.top}`;
        for (let i = 0; i < points.length; i++) {
            areaPath += ` L ${points[i].x} ${points[i].y}`;
        }
        areaPath += ` L ${points[points.length - 1].x} ${padding.top} Z`;
    }
    
    // Determine period markers based on relative game time
    // NHL: 20 minutes (1200 seconds) per period
    const periods = [];
    const periodLength = 1200; // 20 minutes in seconds
    const periodsInGame = Math.ceil(timeRange / periodLength);
    
    // Start from 0 (origin) for 1st period, then each subsequent period
    for (let i = 0; i <= periodsInGame && i <= 4; i++) {
        const periodTime = i * periodLength;
        // Only show markers if they're within the displayed time range and values are finite
        if (periodTime <= timeRange && Number.isFinite(timeRange) && timeRange > 0 && Number.isFinite(minTime)) {
            const x = padding.left + (periodTime - minTime) / timeRange * chartWidth;
            // Only add period marker if x coordinate is finite
            if (Number.isFinite(x)) {
            let label = '';
            if (i === 0) label = '1st';
            else if (i === 1) label = '2nd';
            else if (i === 2) label = '3rd';
            else if (i === 3) label = 'OT';
            else if (i === 4) label = 'SO';
            periods.push({ x, label });
            }
        }
    }
    
    // If no periods calculated, use default markers
    if (periods.length === 0 && timeRange > 0) {
        periods.push({ x: padding.left, label: '1st' });
        periods.push({ x: padding.left + chartWidth / 3, label: '2nd' });
        periods.push({ x: padding.left + chartWidth * 2 / 3, label: '3rd' });
    }
    
    // Use provided abbreviations, or fall back to first 3 letters if not provided
    const homeAbbrevDisplay = homeAbbrev || homeTeam.substring(0, 3).toUpperCase();
    const awayAbbrevDisplay = awayAbbrev || awayTeam.substring(0, 3).toUpperCase();
    
    // Get team colors - use display abbreviations if provided abbreviations are empty
    const homeColor = TEAM_COLORS[homeAbbrev || homeAbbrevDisplay] || "#000000";
    const awayColor = TEAM_COLORS[awayAbbrev || awayAbbrevDisplay] || "#666666";
    
    // Determine which team is leading based on current probability
    // Use the leading team's color for the line
    // Use safe probabilities that are guaranteed to be numbers
    const leadingTeamColor = safeHomeProb > safeAwayProb ? homeColor : (safeAwayProb > safeHomeProb ? awayColor : homeColor);
    
    // Create area BELOW line for home team (fills from bottom to line)
    let homeAreaPath = '';
    // Create area ABOVE line for away team (fills from top to line)
    let awayAreaPath = '';
    
    if (points.length > 0) {
        // Home team area: from bottom-left, along line, to bottom-right
        homeAreaPath = `M ${points[0].x} ${height - padding.bottom}`;
        for (let i = 0; i < points.length; i++) {
            homeAreaPath += ` L ${points[i].x} ${points[i].y}`;
        }
        homeAreaPath += ` L ${points[points.length - 1].x} ${height - padding.bottom} Z`;
        
        // Away team area: from top-left, along line, to top-right
        awayAreaPath = `M ${points[0].x} ${padding.top}`;
        for (let i = 0; i < points.length; i++) {
            awayAreaPath += ` L ${points[i].x} ${points[i].y}`;
        }
        awayAreaPath += ` L ${points[points.length - 1].x} ${padding.top} Z`;
    }
    
    // Get the last point for the circle - validate it has finite coordinates
    const lastPoint = points.length > 0 ? points[points.length - 1] : null;
    const validLastPoint = lastPoint && 
                          Number.isFinite(Number(lastPoint.x)) && 
                          Number.isFinite(Number(lastPoint.y)) ? 
                          { x: Number(lastPoint.x), y: Number(lastPoint.y) } : null;
    
    // Validate period markers have finite x coordinates
    const validPeriods = periods.filter(p => Number.isFinite(Number(p.x))).map(p => ({
        x: Number(p.x),
        label: p.label
    }));
    
    return `
        <div class="win-prob-graph-container">
            <div class="win-prob-graph-labels">
                <div class="win-prob-graph-team-left">
                    ${awayLogo ? `<img src="${awayLogo}" alt="${awayTeam}" class="win-prob-graph-logo" onerror="this.style.display='none'">` : ''}
                    <span class="win-prob-graph-percentage">${safeAwayProb.toFixed(1)}%</span>
                    <span class="win-prob-graph-abbrev">-- ${awayAbbrevDisplay}</span>
                </div>
                <div class="win-prob-graph-team-right">
                    <span class="win-prob-graph-abbrev">${homeAbbrevDisplay} --</span>
                    <span class="win-prob-graph-percentage">${safeHomeProb.toFixed(1)}%</span>
                    ${homeLogo ? `<img src="${homeLogo}" alt="${homeTeam}" class="win-prob-graph-logo" onerror="this.style.display='none'">` : ''}
                </div>
            </div>
            <svg class="win-prob-graph" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
                <!-- Y-axis labels -->
                <text x="${padding.left - 10}" y="${padding.top + 5}" text-anchor="end" font-size="10" fill="#888">100</text>
                <text x="${padding.left - 10}" y="${padding.top + chartHeight / 2 + 5}" text-anchor="end" font-size="10" fill="#888">50</text>
                <text x="${padding.left - 10}" y="${height - padding.bottom + 5}" text-anchor="end" font-size="10" fill="#888">0</text>
                
                <!-- Grid lines -->
                <line x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${height - padding.bottom}" stroke="#333" stroke-width="1"/>
                <line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" stroke="#333" stroke-width="1"/>
                <line x1="${padding.left}" y1="${padding.top + chartHeight / 2}" x2="${width - padding.right}" y2="${padding.top + chartHeight / 2}" stroke="#333" stroke-width="1" stroke-dasharray="2,2"/>
                
                <!-- Away team area (above line) - neutral gray -->
                ${awayAreaPath ? `<path d="${awayAreaPath}" fill="#444" opacity="0.25"/>` : ''}
                
                <!-- Home team area (below line) - neutral gray -->
                ${homeAreaPath ? `<path d="${homeAreaPath}" fill="#444" opacity="0.4"/>` : ''}
                
                <!-- Home team probability line - leading team's color (the "thick part") -->
                ${path ? `<path d="${path}" fill="none" stroke="${leadingTeamColor}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>` : ''}
                
                <!-- Large circle at the end - leading team's color -->
                ${validLastPoint ? `<circle cx="${validLastPoint.x}" cy="${validLastPoint.y}" r="6" fill="${leadingTeamColor}" stroke="${leadingTeamColor}" stroke-width="2"/>` : ''}
                
                <!-- Period markers -->
                ${validPeriods.map(p => `
                    <line x1="${p.x}" y1="${padding.top}" x2="${p.x}" y2="${height - padding.bottom}" stroke="#333" stroke-width="0.5" stroke-dasharray="2,2"/>
                    <text x="${p.x}" y="${height - 10}" text-anchor="start" font-size="10" fill="#888">${p.label}</text>
                `).join('')}
            </svg>
        </div>
    `;
}


function renderFeedEvents(events, homeTeam, awayTeam, homeLogo, awayLogo, isLive, gameId, gameStateFromAPI = null) {
    const feed = document.getElementById('playbyplay-feed');
    if (!feed) {
        console.error('[Feed] Feed element not found');
        return;
    }
    
    // Load power play status
    loadPowerPlayStatus(gameId);
    
    // For LIVE games only: Detect stoppage events and trigger model refresh
    if (isLive && currentGameId === gameId) {
        // Check for new stoppage events (type code 516 or event_type STOPPAGE)
        const stoppageEvents = events.filter(e => 
            e.type_code === 516 || 
            e.event_type === 'STOPPAGE' ||
            (e.description && e.description.toLowerCase().includes('stoppage'))
        );
        
        for (const stoppage of stoppageEvents) {
            const stoppageId = `${gameId}-${stoppage.id || stoppage.timestamp}`;
            if (!processedStoppages.has(stoppageId)) {
                processedStoppages.add(stoppageId);
                // Trigger model refresh by re-running ingestion
                // This will process new events and generate updated predictions
                triggerModelRefresh(gameId).catch(() => {
                    // Silently fail
                });
            }
        }
    }
    
    if (!events || events.length === 0) {
        console.log(`[Feed] No events to render for ${gameId}`);
        const message = isLive 
            ? '<div style="color: #aaaaaa; text-align: center; padding: 40px;">No events yet. Play-by-play will appear here once the game starts.</div>'
            : '<div style="color: #aaaaaa; text-align: center; padding: 40px;">No events yet. Start ingestion to see play-by-play.</div>';
        feed.innerHTML = message;
        renderedEventIds.clear();
        lastRenderedEventCount = 0;
        return;
    }

    const mostRecentTime = events[0]?.timestamp || Date.now() / 1000;
    const maxPeriod = Math.max(...events.map(e => e.period || 1));
    // Use game state from API if provided, otherwise infer from isLive
    const gameState = gameStateFromAPI || (isLive ? 'LIVE' : 'OFF');
    const isFinal = gameState === 'OFF' || gameState === 'FINAL';
    
    // Filter events: keep crucial events (GOAL, PENALTY, PERIOD_END) ALWAYS
    const crucialEventTypes = ['GOAL', 'PENALTY', 'PERIOD_END'];
    
    // Deduplicate events by ID (backend should already deduplicate, but do it here too for safety)
    const seenIds = new Set();
    const uniqueEvents = [];
    for (const event of events) {
        const eventId = event.id;
        if (eventId && !seenIds.has(eventId)) {
            seenIds.add(eventId);
            uniqueEvents.push(event);
        } else if (!eventId) {
            // If no ID, create one for deduplication
            // Validate all properties exist before creating dedupKey
            const timestamp = event.timestamp != null ? event.timestamp : '';
            const eventType = event.event_type != null ? event.event_type : '';
            const playerId = event.player_id != null ? event.player_id : '';
            const period = event.period != null ? event.period : '';
            const timeInPeriod = event.time_in_period != null ? event.time_in_period : '';
            const dedupKey = `${timestamp}-${eventType}-${playerId}-${period}-${timeInPeriod}`;
            if (!seenIds.has(dedupKey)) {
                seenIds.add(dedupKey);
                event.id = `${gameId}-${uniqueEvents.length}`;
                uniqueEvents.push(event);
            }
        }
    }
    
    // Backend already sorts and filters events correctly, so we should trust what it sends
    // For completed games, backend sends only crucial events
    // For live games, backend sends all crucial + 4 most recent non-crucial
    // Backend already sorts by timestamp descending, so we just use the events as-is
    // Only sort if we need to (shouldn't be necessary, but ensure order is correct)
    let filteredEvents = uniqueEvents;
    // Double-check sorting by timestamp (most recent first) with event ID as tiebreaker
    filteredEvents.sort((a, b) => {
        const tsA = a.timestamp || 0;
        const tsB = b.timestamp || 0;
        if (tsB !== tsA) {
            return tsB - tsA; // Descending order (most recent first)
        }
        // If timestamps are equal, use ID for stable sort
        const idA = a.id || '';
        const idB = b.id || '';
        return idB.localeCompare(idA);
    });

    if (filteredEvents.length === 0) {
        console.warn(`[Feed] No filtered events to display for ${gameId}`);
        const message = isLive 
            ? '<div style="color: #aaaaaa; text-align: center; padding: 40px;">No events yet. Play-by-play will appear here once the game starts.</div>'
            : '<div style="color: #aaaaaa; text-align: center; padding: 40px;">No events yet. Start ingestion to see play-by-play.</div>';
        feed.innerHTML = message;
        renderedEventIds.clear();
        lastRenderedEventCount = 0;
        return;
    }
    
    // Check if we need to update: if event count changed or if this is a different game
    const currentEventIds = new Set(filteredEvents.map(e => e.id).filter(Boolean));
    const eventCountChanged = filteredEvents.length !== lastRenderedEventCount;
    const hasNewEvents = [...currentEventIds].some(id => !renderedEventIds.has(id));
    
    // Only re-render if:
    // 1. Event count changed (new events added or removed)
    // 2. We have new event IDs that aren't already rendered
    // 3. This is the first render (renderedEventIds is empty)
    const shouldRerender = renderedEventIds.size === 0 || eventCountChanged || hasNewEvents;
    
    if (!shouldRerender) {
        // No changes needed, skip re-render to preserve DOM and scroll position
        return;
    }
    
    // Preserve scroll position if user has scrolled down
    const wasScrolledDown = feed.scrollTop > 100;
    const previousScrollTop = feed.scrollTop;
    
    feed.innerHTML = filteredEvents.map((event, index) => {
        const timeAgo = Math.round((mostRecentTime - event.timestamp) / 60);
        const timeStr = timeAgo === 0 ? 'Just now' : `${timeAgo}m ago`;
        const playerInitials = event.player ? event.player.split(' ').map(n => n[0]).join('').substring(0, 2) : '?';
        
        // Check if this is a period-end or period-start event
        const isPeriodEvent = event.event_type === 'PERIOD_END' || event.event_type === 'PERIOD_START';
        const isPeriodEnd = event.event_type === 'PERIOD_END';
        
        // Format period and time remaining
        const period = event.period || 1;
        const timeInPeriod = event.time_in_period || '00:00';
        
        // Format period number (1st, 2nd, 3rd, OT, etc.)
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
        
        // For period-end events, show "0:00" time
        let timeRemaining;
        if (isPeriodEnd) {
            timeRemaining = '0:00';
        } else if (timeInPeriod && timeInPeriod !== '00:00') {
            const [elapsedMinutes, elapsedSeconds] = timeInPeriod.split(':').map(Number);
            const elapsedTotalSeconds = elapsedMinutes * 60 + elapsedSeconds;
            
            // Determine period length: 20 minutes (1200 seconds) for regulation, 5 minutes (300 seconds) for OT
            const periodLengthSeconds = (period <= 3) ? 1200 : 300;
            const remainingTotalSeconds = Math.max(0, periodLengthSeconds - elapsedTotalSeconds);
            
            const remainingMinutes = Math.floor(remainingTotalSeconds / 60);
            const remainingSecs = remainingTotalSeconds % 60;
            timeRemaining = `${remainingMinutes}:${remainingSecs.toString().padStart(2, '0')}`;
        } else {
            // If time is 00:00, show full period time remaining
            timeRemaining = (period <= 3) ? '20:00' : '5:00';
        }
        
        // Format: "1st 19:50" or "OT 4:30" or just period label for period events
        const periodTime = isPeriodEvent ? periodLabel : `${periodLabel} ${timeRemaining}`;
        
        // For period-end events, use special styling
        if (isPeriodEnd) {
            return `
                <div class="playbyplay-event period-end-event" style="border-left: 3px solid #666; background: rgba(100, 100, 100, 0.1); margin: 10px 0; padding: 12px; border-radius: 4px;">
                    <div class="event-content" style="text-align: center;">
                        <div class="event-description" style="font-weight: 600; color: #888; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px;">
                            ${event.description || 'End of Period'}
                        </div>
                        <div style="font-size: 12px; color: #aaa; margin-top: 4px;">
                            ${periodLabel} Period • Score: ${event.home_score || 0} - ${event.away_score || 0}
                        </div>
                    </div>
                </div>
            `;
        }
        
        // For period-start events, use subtle styling
        if (event.event_type === 'PERIOD_START') {
            return `
                <div class="playbyplay-event period-start-event" style="border-left: 2px solid #4a9eff; background: rgba(74, 158, 255, 0.05); margin: 8px 0; padding: 10px; border-radius: 4px;">
                    <div class="event-content" style="text-align: center;">
                        <div class="event-description" style="font-weight: 500; color: #4a9eff; font-size: 13px;">
                            ${event.description || 'Start of Period'}
                        </div>
                    </div>
                </div>
            `;
        }
        
        // Regular event rendering (goals, penalties, etc.)
        const avatarContent = event.player_headshot 
            ? `<img src="${event.player_headshot}" alt="${event.player || 'Player'}" class="event-player-headshot" onerror="this.parentElement.textContent='${playerInitials}'">`
            : playerInitials;
        
        const isGoal = event.event_type === 'GOAL';
        const scoringTeam = event.team;
        const homeScoreBold = (isGoal && scoringTeam === 'HOME') ? 'font-weight: bold;' : '';
        const awayScoreBold = (isGoal && scoringTeam === 'AWAY') ? 'font-weight: bold;' : '';
        
        const homeLogoHtml = homeLogo ? `<img src="${homeLogo}" alt="${homeTeam}" class="event-score-logo" onerror="this.style.display='none'">` : '';
        const awayLogoHtml = awayLogo ? `<img src="${awayLogo}" alt="${awayTeam}" class="event-score-logo" onerror="this.style.display='none'">` : '';
        
        const scoreDisplay = `
            <span class="event-score-container">
                ${homeLogoHtml}
                <span style="${homeScoreBold}">${event.home_score}</span>
                <span class="event-score-dash">-</span>
                <span style="${awayScoreBold}">${event.away_score}</span>
                ${awayLogoHtml}
            </span>
        `;
        
        // Goal description is already formatted with strength labels from backend
        let goalDescription = event.description || event.event_type || 'Event';
        
        return `
            <div class="playbyplay-event ${isGoal ? 'goal-event' : ''}">
                <div class="event-player-avatar">${avatarContent}</div>
                <div class="event-content">
                    <div class="event-header">
                        <span>${scoreDisplay}</span>
                        <span>${periodTime}</span>
                    </div>
                    <div class="event-description">
                        ${goalDescription}
                    </div>
                    ${event.player ? `<div class="event-player">${event.player}</div>` : (event.player_id ? `<div class="event-player">Player ${event.player_id}</div>` : '')}
                </div>
            </div>
        `;
    }).join('');
    
    // Update tracking variables
    renderedEventIds = new Set(filteredEvents.map(e => e.id).filter(Boolean));
    lastRenderedEventCount = filteredEvents.length;
    lastEventCount = filteredEvents.length;
    lastGoalCount = filteredEvents.filter(e => e.event_type === 'GOAL').length;
    
    // Preserve scroll position if user was scrolled down, otherwise scroll to top
    if (wasScrolledDown && previousScrollTop > 0) {
        // User was viewing older events, try to restore scroll position
        // Use requestAnimationFrame to ensure DOM is updated
        requestAnimationFrame(() => {
            feed.scrollTop = previousScrollTop;
        });
    } else {
        // User was at the top, scroll to top to show latest events
        feed.scrollTop = 0;
    }
    
    // Set up event-driven power play checking (no constant polling)
    if (isLive) {
        // Count current penalties
        const currentPenaltyCount = filteredEvents.filter(e => e.event_type === 'PENALTY').length;
        
        // Only check power play status if:
        // 1. This is the first render (lastPenaltyCount is 0)
        // 2. A new penalty was detected (penalty count increased)
        // 3. Penalty count changed (penalty expired or new one started)
        if (lastPenaltyCount === 0 || currentPenaltyCount !== lastPenaltyCount) {
            // Check power play status when a penalty is detected or count changes
            loadPowerPlayStatus(gameId);
            lastPenaltyCount = currentPenaltyCount;
        }
        
        // No constant polling - only check when penalties change
    } else {
        stopPlayByPlayPolling();
        stopPowerPlayPolling();
        lastEventCount = 0;
        lastGoalCount = 0;
        lastPenaltyCount = 0;
    }
}


function showGameDetails() {
    // Hide games list
    const mainContainer = document.querySelector('.main-container');
    if (mainContainer) {
        mainContainer.style.display = 'none';
    }
    
    // Show game details
    const gameDetails = document.getElementById('gameDetails');
    if (gameDetails) {
        // Always add a back button when showing game details (even during loading/errors)
        if (!gameDetails.innerHTML.includes('back-button')) {
            gameDetails.innerHTML = `
                <div class="back-button-container">
                    <button class="back-button" onclick="showGamesList()">← Back to Games</button>
                </div>
                <div id="game-content-placeholder"></div>
            `;
        }
        gameDetails.style.display = 'block';
    }
}


function showGamesList() {
    // Stop polling for the current game when navigating away
    stopPollingForCurrentGame();
    stopPlayByPlayPolling();
    stopLiveScorePolling();
    stopPowerPlayPolling();
    currentGameId = null;
    currentGameIsLive = false;
    // Reset feed tracking when navigating away
    renderedEventIds.clear();
    lastRenderedEventCount = 0;
    lastPenaltyCount = 0;
    
    // Show games list
    const mainContainer = document.querySelector('.main-container');
    if (mainContainer) {
        mainContainer.style.display = 'block';
    }
    
    // Hide and clean up game details to prevent memory leaks
    const gameDetails = document.getElementById('gameDetails');
    if (gameDetails) {
        gameDetails.style.display = 'none';
        gameDetails.classList.remove('show');
        // Clear innerHTML to free up memory from large DOM structures
        // Use a timeout to avoid visual artifacts during transition
        setTimeout(() => {
            if (gameDetails.style.display === 'none') {
                gameDetails.innerHTML = '';
            }
        }, 500);
    }
    
    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
}


function showBasicGameInfo(gameId, basicInfo) {
    const homeTeam = basicInfo.home_team_name || 'Home';
    const awayTeam = basicInfo.away_team_name || 'Away';
    const homeLogo = basicInfo.home_team_logo || '';
    const awayLogo = basicInfo.away_team_logo || '';
    const homeScore = basicInfo.home_score || 0;
    const awayScore = basicInfo.away_score || 0;
    const isLive = basicInfo.is_live || false;
    const gameState = basicInfo.game_state || '';
    const isFinal = gameState === 'OFF' || gameState === 'FINAL';
    const period = basicInfo.period || 1;
    const timeInPeriod = basicInfo.time_in_period || '00:00';
    const overtimeType = basicInfo.overtime_type || null;
    
    // Format time and period for live games, or final status for finished games
    let timeDisplay = '';
    let periodDisplay = '';
    let statusDisplay = '';
    
    if (isFinal) {
        // For finished games, show "Final", "Final/OT", or "Final/SO"
        if (overtimeType === 'OT') {
            statusDisplay = 'Final/OT';
        } else if (overtimeType === 'SO') {
            statusDisplay = 'Final/SO';
        } else {
            statusDisplay = 'Final';
        }
        // For final games, hide time and period, show final status instead
        timeDisplay = '';
        periodDisplay = '';
    } else {
        // Convert time elapsed to time remaining
        // timeInPeriod is elapsed time in MM:SS format (e.g., "00:30" = 30 seconds elapsed)
        // We need to convert to time remaining
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
    }
    
    const gameDetails = document.getElementById('gameDetails');
    const placeholder = document.getElementById('game-content-placeholder');
    
    // Show basic scoreboard immediately
    gameDetails.innerHTML = `
        <div class="back-button-container">
            <button class="back-button" onclick="showGamesList()">← Back to Games</button>
        </div>
        <div class="scoreboard-winprob-container">
            <div class="live-score-container">
                <div class="live-score-teams">
                    <div class="live-team-row">
                        <img src="${awayLogo}" alt="${awayTeam}" class="live-team-logo" onerror="this.style.display='none'">
                        <div class="live-team-info">
                            <div class="live-team-score">${awayScore}</div>
                            <div class="live-team-name">${awayTeam}</div>
                        </div>
                    </div>
                    <div class="live-team-row">
                        <img src="${homeLogo}" alt="${homeTeam}" class="live-team-logo" onerror="this.style.display='none'">
                        <div class="live-team-info">
                            <div class="live-team-score">${homeScore}</div>
                            <div class="live-team-name">${homeTeam}</div>
                        </div>
                    </div>
                </div>
                <div class="live-status-info">
                    ${isLive ? '<div class="live-indicator-red"></div>' : ''}
                    ${isFinal ? 
                        `<div class="live-time-remaining" style="font-size: 1.1em; font-weight: 500;">${statusDisplay}</div>
                         <div class="live-period" style="display: none;"></div>` :
                        `<div class="live-time-remaining">${timeDisplay}</div>
                         <div class="live-period">${periodDisplay}</div>`
                    }
                </div>
            </div>
            <div class="win-prob">
                <div class="win-prob-title">Win Probability</div>
                <div style="text-align: center; padding: 40px; color: #aaaaaa;">Loading...</div>
            </div>
        </div>
        <div class="game-tabs">
            <div class="tab active" onclick="switchTab('feed', '${gameId}')" id="feed-tab">Feed</div>
            <div class="tab" onclick="switchTab('game', '${gameId}')" id="game-tab">Game</div>
            <div class="tab" onclick="switchTab('away-team', '${gameId}')" id="away-team-tab">${basicInfo.away_team || awayTeam.substring(0, 3).toUpperCase()}</div>
            <div class="tab" onclick="switchTab('home-team', '${gameId}')" id="home-team-tab">${basicInfo.home_team || homeTeam.substring(0, 3).toUpperCase()}</div>
        </div>
        <div id="powerplay-display" style="display: none;"></div>
        <div id="feed-content" class="tab-content active">
            <div id="playbyplay-feed" class="playbyplay-feed">
                <div class="spinner"></div>
            </div>
        </div>
        <div id="game-content" class="tab-content">
            <div id="game-stats-container">
                <div class="spinner"></div>
            </div>
        </div>
        <div id="away-team-content" class="tab-content">
            <div id="away-team-stats-container">
                <div class="spinner"></div>
            </div>
        </div>
        <div id="home-team-content" class="tab-content">
            <div id="home-team-stats-container">
                <div class="spinner"></div>
            </div>
        </div>
    `;
    
    // Set current game info
    currentGameId = gameId;
    currentGameIsLive = isLive;
    currentHomeTeam = homeTeam;
    currentAwayTeam = awayTeam;
    currentHomeLogo = homeLogo;
    currentAwayLogo = awayLogo;
    
    // Start live score polling if game is live
    if (isLive) {
        startLiveScorePolling(gameId);
    }
    
    // Load play-by-play immediately (uses cached data if available)
    loadPlayByPlay(gameId, homeTeam, awayTeam, homeLogo, awayLogo, isLive);
    
    gameDetails.style.display = 'block';
    gameDetails.classList.add('show');
    gameDetails.scrollIntoView({ behavior: 'smooth' });
}

// Refresh game data in background

function switchTab(tabName, gameId) {
    // Update tab styles
    document.querySelectorAll('.tab').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    
    // Activate clicked tab
    const clickedTab = document.getElementById(`${tabName}-tab`);
    if (clickedTab) {
        clickedTab.classList.add('active');
    }
    
    // Show corresponding content
    const content = document.getElementById(`${tabName}-content`);
    if (content) {
        content.classList.add('active');
    }

    if (tabName === 'feed') {
        // Always refresh the feed when clicking on the feed tab, especially for live games
        const feed = document.getElementById('playbyplay-feed');
        if (feed) {
            // If we have cached data, use it immediately, otherwise load fresh
            if (liveGamesFeedCache[gameId] && liveGamesFeedCache[gameId].events) {
                const cached = liveGamesFeedCache[gameId];
                renderFeedEvents(cached.events, cached.homeTeam, cached.awayTeam, cached.homeLogo, cached.awayLogo, cached.isLive !== undefined ? cached.isLive : currentGameIsLive, gameId);
                // Also trigger a background update
                if (currentGameIsLive) {
                    updateGameFeedCache(gameId);
                }
            } else {
                // Use stored team info and live status
                loadPlayByPlay(gameId, currentHomeTeam, currentAwayTeam, currentHomeLogo, currentAwayLogo, currentGameIsLive);
            }
        }
        // Check power play status when switching to feed tab (in case element wasn't available before)
        if (currentGameIsLive) {
            loadPowerPlayStatus(gameId);
        }
    } else if (tabName === 'game') {
        loadGameStats(gameId);
    } else if (tabName === 'away-team') {
        loadTeamPlayerStats(gameId, 'away');
    } else if (tabName === 'home-team') {
        loadTeamPlayerStats(gameId, 'home');
    }
}


async function loadPlayByPlay(gameId, homeTeam, awayTeam, homeLogo = '', awayLogo = '', isLive = false) {
    const feed = document.getElementById('playbyplay-feed');
    if (!feed) return;

    // If this is a live game and background polling isn't started, start it
    if (isLive && !liveGamesPolling[gameId]) {
        // Start background polling for this game
        const gameData = {
            game_id: gameId,
            home_team_name: homeTeam,
            away_team_name: awayTeam,
            home_team_logo: homeLogo,
            away_team_logo: awayLogo,
            game_state: 'LIVE'
        };
        startGameFeedPolling(gameId, gameData);
    }

    // Always fetch fresh data immediately when clicking on a game (ensure it's up-to-date)
    // Show cached data first for instant display, then update with fresh data
    let useCache = false;
    if (liveGamesFeedCache[gameId] && liveGamesFeedCache[gameId].events) {
        // Use cached data for instant display
        const cached = liveGamesFeedCache[gameId];
        homeTeam = cached.homeTeam || homeTeam;
        awayTeam = cached.awayTeam || awayTeam;
        homeLogo = cached.homeLogo || homeLogo;
        awayLogo = cached.awayLogo || awayLogo;
        
                        // Render cached events immediately
                        const cachedIsLive = cached.isLive !== undefined ? cached.isLive : isLive;
                        renderFeedEvents(cached.events, homeTeam, awayTeam, homeLogo, awayLogo, cachedIsLive, gameId, cached.gameState);
        useCache = true;
    }
    
    // Always fetch fresh data in background to ensure it's up-to-date
    updateGameFeedCache(gameId);
    
    // If we didn't use cache, load normally
    if (!useCache) {
        // No cached data, load normally
        // Load power play status
        loadPowerPlayStatus(gameId);

        // Only show spinner if feed is empty or doesn't have events yet
        if (!feed.innerHTML || feed.innerHTML.includes('spinner') || feed.innerHTML.includes('No events')) {
            feed.innerHTML = '<div class="spinner"></div>';
        }

        try {
            const response = await fetch(`${API_BASE}/v1/games/${gameId}/playbyplay?limit=50`);
            if (!response.ok) {
                console.error(`[Feed] Failed to load play-by-play: ${response.status}`);
                feed.innerHTML = '<div style="color: #ee8888; text-align: center; padding: 40px;">Error loading play-by-play data</div>';
                return;
            }
            
            const data = await response.json();
            console.log(`[Feed] Loaded play-by-play for ${gameId}:`, {
                hasEvents: !!data.events,
                eventCount: data.events?.length || 0,
                gameState: data.game_state
            });

            if (data.events !== undefined) {
                // Cache the feed data for this game
                if (!liveGamesFeedCache[gameId]) {
                    liveGamesFeedCache[gameId] = {};
                }
                liveGamesFeedCache[gameId].events = data.events || [];
                liveGamesFeedCache[gameId].homeTeam = homeTeam;
                liveGamesFeedCache[gameId].awayTeam = awayTeam;
                liveGamesFeedCache[gameId].homeLogo = homeLogo;
                liveGamesFeedCache[gameId].awayLogo = awayLogo;
                liveGamesFeedCache[gameId].isLive = isLive;
                liveGamesFeedCache[gameId].gameState = data.game_state || null;
                liveGamesFeedCache[gameId].lastEventCount = data.events ? data.events.length : 0;
                liveGamesFeedCache[gameId].lastGoalCount = data.events ? data.events.filter(e => e.event_type === 'GOAL').length : 0;
                liveGamesFeedCache[gameId].lastUpdate = Date.now();
                
                // Render the events
                renderFeedEvents(data.events || [], homeTeam, awayTeam, homeLogo, awayLogo, isLive, gameId, data.game_state);
            } else if (data.events && data.events.length === 0) {
                // Show appropriate message based on whether game is live or not
                const message = isLive 
                    ? '<div style="color: #aaaaaa; text-align: center; padding: 40px;">No events yet. Play-by-play will appear here once the game starts.</div>'
                    : '<div style="color: #aaaaaa; text-align: center; padding: 40px;">No events yet. Start ingestion to see play-by-play.</div>';
                feed.innerHTML = message;
                // Polling is already started by startGameFeedPolling above
                return;
            } else {
                const errorMessage = isLive
                    ? '<div style="color: #aaaaaa; text-align: center; padding: 40px;">Error loading play-by-play. Retrying...</div>'
                    : '<div style="color: #aaaaaa; text-align: center; padding: 40px;">Error loading play-by-play.</div>';
                feed.innerHTML = errorMessage;
                // Polling is already started by startGameFeedPolling above
            }
        } catch (error) {
            feed.innerHTML = `<div style="color: #ee8888; text-align: center; padding: 40px;">Error: ${error.message}</div>`;
            // Polling is already started by startGameFeedPolling above
        }
    }
}

// Load standings

async function loadPowerPlayStatus(gameId) {
    const powerPlayDisplay = document.getElementById('powerplay-display');
    if (!powerPlayDisplay) {
        // Silently return - element might not exist if not on feed tab
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/v1/games/${gameId}/powerplay`);
        const data = await response.json();
        
        if (response.ok && data.is_powerplay && data.time_remaining && data.time_remaining > 0) {
            // Format time remaining as :SS (e.g., :25)
            const seconds = Math.floor(data.time_remaining % 60);
            const timeStr = `:${seconds.toString().padStart(2, '0')} remaining`;
            
            // Get strength (e.g., "5 on 4")
            const strength = data.strength || "5 on 4";
            
            const logoHtml = data.team_logo 
                ? `<img src="${data.team_logo}" alt="Power Play Team" class="powerplay-logo" onerror="this.style.display='none'">`
                : '';
            
            // Display only time remaining
            const timeDisplay = timeStr;
            
            powerPlayDisplay.innerHTML = `
                <div class="powerplay-container">
                    ${logoHtml}
                    <div class="powerplay-text">${strength}, ${timeDisplay}</div>
                </div>
            `;
            powerPlayDisplay.style.display = 'block';
            powerPlayDisplay.style.visibility = 'visible';
        } else {
            // Hide power play display if no active power play
            powerPlayDisplay.style.display = 'none';
            powerPlayDisplay.innerHTML = '';
        }
    } catch (error) {
        // Silently handle errors - don't spam console
        powerPlayDisplay.style.display = 'none';
    }
}


