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

