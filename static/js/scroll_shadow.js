// ================================================================
// Toggles .has-scroll-left / .has-scroll-right on every
// .table-scroll-shell based on its inner .overflow-x-auto scroll
// position, so the CSS edge-fade in theme.css only shows when there's
// actually more to scroll to. Re-binds after HTMX swaps (pagination,
// filters) since those replace the table markup wholesale.
// ================================================================
(function () {
    function updateShell(shell) {
        var scroller = shell.querySelector('.overflow-x-auto');
        if (!scroller) return;
        var atStart = scroller.scrollLeft <= 1;
        var atEnd = scroller.scrollLeft >= scroller.scrollWidth - scroller.clientWidth - 1;
        shell.classList.toggle('has-scroll-left', !atStart);
        shell.classList.toggle('has-scroll-right', !atEnd && scroller.scrollWidth > scroller.clientWidth);
    }

    function bindShell(shell) {
        if (shell.dataset.scrollShadowBound) return;
        shell.dataset.scrollShadowBound = '1';
        var scroller = shell.querySelector('.overflow-x-auto');
        if (!scroller) return;
        scroller.addEventListener('scroll', function () { updateShell(shell); });
        window.addEventListener('resize', function () { updateShell(shell); });
        updateShell(shell);
    }

    function bindAll() {
        document.querySelectorAll('.table-scroll-shell').forEach(bindShell);
    }

    document.addEventListener('DOMContentLoaded', bindAll);
    document.body.addEventListener('htmx:afterSwap', function (event) {
        event.target.querySelectorAll('.table-scroll-shell').forEach(function (shell) {
            delete shell.dataset.scrollShadowBound;
            bindShell(shell);
        });
    });
})();
