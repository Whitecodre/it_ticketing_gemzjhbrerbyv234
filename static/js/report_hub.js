// static/js/report_hub.js
// Client-side search for the Reports Hub landing page (templates/dashboards/
// report_hub.html) — filters report cards by label/description/category as
// you type, and hides a whole category section once none of its cards
// match. Purely client-side since there are only a couple dozen report
// types at most; not worth a server round-trip.
document.addEventListener('DOMContentLoaded', function() {
    const input = document.getElementById('reportHubSearch');
    if (!input) return;

    const cards = Array.from(document.querySelectorAll('[data-report-card]'));
    const sections = Array.from(document.querySelectorAll('[data-category-section]'));
    const noResults = document.getElementById('reportHubNoResults');
    const noResultsQuery = document.getElementById('reportHubNoResultsQuery');

    function applyFilter() {
        const query = input.value.trim().toLowerCase();
        let anyVisible = false;

        cards.forEach(function(card) {
            const matches = !query || card.dataset.searchText.includes(query);
            card.hidden = !matches;
            if (matches) anyVisible = true;
        });

        sections.forEach(function(section) {
            const hasVisibleCard = section.querySelector('[data-report-card]:not([hidden])');
            section.hidden = !hasVisibleCard;
        });

        if (noResults) {
            noResults.classList.toggle('hidden', anyVisible || !query);
            if (noResultsQuery) noResultsQuery.textContent = query;
        }
    }

    input.addEventListener('input', applyFilter);
});
