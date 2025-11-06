function initDateSelector() {
    const dateSelector = document.getElementById('dateSelector');
    if (!dateSelector) {
        console.error('Date selector element not found');
        return;
    }
    
    // Clear any existing dates
    dateSelector.innerHTML = '';
    
    const today = new Date();
    const dates = [];
    
    // Show enough dates to fill the top bar (approximately 3 weeks: 10 days back, today, 10 days forward)
    console.log(`[CACHE-BUST v8] Starting date generation. Today: ${today.toLocaleDateString()}`);
    console.log(`[CACHE-BUST v8] Loop will run from -10 to +10 (21 iterations)`);
    
    // Create 21 dates: 10 days back, today, 10 days forward
    for (let i = -10; i <= 10; i++) {
        const date = new Date(today);
        date.setDate(today.getDate() + i);
        dates.push(date);
        console.log(`[CACHE-BUST v8] Loop iteration ${i}: Created date ${date.toLocaleDateString()}`);
    }
    
    console.log(`[CACHE-BUST v8] Total dates created: ${dates.length} (should be 21)`);
    if (dates.length !== 21) {
        console.error(`[CACHE-BUST v8] ERROR: Expected 21 dates but got ${dates.length}!`);
    }

    dates.forEach((date, index) => {
        const dateItem = document.createElement('div');
        dateItem.className = 'date-item';
        
        const month = date.toLocaleDateString('en-US', { month: 'short' });
        const day = date.getDate();
        const dayName = date.toLocaleDateString('en-US', { weekday: 'short' });
        
        const dateTop = document.createElement('div');
        dateTop.className = 'date-top';
        dateTop.textContent = `${month} ${day}`;
        
        const dateBottom = document.createElement('div');
        dateBottom.className = 'date-bottom';
        dateBottom.textContent = dayName;
        
        dateItem.appendChild(dateTop);
        dateItem.appendChild(dateBottom);
        
        dateItem.onclick = () => {
            document.querySelectorAll('.date-item').forEach(item => item.classList.remove('active'));
            dateItem.classList.add('active');
            // Switch back to games list view when clicking a date
            showGamesList();
            loadGamesList(date);
        };
        
        // Mark today as active (index 10 when range is -10 to +10)
        if (index === 10) {
            dateItem.classList.add('active');
        }
        
        dateSelector.appendChild(dateItem);
        console.log(`Added date ${index + 1}/${dates.length}: ${month} ${day}, ${dayName}`);
    });
    
    console.log(`Date selector initialized with ${dates.length} dates. Total date items in DOM: ${dateSelector.children.length}`);
    console.log(`Date selector width: ${dateSelector.offsetWidth}px, scrollWidth: ${dateSelector.scrollWidth}px`);
    
    // Ensure the date selector can scroll to show all dates
    if (dateSelector.scrollWidth > dateSelector.offsetWidth) {
        console.log(`Date selector is scrollable (${dateSelector.scrollWidth}px > ${dateSelector.offsetWidth}px)`);
        // Force the date selector to show all content
        dateSelector.style.minWidth = `${dateSelector.scrollWidth}px`;
    }
    
    // Verify all dates are in the DOM
    const allDateItems = dateSelector.querySelectorAll('.date-item');
    console.log(`Found ${allDateItems.length} date items in DOM`);
    if (allDateItems.length !== dates.length) {
        console.error(`Mismatch: Expected ${dates.length} dates but found ${allDateItems.length} in DOM`);
    }
}

// Helper function to format date as YYYY-MM-DD in local time

