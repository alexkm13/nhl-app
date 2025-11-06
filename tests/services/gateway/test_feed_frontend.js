/**
 * JavaScript tests for frontend feed rendering.
 * These tests can be run with Node.js and a test framework like Jest or Mocha.
 */

// Mock DOM environment
if (typeof document === 'undefined') {
    global.document = {
        querySelector: jest.fn(),
        getElementById: jest.fn(() => ({
            innerHTML: '',
            scrollTop: 0,
        })),
    };
    global.window = {};
    global.console = {
        log: jest.fn(),
        error: jest.fn(),
        warn: jest.fn(),
    };
}

// Sample feed rendering logic (extracted for testing)
function validateFeedEvent(event) {
    const requiredFields = ['event_type', 'period', 'team'];
    return requiredFields.every(field => field in event);
}

function filterCrucialEvents(events) {
    const crucialTypes = ['GOAL', 'PENALTY'];
    return events.filter(e => crucialTypes.includes(e.event_type));
}

function deduplicateEvents(events) {
    const seenIds = new Set();
    const uniqueEvents = [];
    
    for (const event of events) {
        const eventId = event.id;
        if (eventId && !seenIds.has(eventId)) {
            seenIds.add(eventId);
            uniqueEvents.push(event);
        } else if (!eventId) {
            // Create dedup key for events without ID
            const dedupKey = `${event.timestamp}-${event.event_type}-${event.player_id}-${event.period}-${event.time_in_period}`;
            if (!seenIds.has(dedupKey)) {
                seenIds.add(dedupKey);
                event.id = `event-${uniqueEvents.length}`;
                uniqueEvents.push(event);
            }
        }
    }
    
    return uniqueEvents;
}

function sortEventsByTimestamp(events) {
    return events.sort((a, b) => {
        const tsA = a.timestamp || 0;
        const tsB = b.timestamp || 0;
        if (tsB !== tsA) {
            return tsB - tsA; // Descending (most recent first)
        }
        const idA = a.id || '';
        const idB = b.id || '';
        return idB.localeCompare(idA);
    });
}

// Tests
describe('Feed Event Processing', () => {
    test('should validate event structure', () => {
        const validEvent = {
            id: 'event-1',
            event_type: 'GOAL',
            period: 1,
            team: 'HOME',
        };
        
        expect(validateFeedEvent(validEvent)).toBe(true);
    });
    
    test('should reject invalid event structure', () => {
        const invalidEvent = {
            id: 'event-1',
            // Missing required fields
        };
        
        expect(validateFeedEvent(invalidEvent)).toBe(false);
    });
    
    test('should filter crucial events', () => {
        const events = [
            { event_type: 'GOAL', period: 1 },
            { event_type: 'SHOT', period: 1 },
            { event_type: 'PENALTY', period: 1 },
            { event_type: 'FACEOFF', period: 1 },
        ];
        
        const crucial = filterCrucialEvents(events);
        
        expect(crucial.length).toBe(2);
        expect(crucial.every(e => ['GOAL', 'PENALTY'].includes(e.event_type))).toBe(true);
    });
    
    test('should deduplicate events', () => {
        const events = [
            { id: 'event-1', event_type: 'GOAL' },
            { id: 'event-1', event_type: 'GOAL' }, // Duplicate
            { id: 'event-2', event_type: 'GOAL' },
        ];
        
        const unique = deduplicateEvents(events);
        
        expect(unique.length).toBe(2);
        expect(unique.map(e => e.id)).toEqual(['event-1', 'event-2']);
    });
    
    test('should handle events without IDs', () => {
        const events = [
            { event_type: 'GOAL', timestamp: 100, period: 1 },
            { event_type: 'GOAL', timestamp: 100, period: 1 }, // Duplicate
            { event_type: 'GOAL', timestamp: 200, period: 1 },
        ];
        
        const unique = deduplicateEvents(events);
        
        expect(unique.length).toBe(2);
        expect(unique.every(e => e.id)).toBe(true);
    });
    
    test('should sort events by timestamp descending', () => {
        const events = [
            { timestamp: 100, event_type: 'GOAL' },
            { timestamp: 50, event_type: 'GOAL' },
            { timestamp: 150, event_type: 'GOAL' },
        ];
        
        const sorted = sortEventsByTimestamp(events);
        
        expect(sorted[0].timestamp).toBe(150);
        expect(sorted[1].timestamp).toBe(100);
        expect(sorted[2].timestamp).toBe(50);
    });
    
    test('should handle events with same timestamp', () => {
        const events = [
            { id: 'event-b', timestamp: 100, event_type: 'GOAL' },
            { id: 'event-a', timestamp: 100, event_type: 'GOAL' },
        ];
        
        const sorted = sortEventsByTimestamp(events);
        
        // Should use ID as tiebreaker
        expect(sorted[0].id).toBe('event-b');
        expect(sorted[1].id).toBe('event-a');
    });
});

// Export for use in test runners
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        validateFeedEvent,
        filterCrucialEvents,
        deduplicateEvents,
        sortEventsByTimestamp,
    };
}

