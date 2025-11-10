async function loadGamesList(date = null) {
    const gamesList = document.getElementById('gamesList');
    gamesList.innerHTML = '<div class="spinner"></div>';

    try {
        // Always use a date - default to today if not provided
        if (!date) {
            date = new Date();
        }
        const dateStr = formatDateLocal(date);
        const url = `${API_BASE}/v1/games?date=${dateStr}`;

        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();

        if (data.games && data.games.length > 0) {
            // Store basic game info for instant display
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
            
            // Prefetch game data for instant loading
            prefetchGameData(data.games.map(g => g.game_id));
            
            // Check if there are any live games - if so, start polling
            const hasLiveGames = data.games.some(g => g.game_state === 'LIVE' || g.game_state === 'CRIT');
            if (hasLiveGames) {
                startGamesListPolling(date);
                // Start/update polling for all live games
                updateLiveGameFeedPolling(data.games);
            } else {
                stopGamesListPolling();
                stopAllLiveGameFeedPolling();
            }
            
            gamesList.innerHTML = renderAllGameCards(data.games);
        } else {
            gamesList.innerHTML = '<div style="color: #aaaaaa; padding: 20px; text-align: center;">No games scheduled for this date</div>';
        }
    } catch (error) {
        console.error('Error loading games:', error);
        gamesList.innerHTML = '<div style="color: #ee8888; padding: 20px; text-align: center;">Error loading games</div>';
    }
}

// Prefetch game data for all games on current date

async function prefetchGameData(gameIds) {
    // Prefetch in parallel for all games - both win probability and play-by-play
    const prefetchPromises = gameIds.map(async (gameId) => {
        try {
            // Prefetch win probability
            const winprobResponse = await fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`);
            if (winprobResponse.ok) {
                const data = await winprobResponse.json();
                gameDataCache[gameId] = data;
            } else {
                console.debug(`[Prefetch] Failed to prefetch winprob for game ${gameId}: ${winprobResponse.status}`);
            }
            
            // Prefetch play-by-play data (this will populate Redis cache)
            // Don't await - just fire and forget to populate cache
            fetch(`${API_BASE}/v1/games/${gameId}/playbyplay?limit=50`)
                .catch((error) => {
                    console.debug(`[Prefetch] Failed to prefetch playbyplay for game ${gameId}:`, error);
                });
        } catch (error) {
            // Add console.debug for prefetch failures
            console.debug(`[Prefetch] Error prefetching game ${gameId}:`, error);
        }
    });
    // Don't await - let it run in background
    Promise.all(prefetchPromises).catch((error) => {
        console.debug('[Prefetch] Error in prefetch batch:', error);
    });
}


async function selectGame(gameId) {
    // Hide games list immediately
    // Inline showGameDetails logic here since ui.js loads after api.js
    const mainContainer = document.querySelector('.main-container');
    if (mainContainer) {
        mainContainer.style.display = 'none';
    }
    
    // Show game details
    let gameDetails = document.getElementById('gameDetails');
    if (gameDetails) {
        gameDetails.style.display = 'block';
        gameDetails.classList.add('show');
        gameDetails.scrollIntoView({ behavior: 'smooth' });
    }
    
    // Show cached data immediately for instant display
    if (gameDataCache[gameId]) {
        displayResults(gameDataCache[gameId]);
        // Fetch fresh data in background (non-blocking)
        fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`)
            .then(response => {
                if (response.ok) {
                    return response.json();
                }
                return null;
            })
            .then(data => {
                if (data) {
                    gameDataCache[gameId] = data; // Update cache
                    // Update display if still viewing this game
                    if (currentGameId === gameId) {
                        displayResults(data);
                    }
                }
            })
            .catch(error => {
                console.error('Error refreshing game data:', error);
            });
        return; // Return immediately after showing cached data
    }
    
    // No cache - show basic info immediately if available from games list, then fetch full data
    const basicInfo = gamesListData[gameId];
    if (basicInfo) {
        // Show basic game info immediately for instant display
        showBasicGameInfo(gameId, basicInfo);
        // Fetch full data in background (non-blocking)
        fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`)
            .then(response => {
                if (response.ok) {
                    return response.json();
                }
                return null;
            })
            .then(data => {
                if (data) {
                    gameDataCache[gameId] = data; // Cache it
                    // Update display if still viewing this game
                    if (currentGameId === gameId) {
                        displayResults(data);
                    }
                }
            })
            .catch(error => {
                // Silently handle network errors - don't spam console
                // Only log if it's a non-network error
                if (error.name !== 'TypeError' || !error.message.includes('fetch')) {
                    console.error('Error fetching game data:', error);
                }
                // If fetch fails, start ingestion (but don't block feed loading)
                // Only for non-completed games
                if (currentGameId === gameId && !basicInfo.is_final && basicInfo.game_state !== 'OFF' && basicInfo.game_state !== 'FINAL') {
                    startIngestionForGame(gameId).catch(() => {
                        // Silently fail - feed should still work
                    });
                }
            });
        return; // Return immediately after showing basic info
    }
    
    // No basic info either - show loading state and fetch
    // gameDetails already declared above, reuse it
    if (!gameDetails) {
        gameDetails = document.getElementById('gameDetails');
    }
    const placeholder = document.getElementById('game-content-placeholder');
    if (placeholder) {
        placeholder.innerHTML = '<div class="spinner"></div><div style="text-align: center; color: #aaaaaa; margin-top: 20px;">Loading game...</div>';
    }
    
    // Fetch fresh data (non-blocking)
    fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`)
        .then(response => {
            if (response.ok) {
                return response.json();
            }
            return null;
        })
        .then(data => {
            if (data) {
                gameDataCache[gameId] = data; // Cache it
                if (currentGameId === gameId) {
                    displayResults(data);
                }
            } else {
                // If fetch fails, start ingestion (only for non-completed games)
                // Only retry once to prevent infinite recursion
                if (currentGameId === gameId) {
                    // Check if game is completed before starting ingestion
                    fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`)
                        .then(checkResponse => {
                            if (checkResponse.ok) {
                                return checkResponse.json();
                            }
                            return null;
                        })
                        .then(checkData => {
                            // Start ingestion for any game (live or final) to enable backfill
                            if (checkData && currentGameId === gameId) {
                                startIngestionForGame(gameId).catch(err => {
                                    console.error('Error starting ingestion:', err);
                                });
                            } else if (currentGameId === gameId) {
                                // If we can't check, try starting ingestion anyway (only once)
                                startIngestionForGame(gameId).catch(err => {
                                    console.error('Error starting ingestion:', err);
                                });
                            }
                        })
                        .catch(err => {
                            // On fetch error, log and stop (don't recurse)
                            console.warn('Unable to verify game state for ingestion:', err.message);
                        });
                }
            }
        })
        .catch(error => {
            // Silently handle network errors - don't spam console
            // Only log if it's a non-network error
            if (error.name !== 'TypeError' || !error.message.includes('fetch')) {
                console.error('Error fetching game data:', error);
            }
            // If fetch fails, start ingestion (but don't block feed loading)
            if (currentGameId === gameId) {
                startIngestionForGame(gameId).catch(() => {
                    // Silently fail - feed should still work
                });
            }
        });
}

// Show basic game info immediately while fetching full data

async function refreshGameData(gameId) {
    try {
        const response = await fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`);
        if (response.ok) {
            const data = await response.json();
            
            // Validate data structure before proceeding
            if (!data || !data.game) {
                console.warn('refreshGameData: invalid data structure', data);
                return;
            }
            
            const isFinal = data.game && (data.game.game_state === 'OFF' || data.game.game_state === 'FINAL');
            
            // For completed games, only update if data has changed
            // Guard against missing score data
            if (isFinal && gameDataCache[gameId] && currentGameId === gameId) {
                const cachedData = gameDataCache[gameId];
                
                // Validate that both cached and new data have score information
                if (cachedData.score && cachedData.score.home && cachedData.score.away &&
                    data.score && data.score.home && data.score.away &&
                    data.win_probability && cachedData.win_probability) {
                    
                    const dataChanged = 
                        cachedData.score.home.goals !== data.score.home.goals ||
                        cachedData.score.away.goals !== data.score.away.goals ||
                        Math.abs((cachedData.win_probability[data.score.home.team] || 0) - (data.win_probability[data.score.home.team] || 0)) > 0.001;
                    
                    if (!dataChanged) {
                        return; // Data hasn't changed, don't re-render
                    }
                }
            }
            
            gameDataCache[gameId] = data;
            // Only update UI if we're still viewing this game
            if (currentGameId === gameId) {
                displayResults(data);
            }
        }
    } catch (error) {
        // Silently fail - cached data is still valid
        console.warn('refreshGameData error:', error);
    }
}


async function fetchResults(gameId, retryCount = 0) {
    const MAX_RETRIES = 60; // Maximum 5 minutes of polling (60 * 5 seconds)

    try {
        const response = await fetch(`${API_BASE}/v1/games/${gameId}/winprob/friendly`);
        const data = await response.json();

        if (response.ok) {
            // Validate data structure before proceeding
            if (!data || !data.game) {
                console.error('fetchResults: invalid data structure', data);
                const gameDetails = document.getElementById('gameDetails');
                if (gameDetails) {
                    gameDetails.innerHTML = `
                        <div class="back-button-container">
                            <button class="back-button" onclick="showGamesList()">← Back to Games</button>
                        </div>
                        <div style="text-align: center; padding: 40px; color: #ee8888;">
                            <div style="font-size: 1.2em; margin-bottom: 10px;">Error Loading Game</div>
                            <div>Invalid game data received</div>
                        </div>
                    `;
                    gameDetails.style.display = 'block';
                    gameDetails.classList.add('show');
                }
                return;
            }

            // For completed games, only re-display if data has actually changed
            // Guard against missing score data
            const isFinal = data.game && (data.game.game_state === 'OFF' || data.game.game_state === 'FINAL');
            if (isFinal && gameDataCache[gameId] && currentGameId === gameId) {
                // Check if data has actually changed
                const cachedData = gameDataCache[gameId];

                // Validate that both cached and new data have score information
                if (cachedData.score && cachedData.score.home && cachedData.score.away &&
                    data.score && data.score.home && data.score.away &&
                    data.win_probability && cachedData.win_probability &&
                    data.score.home.team) {

                    const dataChanged =
                        cachedData.score.home.goals !== data.score.home.goals ||
                        cachedData.score.away.goals !== data.score.away.goals ||
                        Math.abs((cachedData.win_probability[data.score.home.team] || 0) - (data.win_probability[data.score.home.team] || 0)) > 0.001;

                    // Only re-display if data actually changed
                    if (!dataChanged) {
                        return; // Data hasn't changed, don't re-render
                    }
                }
            }

            displayResults(data);
        } else if (response.status === 202) {
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
            setTimeout(() => pollForResults(gameId, retryCount + 1), 5000);
        } else {
            // Show error message in game details with back button already visible
            const gameDetails = document.getElementById('gameDetails');
            const placeholder = document.getElementById('game-content-placeholder');
            if (placeholder) {
                placeholder.innerHTML = `
                    <div style="text-align: center; padding: 40px; color: #ee8888;">
                        <div style="font-size: 1.2em; margin-bottom: 10px;">Error Loading Game</div>
                        <div>${data.detail || 'Unknown error'}</div>
                    </div>
                `;
            } else if (gameDetails) {
                gameDetails.innerHTML = `
                    <div class="back-button-container">
                        <button class="back-button" onclick="showGamesList()">← Back to Games</button>
                    </div>
                    <div style="text-align: center; padding: 40px; color: #ee8888;">
                        <div style="font-size: 1.2em; margin-bottom: 10px;">Error Loading Game</div>
                        <div>${data.detail || 'Unknown error'}</div>
                    </div>
                `;
                gameDetails.style.display = 'block';
                gameDetails.classList.add('show');
            }
        }
    } catch (error) {
        // Show error message in game details with back button already visible
        const gameDetails = document.getElementById('gameDetails');
        const placeholder = document.getElementById('game-content-placeholder');
        if (placeholder) {
            placeholder.innerHTML = `
                <div style="text-align: center; padding: 40px; color: #ee8888;">
                    <div style="font-size: 1.2em; margin-bottom: 10px;">Error Loading Game</div>
                    <div>${error.message || 'Network error'}</div>
                </div>
            `;
        } else if (gameDetails) {
            gameDetails.innerHTML = `
                <div class="back-button-container">
                    <button class="back-button" onclick="showGamesList()">← Back to Games</button>
                </div>
                <div style="text-align: center; padding: 40px; color: #ee8888;">
                    <div style="font-size: 1.2em; margin-bottom: 10px;">Error Loading Game</div>
                    <div>${error.message || 'Network error'}</div>
                </div>
            `;
            gameDetails.style.display = 'block';
            gameDetails.classList.add('show');
        }
    }
}


async function loadGameStats(gameId) {
    const container = document.getElementById('game-stats-container');
    if (!container) return;
    
    container.innerHTML = '<div class="spinner"></div>';
    
    try {
        const response = await fetch(`${API_BASE}/v1/games/${gameId}/stats`);
        const data = await response.json();
        
        if (response.ok && data.stats) {
            const stats = data.stats;
            const homeTeam = data.home_team;
            const awayTeam = data.away_team;
            
            // Function to create a stat row with bar graph
            // Away team on LEFT, Home team on RIGHT
            function createStatRow(statName, homeValue, awayValue, displayName = null, homeLogo = '', awayLogo = '', homeAbbrev = '', awayAbbrev = '') {
                const total = homeValue + awayValue;
                const homePercent = total > 0 ? (homeValue / total * 100) : 50;
                const awayPercent = total > 0 ? (awayValue / total * 100) : 50;
                const label = displayName || statName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                
                // Get team colors, fallback to default if not found
                const homeColor = TEAM_COLORS[homeAbbrev] || '#444';
                const awayColor = TEAM_COLORS[awayAbbrev] || '#0066cc';
                
                return `
                    <div class="stat-row">
                        <div class="stat-value-left-container">
                            ${awayLogo ? `<img src="${awayLogo}" alt="Away" class="stat-team-logo" onerror="this.style.display='none'">` : ''}
                            <div class="stat-value stat-value-left">${awayValue}</div>
                        </div>
                        <div class="stat-label">${label}</div>
                        <div class="stat-value-right-container">
                            <div class="stat-value stat-value-right">${homeValue}</div>
                            ${homeLogo ? `<img src="${homeLogo}" alt="Home" class="stat-team-logo" onerror="this.style.display='none'">` : ''}
                        </div>
                        <div class="stat-bar-container">
                            <div class="stat-bar stat-bar-away" style="width: ${awayPercent}%; background-color: ${awayColor};"></div>
                            <div class="stat-bar stat-bar-home" style="width: ${homePercent}%; background-color: ${homeColor};"></div>
                        </div>
                    </div>
                `;
            }
            
            container.innerHTML = `
                <div class="game-stats-header">
                    <h2>Head-to-head</h2>
                </div>
                <div class="game-stats-body">
                    ${createStatRow('shots', stats.shots.home, stats.shots.away, 'Shots', homeTeam.logo, awayTeam.logo, homeTeam.abbrev, awayTeam.abbrev)}
                    ${createStatRow('hits', stats.hits.home, stats.hits.away, 'Hits', homeTeam.logo, awayTeam.logo, homeTeam.abbrev, awayTeam.abbrev)}
                    ${createStatRow('faceoff_win_pct', stats.faceoff_win_pct.home, stats.faceoff_win_pct.away, 'Face-off win %', homeTeam.logo, awayTeam.logo, homeTeam.abbrev, awayTeam.abbrev)}
                    ${createStatRow('penalty_minutes', stats.penalty_minutes.home, stats.penalty_minutes.away, 'Penalty minutes', homeTeam.logo, awayTeam.logo, homeTeam.abbrev, awayTeam.abbrev)}
                    ${createStatRow('power_play_pct', stats.power_play_pct.home, stats.power_play_pct.away, 'Power play %', homeTeam.logo, awayTeam.logo, homeTeam.abbrev, awayTeam.abbrev)}
                    ${createStatRow('power_play_opportunities', stats.power_play_opportunities.home, stats.power_play_opportunities.away, 'Power play opportunities', homeTeam.logo, awayTeam.logo, homeTeam.abbrev, awayTeam.abbrev)}
                    ${createStatRow('blocked_shots', stats.blocked_shots.home, stats.blocked_shots.away, 'Blocked shots', homeTeam.logo, awayTeam.logo, homeTeam.abbrev, awayTeam.abbrev)}
                    ${createStatRow('takeaways', stats.takeaways.home, stats.takeaways.away, 'Takeaways', homeTeam.logo, awayTeam.logo, homeTeam.abbrev, awayTeam.abbrev)}
                    ${createStatRow('giveaways', stats.giveaways.home, stats.giveaways.away, 'Giveaways', homeTeam.logo, awayTeam.logo, homeTeam.abbrev, awayTeam.abbrev)}
                </div>
            `;
        } else {
            container.innerHTML = '<div style="color: #aaaaaa; text-align: center; padding: 40px;">Error loading game stats.</div>';
        }
    } catch (error) {
        container.innerHTML = `<div style="color: #ee8888; text-align: center; padding: 40px;">Error: ${error.message}</div>`;
    }
}


async function loadTeamPlayerStats(gameId, team) {
    const containerId = team === 'away' ? 'away-team-stats-container' : 'home-team-stats-container';
    const container = document.getElementById(containerId);
    if (!container) return;
    
    container.innerHTML = '<div class="spinner"></div>';
    
    try {
        const response = await fetch(`${API_BASE}/v1/games/${gameId}/player-stats`);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error(`Player stats API error: ${response.status} ${response.statusText}`, errorText);
            container.innerHTML = `<div style="color: #ee8888; text-align: center; padding: 40px;">Error loading player stats: ${response.status} ${response.statusText}</div>`;
            return;
        }
        
        const data = await response.json();
        
        if (data && data.away_team && data.home_team) {
            const teamData = team === 'away' ? data.away_team : data.home_team;
            const skaters = teamData.skaters || [];
            const goalies = teamData.goalies || [];
            
            // Function to render a skater row
            function renderSkaterRow(player) {
                const stats = player.stats || {};
                const plusMinus = stats.plus_minus || 0;
                const plusMinusClass = plusMinus > 0 ? 'plus-minus-positive' : plusMinus < 0 ? 'plus-minus-negative' : '';
                
                return `
                    <div class="player-stat-row">
                        <div class="player-info">
                            ${player.headshot ? `<img src="${player.headshot}" alt="${player.name}" class="player-headshot" onerror="this.style.display='none'">` : '<div class="player-headshot-placeholder"></div>'}
                            <div class="player-name-info">
                                <div class="player-name">${player.name || 'Unknown'}</div>
                                <div class="player-position">${player.position || ''}</div>
                            </div>
                        </div>
                        <div class="player-stats-grid">
                            <div class="stat-item">
                                <div class="stat-value">${stats.pts || 0}</div>
                                <div class="stat-label">PTS</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${stats.goals || 0}</div>
                                <div class="stat-label">GOAL</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${stats.assists || 0}</div>
                                <div class="stat-label">AST</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value ${plusMinusClass}">${plusMinus >= 0 ? '+' : ''}${plusMinus}</div>
                                <div class="stat-label">+/-</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${stats.pim || 0}</div>
                                <div class="stat-label">PIM</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${stats.sog || 0}</div>
                                <div class="stat-label">SOG</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${stats.hits || 0}</div>
                                <div class="stat-label">HITS</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${stats.toi || '0:00'}</div>
                                <div class="stat-label">TOI</div>
                            </div>
                        </div>
                    </div>
                `;
            }
            
            // Function to render a goalie row
            function renderGoalieRow(player) {
                const stats = player.stats || {};
                
                return `
                    <div class="player-stat-row">
                        <div class="player-info">
                            ${player.headshot ? `<img src="${player.headshot}" alt="${player.name}" class="player-headshot" onerror="this.style.display='none'">` : '<div class="player-headshot-placeholder"></div>'}
                            <div class="player-name-info">
                                <div class="player-name">${player.name || 'Unknown'}</div>
                                <div class="player-position">${player.position || 'G'}</div>
                            </div>
                        </div>
                        <div class="player-stats-grid goalie-stats">
                            <div class="stat-item">
                                <div class="stat-value">${stats.toi || '0:00'}</div>
                                <div class="stat-label">TOI</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${stats.saves_shots || '0/0'}</div>
                                <div class="stat-label">SV/S</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${stats.sv_pct || 0}%</div>
                                <div class="stat-label">SV%</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${stats.pp_saves_shots || '0/0'}</div>
                                <div class="stat-label">PP/S</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${stats.sh_saves_shots || '0/0'}</div>
                                <div class="stat-label">SH/S</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-value">${stats.pim || 0}</div>
                                <div class="stat-label">PIM</div>
                            </div>
                        </div>
                    </div>
                `;
            }
            
            let html = '<div class="team-player-stats">';
            
            // Render goalies first
            if (goalies.length > 0) {
                goalies.forEach(goalie => {
                    html += renderGoalieRow(goalie);
                });
            }
            
            // Then render skaters
            if (skaters.length > 0) {
                skaters.forEach(skater => {
                    html += renderSkaterRow(skater);
                });
            }
            
            if (goalies.length === 0 && skaters.length === 0) {
                html += '<div style="color: #aaaaaa; text-align: center; padding: 40px;">No player stats available.</div>';
            }
            
            html += '</div>';
            container.innerHTML = html;
        } else {
            container.innerHTML = '<div style="color: #aaaaaa; text-align: center; padding: 40px;">Error loading player stats.</div>';
        }
    } catch (error) {
        console.error('Error loading team player stats:', error);
        container.innerHTML = `<div style="color: #ee8888; text-align: center; padding: 40px;">Error: ${error.message}</div>`;
    }
}

// Track rendered event IDs to prevent unnecessary re-renders
// Note: renderedEventIds and lastRenderedEventCount are defined in state.js
let lastPenaltyCount = 0; // Track penalty count to detect new penalties

// Note: processedStoppages is defined in state.js

async function loadStandings() {
    const container = document.getElementById('standingsContainer');
    if (!container) return;
    
    container.innerHTML = '<div class="spinner"></div>';
    
    try {
        const response = await fetch(`${API_BASE}/v1/standings`);
        const data = await response.json();
        
        if (response.ok && data.standings && data.standings.length > 0) {
            container.innerHTML = `
                <div class="standings-table">
                    <div class="standings-header">
                        <div class="standings-rank">#</div>
                        <div class="standings-team">Team</div>
                        <div class="standings-gp">GP</div>
                        <div class="standings-w">W</div>
                        <div class="standings-l">L</div>
                        <div class="standings-otl">OTL</div>
                        <div class="standings-pts">PTS</div>
                    </div>
                    ${data.standings.map((team, index) => `
                        <div class="standings-row">
                            <div class="standings-rank">${index + 1}</div>
                            <div class="standings-team">
                                ${team.logo ? `<img src="${team.logo}" alt="${team.full_name}" class="standings-logo" onerror="this.style.display='none'">` : ''}
                                <span class="standings-team-name">${team.abbreviation}</span>
                            </div>
                            <div class="standings-gp">${team.games_played}</div>
                            <div class="standings-w">${team.wins}</div>
                            <div class="standings-l">${team.losses}</div>
                            <div class="standings-otl">${team.ot_losses}</div>
                            <div class="standings-pts">${team.points}</div>
                        </div>
                    `).join('')}
                </div>
            `;
        } else {
            container.innerHTML = '<div style="color: #aaaaaa; text-align: center; padding: 20px;">No standings data available</div>';
        }
    } catch (error) {
        console.error('Error loading standings:', error);
        container.innerHTML = '<div style="color: #ee8888; text-align: center; padding: 20px;">Error loading standings</div>';
    }
}

