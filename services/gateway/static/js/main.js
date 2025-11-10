// Wait for all dependencies to be loaded before initializing
window.addEventListener('DOMContentLoaded', async function() {
    // Wait a bit for scripts to load, then check for required functions
    // This handles cases where scripts load asynchronously
    let retries = 0;
    const maxRetries = 10;
    
    function checkDependencies() {
        if (typeof initDateSelector === 'undefined' || 
            typeof loadGamesList === 'undefined' || 
            typeof loadStandings === 'undefined') {
            retries++;
            if (retries < maxRetries) {
                setTimeout(checkDependencies, 100);
                return;
            }
            // After max retries, log errors but don't block
            if (typeof initDateSelector === 'undefined') {
                console.error('initDateSelector is not defined. Check dateSelector.js loading.');
            }
            if (typeof loadGamesList === 'undefined') {
                console.error('loadGamesList is not defined. Check api.js loading.');
                return;
            }
            if (typeof loadStandings === 'undefined') {
                console.error('loadStandings is not defined. Check api.js loading.');
            }
            return;
        }
        
        // All dependencies are available, proceed
        initDateSelector();
        // Load games for today's date based on client's system date
        const today = new Date();
        loadGamesList(today).catch(err => {
            console.error('Error loading games list:', err);
        });
        loadStandings().catch(err => {
            console.error('Error loading standings:', err);
        });
    }
    
    checkDependencies();
});
