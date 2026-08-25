// ================================================================
// IDEMPOTENT ACTIONS — global double-submit guard + loading spinner
// ================================================================
// Rather than touching every button/form in the app individually, this
// hooks the two lifecycle events almost everything already goes through:
// an HTMX request, or a native <form> submit. Both get the trigger element
// disabled (via the .is-loading CSS class in theme.css — a pure overlay,
// no innerHTML swapping, so it's safe on any button's internal markup)
// the instant the action starts, and re-enabled when it's done.
//
// Opt out on a specific element with data-allow-resubmit="true" (e.g. a
// live-filter input whose own hx-trigger fires repeatedly by design).
(function() {
    function isTriggerElement(el) {
        if (!el || el.nodeType !== 1) return false;
        var tag = el.tagName;
        return tag === 'BUTTON' || tag === 'A' ||
            (tag === 'INPUT' && ['submit', 'button'].indexOf(el.type) !== -1);
    }

    function startLoading(el) {
        if (!el || el.dataset.allowResubmit === 'true') return;
        el.classList.add('is-loading');
        if (el.tagName === 'BUTTON' || (el.tagName === 'INPUT' && el.type === 'submit')) {
            el.disabled = true;
        }
    }

    function stopLoading(el) {
        if (!el) return;
        el.classList.remove('is-loading');
        if (el.tagName === 'BUTTON' || (el.tagName === 'INPUT' && el.type === 'submit')) {
            el.disabled = false;
        }
    }

    // ---------------- HTMX-driven buttons/links/forms ----------------
    // htmx:beforeRequest/afterRequest bracket every hx-get/hx-post
    // regardless of what triggered it or where the response gets swapped,
    // and afterRequest always fires (success, error, or swap failure) so
    // there's no need for a timeout fallback here.
    document.body.addEventListener('htmx:beforeRequest', function(evt) {
        var elt = evt.detail.elt;
        if (isTriggerElement(elt)) startLoading(elt);
    });
    document.body.addEventListener('htmx:afterRequest', function(evt) {
        var elt = evt.detail.elt;
        if (elt && elt.isConnected) stopLoading(elt);
    });

    // ---------------- Plain <form> submits ----------------
    // Covers both a real browser navigation (page is unloading anyway, so
    // never needing to re-enable is correct) and a form whose own JS calls
    // preventDefault() and does its own fetch()/XHR — this listener still
    // sees the submit event either way (preventDefault doesn't stop other
    // listeners), so those forms get the same instant disable-on-click
    // protection even if their own handler doesn't manage a loading state.
    //
    // Unlike the htmx path, there's no shared "request finished" event for
    // an arbitrary fetch()/XHR a form's own script might run — so a form
    // that already re-enables its submit button itself (many do, via
    // `submitBtn.disabled = false` in a .then()/.finally()) would otherwise
    // leave the .is-loading spinner overlay stuck even after the button
    // becomes clickable again. A MutationObserver on the `disabled`
    // attribute clears .is-loading the moment *anything* flips it back to
    // false, so this composes correctly with existing per-form handlers
    // instead of fighting them. A timeout is still the last-resort
    // fallback, for forms with no such handler at all (or a buggy one).
    document.addEventListener('submit', function(evt) {
        var form = evt.target;
        if (!form || form.tagName !== 'FORM' || form.dataset.allowResubmit === 'true') return;
        // hx-post/hx-get forms are handled by the htmx path above.
        if (form.hasAttribute('hx-post') || form.hasAttribute('hx-get')) return;

        var trigger = form.querySelector('button[type="submit"], input[type="submit"]') ||
            form.querySelector('button:not([type="button"]):not([type="reset"])');
        if (!trigger || trigger.disabled) return;
        startLoading(trigger);

        var settled = false;
        var timeoutId = setTimeout(function() { finish(); }, 20000);
        var observer = new MutationObserver(function() {
            if (trigger.disabled === false) finish();
        });
        function finish() {
            if (settled) return;
            settled = true;
            clearTimeout(timeoutId);
            observer.disconnect();
            stopLoading(trigger);
        }
        observer.observe(trigger, { attributes: true, attributeFilter: ['disabled'] });
    }, true);

    // ---------------- Manual opt-in for custom fetch()/XHR buttons ----------------
    // A plain onclick handler calling fetch() directly (not a <form>, not
    // htmx) has no shared lifecycle event to hook — call these two
    // directly from that handler: window.startButtonLoading(btn) right
    // before the request, window.stopButtonLoading(btn) in .then()/.catch().
    window.startButtonLoading = startLoading;
    window.stopButtonLoading = stopLoading;
})();
