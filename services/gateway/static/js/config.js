// Configuration constants
const API_BASE = window.location.origin || 'http://localhost:8000';

// NHL team colors mapping
const TEAM_COLORS = {
    "ANA": "#F47A38", "BOS": "#FFB81C", "BUF": "#003087", "CGY": "#C8102E",
    "CAR": "#CC0000", "CHI": "#CF0A2C", "COL": "#8B2942", "CBJ": "#002654",
    "DAL": "#006847", "DET": "#CE1126", "EDM": "#041E42", "FLA": "#C8102E",
    "LAK": "#A2AAAD", "MIN": "#154734", "MTL": "#AF1E2D", "NSH": "#FFB81C",
    "NJD": "#CE1126", "NYI": "#00539B", "NYR": "#0038A8", "OTT": "#C8102E",
    "PHI": "#F74902", "PIT": "#FCB514", "SJS": "#006D75", "SEA": "#001628",
    "STL": "#003087", "TBL": "#002868", "TOR": "#00205B", "VAN": "#00205B",
    "VGK": "#B9975B", "WSH": "#C8102E", "WPG": "#041E42", "UTA": "#6CACE3"
};

// Application version for cache invalidation
const APP_VERSION = 'v8';

