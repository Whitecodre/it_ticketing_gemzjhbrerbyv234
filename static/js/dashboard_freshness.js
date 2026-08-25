// Ticks "Updated Xs/m ago" freshness indicators on dashboards so a stale
// page is visibly stale instead of looking identical to a fresh one.
(function() {
    function formatAge(seconds) {
        if (seconds < 5) return 'Updated just now';
        if (seconds < 60) return 'Updated ' + seconds + 's ago';
        var minutes = Math.floor(seconds / 60);
        if (minutes < 60) return 'Updated ' + minutes + 'm ago';
        var hours = Math.floor(minutes / 60);
        return 'Updated ' + hours + 'h ago';
    }

    function tick() {
        document.querySelectorAll('[data-freshness-since]').forEach(function(el) {
            var sinceSeconds = parseInt(el.getAttribute('data-freshness-since'), 10);
            if (!sinceSeconds) return;
            var textEl = el.querySelector('[data-freshness-text]') || el;
            var ageSeconds = Math.max(0, Math.floor(Date.now() / 1000) - sinceSeconds);
            textEl.textContent = formatAge(ageSeconds);
            el.title = 'Page data loaded at ' + new Date(sinceSeconds * 1000).toLocaleTimeString();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', tick);
    } else {
        tick();
    }
    setInterval(tick, 15000);
})();
