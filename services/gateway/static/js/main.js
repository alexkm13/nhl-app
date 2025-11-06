// Wait for all dependencies to be loaded before initializing
window.addEventListener('DOMContentLoaded', async function() {
    // Ensure all required functions are available
    if (typeof initDateSelector === 'undefined') {
        console.error('initDateSelector is not defined. Check dateSelector.js loading.');
        return;
    }
    if (typeof loadGamesList === 'undefined') {
        console.error('loadGamesList is not defined. Check api.js loading.');
        return;
    }
    if (typeof loadStandings === 'undefined') {
        console.error('loadStandings is not defined. Check api.js loading.');
        return;
    }
    
    initDateSelector();
    // Load games for today's date based on client's system date
    const today = new Date();
    await loadGamesList(today);
    await loadStandings();
});
