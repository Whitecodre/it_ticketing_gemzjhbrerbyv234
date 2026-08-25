// ================================================================
// SHARED DATE-RANGE FILTER — one Alpine component behind
// components/date_range_filter.html, reused by the Reports & Analytics
// dashboard and the generic report-export page (Incident Reports,
// Service Requests, Audit Logs, Maintenance, Assets, Users all share the
// one report_builder.html template already).
//
// Two apply strategies, since the two host pages already commit filters
// differently and neither is a view change we're allowed to make here:
//   'redirect' — navigates to the current URL with start/end query params
//                set (what dashboards/reports.html already did by hand).
//   'htmx'     — writes into the two hidden inputs identified by
//                startInputId/endInputId and fires a bubbling 'change' on
//                the end input, so the host form's existing
//                hx-trigger="change" (which already serializes every
//                other filter field) picks it up — no new HTMX wiring.
// ================================================================
document.addEventListener('alpine:init', function () {
    Alpine.data('dateRangeFilter', function (config) {
        return {
            presets: config.presets || [],
            applyMode: config.applyMode || 'redirect',
            startInputId: config.startInputId || null,
            endInputId: config.endInputId || null,
            redirectStartParam: config.redirectStartParam || 'start_date',
            redirectEndParam: config.redirectEndParam || 'end_date',
            start: config.start || '',
            end: config.end || '',
            activePresetDays: config.activePresetDays !== undefined ? config.activePresetDays : null,
            defaultStart: config.defaultStart || '',
            defaultEnd: config.defaultEnd || '',
            defaultPresetDays: config.defaultPresetDays !== undefined ? config.defaultPresetDays : null,

            popoverOpen: false,
            pickStage: 'start',
            pendingStart: null,
            viewMonth: null,
            _positionCleanup: null,

            init: function () {
                var base = this.start ? new Date(this.start + 'T00:00:00') : new Date();
                this.viewMonth = new Date(base.getFullYear(), base.getMonth(), 1);
            },

            get rangeLabel() {
                if (!this.start || !this.end) return 'Select date range';
                return this.formatShort(this.start) + ' – ' + this.formatShort(this.end);
            },

            formatShort: function (iso) {
                var d = new Date(iso + 'T00:00:00');
                return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
            },

            toISO: function (d) {
                var y = d.getFullYear();
                var m = String(d.getMonth() + 1).padStart(2, '0');
                var day = String(d.getDate()).padStart(2, '0');
                return y + '-' + m + '-' + day;
            },

            applyPreset: function (days) {
                var end = new Date();
                var start = new Date();
                if (days > 0) start.setDate(end.getDate() - days);
                this.start = this.toISO(start);
                this.end = this.toISO(end);
                this.activePresetDays = days;
                this.popoverOpen = false;
                this.commit();
            },

            openPopover: function () {
                this.pickStage = 'start';
                this.pendingStart = null;
                var base = this.start ? new Date(this.start + 'T00:00:00') : new Date();
                this.viewMonth = new Date(base.getFullYear(), base.getMonth(), 1);
                this.popoverOpen = true;
                // The popover is position:fixed (see theme.css .drf-popover) so it
                // isn't clipped by a .dashboard-card ancestor's overflow — computed
                // via the same shared helper the per-row action dropdowns use
                // (static/js/global.js), after Alpine has actually mounted it (x-show
                // toggling display off->on happens synchronously, but $nextTick makes
                // sure the browser has laid it out before we measure it).
                var self = this;
                this.$nextTick(function () {
                    if (window.positionDropdown && self.$refs.toggle && self.$refs.popover) {
                        self._positionCleanup = window.positionDropdown(self.$refs.toggle, self.$refs.popover, { align: 'right' });
                    }
                });
            },

            closePopover: function () {
                this.popoverOpen = false;
                if (this._positionCleanup) {
                    this._positionCleanup();
                    this._positionCleanup = null;
                }
            },

            prevMonth: function () {
                this.viewMonth = new Date(this.viewMonth.getFullYear(), this.viewMonth.getMonth() - 1, 1);
            },

            nextMonth: function () {
                this.viewMonth = new Date(this.viewMonth.getFullYear(), this.viewMonth.getMonth() + 1, 1);
            },

            monthLabel: function (offset) {
                var m = new Date(this.viewMonth.getFullYear(), this.viewMonth.getMonth() + offset, 1);
                return m.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
            },

            monthDays: function (offset) {
                var m = new Date(this.viewMonth.getFullYear(), this.viewMonth.getMonth() + offset, 1);
                var days = [];
                var firstWeekday = m.getDay();
                for (var i = 0; i < firstWeekday; i++) days.push(null);
                var daysInMonth = new Date(m.getFullYear(), m.getMonth() + 1, 0).getDate();
                for (var d = 1; d <= daysInMonth; d++) days.push(new Date(m.getFullYear(), m.getMonth(), d));
                return days;
            },

            pickDay: function (date) {
                if (!date) return;
                var iso = this.toISO(date);
                if (this.pickStage === 'start') {
                    this.pendingStart = iso;
                    this.pickStage = 'end';
                    return;
                }
                var s = this.pendingStart, e = iso;
                if (e < s) { var t = s; s = e; e = t; }
                this.start = s;
                this.end = e;
                this.activePresetDays = null;
                this.popoverOpen = false;
                this.commit();
            },

            dayClass: function (date) {
                if (!date) return '';
                var iso = this.toISO(date);
                if (this.pickStage === 'end' && this.pendingStart === iso) return 'drf-day-selected';
                if (iso === this.start || iso === this.end) return 'drf-day-selected';
                if (this.start && this.end && iso > this.start && iso < this.end) return 'drf-day-in-range';
                return '';
            },

            reset: function () {
                this.start = this.defaultStart;
                this.end = this.defaultEnd;
                this.activePresetDays = this.defaultPresetDays;
                this.popoverOpen = false;
                this.commit();
            },

            commit: function () {
                if (this.applyMode === 'redirect') {
                    var url = new URL(window.location.href);
                    if (this.start && this.end) {
                        url.searchParams.set(this.redirectStartParam, this.start);
                        url.searchParams.set(this.redirectEndParam, this.end);
                    } else {
                        url.searchParams.delete(this.redirectStartParam);
                        url.searchParams.delete(this.redirectEndParam);
                    }
                    window.location.href = url.toString();
                } else if (this.applyMode === 'htmx') {
                    var startEl = this.startInputId && document.getElementById(this.startInputId);
                    var endEl = this.endInputId && document.getElementById(this.endInputId);
                    if (startEl) startEl.value = this.start;
                    if (endEl) {
                        endEl.value = this.end;
                        endEl.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            },
        };
    });
});
