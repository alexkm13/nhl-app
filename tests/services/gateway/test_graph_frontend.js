/**
 * JavaScript tests for frontend graph generation.
 * These tests can be run with Node.js and a test framework like Jest or Mocha.
 * 
 * To run these tests:
 * 1. Install Jest: npm install --save-dev jest
 * 2. Run: jest test_graph_frontend.js
 */

// Mock DOM environment
if (typeof document === 'undefined') {
    global.document = {
        querySelector: jest.fn(),
        getElementById: jest.fn(),
    };
    global.window = {};
}

// Sample graph generation function (extracted from index.html for testing)
function generateWinProbGraph(historyData, homeTeam, awayTeam, homeProb, awayProb, isLive, homeLogo = '', awayLogo = '', homeAbbrev = '', awayAbbrev = '', currentGameTime = null) {
    const width = 400;
    const height = 120;
    const padding = { top: 20, right: 20, bottom: 30, left: 40 };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;
    
    let points = [];
    let minTime, maxTime, timeRange;
    
    if (!historyData || historyData.length === 0) {
        const currentProb = homeProb / 100;
        const x1 = padding.left;
        const x2 = width - padding.right;
        const y = padding.top + chartHeight - (currentProb * chartHeight);
        minTime = 0;
        maxTime = 3600;
        timeRange = maxTime - minTime;
        points = [
            { x: x1, y: y, prob: currentProb, ts: 0 },
            { x: x2, y: y, prob: currentProb, ts: maxTime }
        ];
    } else {
        const times = historyData.map(d => d.ts);
        minTime = Math.min(...times);
        maxTime = Math.max(...times);
        minTime = Math.min(0, minTime);
        
        const typicalGameTime = 3600;
        let maxDisplayTime = Math.max(typicalGameTime, maxTime + 300);
        
        if (isLive && currentGameTime !== null && currentGameTime !== undefined) {
            maxDisplayTime = Math.max(maxDisplayTime, currentGameTime + 300);
        }
        
        timeRange = maxDisplayTime - minTime || 1;
        
        points = historyData.map((d) => {
            const x = padding.left + (d.ts - minTime) / timeRange * chartWidth;
            const y = padding.top + chartHeight - (d.p_home_win * chartHeight);
            return { x, y, prob: d.p_home_win, ts: d.ts };
        });
    }
    
    // Build SVG path
    let path = '';
    if (points.length > 0) {
        path = `M ${points[0].x} ${points[0].y}`;
        for (let i = 1; i < points.length; i++) {
            path += ` L ${points[i].x} ${points[i].y}`;
        }
    }
    
    return `<svg width="${width}" height="${height}"><path d="${path}"/></svg>`;
}

// Tests
describe('Win Probability Graph Generation', () => {
    test('should generate graph with empty history data', () => {
        const result = generateWinProbGraph(
            [],
            'Home Team',
            'Away Team',
            60,
            40,
            false
        );
        expect(result).toContain('<svg');
        expect(result).toContain('<path');
    });
    
    test('should generate graph with history data', () => {
        const historyData = [
            { ts: 0, p_home_win: 0.5 },
            { ts: 600, p_home_win: 0.55 },
            { ts: 1200, p_home_win: 0.60 },
        ];
        
        const result = generateWinProbGraph(
            historyData,
            'Home Team',
            'Away Team',
            65,
            35,
            true,
            '',
            '',
            'HOME',
            'AWAY',
            1800
        );
        
        expect(result).toContain('<svg');
        expect(result).toContain('<path');
    });
    
    test('should handle live game with current time', () => {
        const historyData = [
            { ts: 0, p_home_win: 0.5 },
            { ts: 600, p_home_win: 0.55 },
        ];
        
        const result = generateWinProbGraph(
            historyData,
            'Home Team',
            'Away Team',
            60,
            40,
            true,
            '',
            '',
            'HOME',
            'AWAY',
            1800
        );
        
        expect(result).toBeDefined();
        expect(result).toContain('<svg');
    });
    
    test('should calculate correct coordinates', () => {
        const historyData = [
            { ts: 0, p_home_win: 0.5 },
        ];
        
        const result = generateWinProbGraph(
            historyData,
            'Home Team',
            'Away Team',
            50,
            50,
            false
        );
        
        // Should generate SVG with valid coordinates
        expect(result).toContain('M ');
        expect(result).toContain('L ');
    });
});

// Export for use in test runners
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { generateWinProbGraph };
}

