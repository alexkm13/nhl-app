// Utility functions

// Helper function to escape HTML to prevent XSS attacks
function escapeHtml(unsafe) {
    if (typeof unsafe !== 'string') {
        return String(unsafe || '');
    }
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// Helper function to adjust color brightness for better contrast
function adjustColorBrightness(color, percent) {
    const num = parseInt(color.replace("#",""), 16);
    const amt = Math.round(2.55 * percent);
    const R = Math.min(255, Math.max(0, (num >> 16) + amt));
    const G = Math.min(255, Math.max(0, ((num >> 8) & 0x00FF) + amt));
    const B = Math.min(255, Math.max(0, (num & 0x0000FF) + amt));
    return "#" + (0x1000000 + R * 0x10000 + G * 0x100 + B).toString(16).slice(1);
}

// Helper function to format date as YYYY-MM-DD in local time
function formatDateLocal(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

// Show status message
function showStatus(message, type) {
    const statusEl = document.getElementById('status');
    if (!statusEl) return;
    
    statusEl.textContent = message;
    statusEl.className = `status ${type || ''}`;
    statusEl.style.display = 'block';
    
    if (type !== 'error') {
        setTimeout(() => {
            statusEl.style.display = 'none';
        }, 3000);
    }
}

// Time conversion utility function (DRY principle)
// Parses MM:SS time string and returns seconds
// Returns 0 if format is invalid
function parseTimeToSeconds(timeStr) {
    if (!timeStr || typeof timeStr !== 'string') {
        return 0;
    }
    const parts = timeStr.split(':');
    if (parts.length !== 2) {
        return 0;
    }
    const minutes = Number(parts[0]) || 0;
    const seconds = Number(parts[1]) || 0;
    return minutes * 60 + seconds;
}

// Get period label (1st, 2nd, 3rd, OT, etc.)
function getPeriodLabel(period) {
    if (period === 1) return '1st';
    if (period === 2) return '2nd';
    if (period === 3) return '3rd';
    if (period === 4) return 'OT';
    return `${period}th`;
}

// Format time for game display (handles both elapsed and remaining time)
function formatGameTime(timeInPeriod, period, isTimeRemaining) {
    if (!timeInPeriod || timeInPeriod === '00:00') {
        // If time is 00:00, show full period time
        return (period <= 3) ? '20:00' : '5:00';
    }

    if (isTimeRemaining) {
        // Already time remaining, use directly
        const [minutes, seconds] = timeInPeriod.split(':').map(Number);
        return `${minutes}:${seconds.toString().padStart(2, '0')}`;
    } else {
        // Convert elapsed time to remaining
        const [elapsedMinutes, elapsedSeconds] = timeInPeriod.split(':').map(Number);
        const elapsedTotalSeconds = elapsedMinutes * 60 + elapsedSeconds;

        // Determine period length: 20 minutes (1200 seconds) for regulation, 5 minutes (300 seconds) for OT
        const periodLengthSeconds = (period <= 3) ? 1200 : 300;
        const remainingTotalSeconds = Math.max(0, periodLengthSeconds - elapsedTotalSeconds);

        const remainingMinutes = Math.floor(remainingTotalSeconds / 60);
        const remainingSecs = remainingTotalSeconds % 60;
        return `${remainingMinutes}:${remainingSecs.toString().padStart(2, '0')}`;
    }
}

// Render a single game card (consolidated from api.js and polling.js)
function renderGameCard(game) {
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

    // Determine winner/loser for final games
    if (isFinal && !isTie) {
        // Away team row (always on top)
        const awayRow = awayIsWinner ?
            `<div class="game-score-row winner">
                <div class="game-winner-indicator">▶</div>
                <img src="${escapeHtml(game.away_team_logo || '')}" alt="${escapeHtml(game.away_team_name)}" class="game-team-logo" onerror="this.style.display='none'">
                <div class="game-team-name">${escapeHtml(game.away_team_name || game.away_team)}</div>
                <div class="game-team-score">${awayScore}</div>
            </div>` :
            `<div class="game-score-row loser">
                <img src="${escapeHtml(game.away_team_logo || '')}" alt="${escapeHtml(game.away_team_name)}" class="game-team-logo" onerror="this.style.display='none'">
                <div class="game-team-name">${escapeHtml(game.away_team_name || game.away_team)}</div>
                <div class="game-team-score">${awayScore}</div>
            </div>`;

        // Home team row (always on bottom)
        const homeRow = homeIsWinner ?
            `<div class="game-score-row winner">
                <div class="game-winner-indicator">▶</div>
                <img src="${escapeHtml(game.home_team_logo || '')}" alt="${escapeHtml(game.home_team_name)}" class="game-team-logo" onerror="this.style.display='none'">
                <div class="game-team-name">${escapeHtml(game.home_team_name || game.home_team)}</div>
                <div class="game-team-score">${homeScore}</div>
            </div>` :
            `<div class="game-score-row loser">
                <img src="${escapeHtml(game.home_team_logo || '')}" alt="${escapeHtml(game.home_team_name)}" class="game-team-logo" onerror="this.style.display='none'">
                <div class="game-team-name">${escapeHtml(game.home_team_name || game.home_team)}</div>
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
        // Live or future game
        const isLive = game.game_state === 'LIVE' || game.game_state === 'CRIT';

        let gameTimeDisplay = 'TBD';
        let periodDisplay = '';

        if (isLive) {
            const period = game.period || game.periodDescriptor?.number || null;
            const timeInPeriod = game.time_in_period || game.timeInPeriod || null;

            if (period && timeInPeriod) {
                periodDisplay = getPeriodLabel(period);
                gameTimeDisplay = formatGameTime(timeInPeriod, period, game.is_time_remaining === true);
            } else {
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

        // Only show records for games that haven't started
        const showRecords = !isLive;
        const awayRecord = showRecords && game.away_team_record ? `<div class="game-team-record">${game.away_team_record}</div>` : '';
        const homeRecord = showRecords && game.home_team_record ? `<div class="game-team-record">${game.home_team_record}</div>` : '';

        return `
            <div class="game-card ${isLive ? 'live' : ''}" onclick="selectGame('${escapeHtml(game.game_id)}')">
                <div class="game-live-score">
                    <div class="game-live-team-left">
                        <img src="${escapeHtml(game.away_team_logo || '')}" alt="${escapeHtml(game.away_team_name)}" class="game-live-logo" onerror="this.style.display='none'">
                        <div class="game-live-score-num">${awayScore}</div>
                        <div class="game-live-team-name">${escapeHtml(game.away_team_name || game.away_team)}</div>
                        ${awayRecord}
                    </div>
                    <div class="game-live-time-container">
                        ${isLive ? '<div class="game-live-indicator"></div>' : ''}
                        <div class="game-live-time">${escapeHtml(gameTimeDisplay)}</div>
                        ${isLive ?
                            `<div class="game-spread">${escapeHtml(periodDisplay)}</div>` :
                            (game.spread !== null && game.spread !== undefined ?
                                `<div class="game-spread">${escapeHtml(game.spread_favorite === 'home' ? game.home_team_name : game.away_team_name)} ${game.spread > 0 ? '+' : ''}${game.spread}</div>` :
                                '<div class="game-spread">N/A</div>')}
                    </div>
                    <div class="game-live-team-right">
                        <img src="${escapeHtml(game.home_team_logo || '')}" alt="${escapeHtml(game.home_team_name)}" class="game-live-logo" onerror="this.style.display='none'">
                        <div class="game-live-score-num">${homeScore}</div>
                        <div class="game-live-team-name">${escapeHtml(game.home_team_name || game.home_team)}</div>
                        ${homeRecord}
                    </div>
                </div>
            </div>
        `;
    }
}

// Render all game cards
function renderAllGameCards(games) {
    return games.map(game => renderGameCard(game)).join('');
}

