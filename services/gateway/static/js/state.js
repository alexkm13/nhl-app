// Application state management
// All state variables are stored here for centralized management

// Polling intervals
let playByPlayPollInterval = null;
let goalCheckPollInterval = null; // Fast polling for goal detection
let liveScorePollInterval = null;
let powerPlayPollInterval = null; // Polling for power play status
let gamesListPollInterval = null; // Polling for games list updates

// Current game state
let currentGameId = null;
let currentGameIsLive = false;
let currentHomeTeam = '';
let currentAwayTeam = '';
let currentHomeLogo = '';
let currentAwayLogo = '';
let lastEventCount = 0; // Track number of events to detect new goals
let lastGoalCount = 0; // Track goal count to detect new goals

// Caches for game data to enable instant loading
let gameDataCache = {};
let gamesListData = {}; // Map of gameId -> basic game info from games list

// Track all live games and their polling intervals
let liveGamesPolling = {}; // Map of gameId -> { interval, goalCheckInterval, gameData }
let liveGamesFeedCache = {}; // Map of gameId -> { events, homeTeam, awayTeam, homeLogo, awayLogo, isLive }

// Track games that have had ingestion started to prevent duplicate starts
let ingestionStartedForGames = new Set();

// Track processed stoppages for live games
let processedStoppages = new Set();

// Track rendered event IDs to prevent duplicates
let renderedEventIds = new Set();
let lastRenderedEventCount = 0;

// Track ongoing feed updates to prevent race conditions
const ongoingFeedUpdates = new Set();

// Initialize cache invalidation on version change
const storedVersion = sessionStorage.getItem('app_version');
if (storedVersion !== APP_VERSION) {
    // Clear all caches when version changes
    gameDataCache = {};
    gamesListData = {};
    liveGamesFeedCache = {};
    liveGamesPolling = {};
    sessionStorage.setItem('app_version', APP_VERSION);
    console.log(`[Cache] Cleared all caches due to version change (${storedVersion || 'none'} → ${APP_VERSION})`);
}

