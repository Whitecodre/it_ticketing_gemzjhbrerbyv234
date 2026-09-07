// static/js/settings_hub.js
// Client-side search for the System Settings hub landing page (templates/
// dashboards/system_settings.html) — filters category cards by label as you
// type, and hides a whole group section once none of its cards match.
// Purely client-side since there are only a handful of settings resources;
// not worth a server round-trip. Mirrors report_hub.js's pattern.
document.addEventListener('DOMContentLoaded', function() {
    const input = document.getElementById('settingsHubSearch');
    if (!input) return;

    const cards = Array.from(document.querySelectorAll('[data-settings-card]'));
    const sections = Array.from(document.querySelectorAll('[data-settings-group]'));
    const noResults = document.getElementById('settingsHubNoResults');
    const noResultsQuery = document.getElementById('settingsHubNoResultsQuery');

    function applyFilter() {
        const query = input.value.trim().toLowerCase();
        let anyVisible = false;

        cards.forEach(function(card) {
            const matches = !query || card.dataset.searchText.includes(query);
            card.hidden = !matches;
            if (matches) anyVisible = true;
        });

        sections.forEach(function(section) {
            const hasVisibleCard = section.querySelector('[data-settings-card]:not([hidden])');
            section.hidden = !hasVisibleCard;
        });

        if (noResults) {
            noResults.classList.toggle('hidden', anyVisible || !query);
            if (noResultsQuery) noResultsQuery.textContent = query;
        }
    }

    input.addEventListener('input', applyFilter);
});
