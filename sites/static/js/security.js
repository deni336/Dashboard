(function () {
    'use strict';

    const CHECK_STATUSES = new Set(['good', 'warning', 'critical']);
    const state = { overview: null, loading: false, generation: 0, pollTimer: null };

    function byId(id) { return document.getElementById(id); }
    function object(value) { return value && typeof value === 'object' && !Array.isArray(value) ? value : null; }

    function plain(value, maximum = 160) {
        if (typeof value !== 'string' && typeof value !== 'number') return '';
        return String(value).replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, maximum);
    }

    function safeDate(value) {
        if (typeof value !== 'string') return '';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? '' : date.toISOString();
    }

    function score(value) {
        return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100 ? value : null;
    }

    function nonnegative(value) {
        return Number.isSafeInteger(value) && value >= 0 ? Math.min(value, 1000000) : null;
    }

    function rate(value) {
        return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.min(value, Number.MAX_SAFE_INTEGER) : null;
    }

    function safeIdentifier(value) {
        return typeof value === 'string' && /^[A-Za-z][A-Za-z0-9._-]{0,95}$/.test(value) ? value : '';
    }

    function normalizeCheck(value) {
        const source = object(value);
        if (!source) return null;
        const id = safeIdentifier(source.id);
        const title = typeof source.title === 'string' ? plain(source.title, 140) : '';
        if (!id || !CHECK_STATUSES.has(source.status) || !title) return null;
        return Object.freeze({
            id,
            status: source.status,
            title,
            detail: plain(source.detail, 500),
            recommendation: plain(source.recommendation, 500),
        });
    }

    function summaryValue(source, key, parser = nonnegative) {
        return source && Object.hasOwn(source, key) ? parser(source[key]) : null;
    }

    function availability(value) {
        return value === 'available' ? 'available' : 'unavailable';
    }

    function agentCounts(value) {
        const source = object(value);
        return Object.freeze({
            total: summaryValue(source, 'total'),
            online: summaryValue(source, 'online'),
            stale: summaryValue(source, 'stale'),
            offline: summaryValue(source, 'offline'),
        });
    }

    function normalizeWorkstations(value) {
        const source = object(value);
        const agents = agentCounts(source?.agents);
        const network = object(source?.network);
        const warnings = object(source?.resource_warnings);
        const warningValues = {
            cpu: summaryValue(warnings, 'cpu'),
            memory: summaryValue(warnings, 'memory'),
            gpu: summaryValue(warnings, 'gpu'),
            disk: summaryValue(warnings, 'disk'),
        };
        const presentWarnings = Object.values(warningValues).filter(value => value !== null);
        return Object.freeze({
            source_status: availability(source?.status),
            total: agents.total,
            online: agents.online,
            stale: agents.stale,
            offline: agents.offline,
            total_network_received_bps: summaryValue(network, 'received_bps', rate),
            total_network_sent_bps: summaryValue(network, 'sent_bps', rate),
            resource_warnings: presentWarnings.length ? presentWarnings.reduce((total, value) => total + value, 0) : null,
            warning_breakdown: Object.freeze(warningValues),
        });
    }

    function normalizeHomelab(value) {
        const source = object(value);
        const agents = agentCounts(source?.agents);
        const containers = object(source?.containers);
        return Object.freeze({
            source_status: availability(source?.status),
            total: agents.total,
            online: agents.online,
            stale: agents.stale,
            offline: agents.offline,
            engines_unavailable: summaryValue(source, 'engines_unavailable'),
            containers_total: summaryValue(containers, 'total'),
            containers_running: summaryValue(containers, 'running'),
            containers_unhealthy: summaryValue(containers, 'unhealthy'),
            health_checks_down: summaryValue(source, 'health_checks_down'),
            updates_available: summaryValue(source, 'updates_available'),
        });
    }

    function normalizeLauncher(value) {
        const source = object(value);
        const agents = agentCounts(source?.agents);
        return Object.freeze({
            source_status: availability(source?.status),
            total: agents.total,
            online: agents.online,
            stale: agents.stale,
            offline: agents.offline,
        });
    }

    function normalizeSources(value) {
        const source = object(value);
        const workstations = normalizeWorkstations(source?.workstation);
        const homelab = normalizeHomelab(source?.homelab);
        const launcher = normalizeLauncher(source?.launcher);
        const coverage = Object.freeze([
            Object.freeze({ id: 'workstation', label: 'Workstations', status: workstations.source_status === 'available' ? 'good' : 'unavailable' }),
            Object.freeze({ id: 'homelab', label: 'Docker & Homelab', status: homelab.source_status === 'available' ? 'good' : 'unavailable' }),
            Object.freeze({ id: 'launcher', label: 'Task runners', status: launcher.source_status === 'available' ? 'good' : 'unavailable' }),
        ]);
        const errors = Object.freeze(coverage.filter(item => item.status === 'unavailable').map(item => Object.freeze({
            source: item.id,
            message: `${item.label} posture data is currently unavailable.`,
        })));
        return Object.freeze({ workstations, homelab, launcher, coverage, errors });
    }

    function normalizeOverview(payload) {
        const source = object(payload);
        if (!source) throw new Error('Kasugai returned an invalid security overview.');
        const postureScore = score(source.score);
        const sources = normalizeSources(source.sources);
        return Object.freeze({
            generated_at: safeDate(source.generated_at),
            score: postureScore,
            grade: plain(source.grade, 32),
            status: postureScore === null ? 'unknown' : postureScore >= 85 ? 'good' : postureScore >= 60 ? 'warning' : 'critical',
            checks: Object.freeze((Array.isArray(source.checks) ? source.checks : []).slice(0, 128).map(normalizeCheck).filter(Boolean)),
            sources: sources.coverage,
            errors: sources.errors,
            workstations: sources.workstations,
            homelab: sources.homelab,
            launcher: sources.launcher,
        });
    }

    function capitalize(value) {
        const text = plain(value, 96).replaceAll('_', ' ').replaceAll('.', ' ');
        return text ? `${text.charAt(0).toLocaleUpperCase()}${text.slice(1)}` : '';
    }

    function formatTime(value) {
        const date = new Date(String(value || ''));
        if (Number.isNaN(date.getTime())) return 'Generation time unavailable';
        return new Intl.DateTimeFormat(undefined, {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit',
        }).format(date);
    }

    function formatRate(value) {
        if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '\u2014';
        if (value === 0) return '0 B/s';
        const units = ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s'];
        const power = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
        const scaled = value / (1024 ** power);
        return `${scaled >= 100 || power === 0 ? Math.round(scaled) : scaled.toFixed(1)} ${units[power]}`;
    }

    function displayCount(value) { return value === null ? '\u2014' : String(value); }

    function icon(name) {
        const element = document.createElement('i');
        element.setAttribute('data-lucide', name);
        element.setAttribute('aria-hidden', 'true');
        return element;
    }

    function refreshIcons() { if (window.lucide) window.lucide.createIcons(); }

    async function responseJson(response) {
        if (response.redirected || response.status === 401) throw new Error('Your session expired. Sign in again.');
        let payload;
        try { payload = await response.json(); }
        catch (_error) { throw new Error('Kasugai returned an invalid security response.'); }
        if (!response.ok) throw new Error(plain(payload?.error, 240) || 'Kasugai could not load the security overview.');
        return payload;
    }

    async function api() {
        return responseJson(await fetch('/api/security/overview', {
            method: 'GET',
            headers: { Accept: 'application/json' },
            credentials: 'same-origin',
            cache: 'no-store',
            redirect: 'error',
        }));
    }

    function stateStatus(summary, warningValue = null, criticalValue = null) {
        if (summary.source_status === 'unavailable') return 'unknown';
        if (criticalValue !== null && criticalValue > 0) return 'critical';
        if ((summary.offline !== null && summary.offline > 0) || (warningValue !== null && warningValue > 0) || (summary.stale !== null && summary.stale > 0)) return 'warning';
        if (summary.online !== null && summary.online > 0) return 'good';
        return 'unknown';
    }

    function setStateLabel(id, status) {
        const element = byId(id);
        element.textContent = status === 'good' ? 'Healthy' : status === 'warning' ? 'Attention' : status === 'critical' ? 'At risk' : 'No data';
        element.classList.remove('is-good', 'is-warning', 'is-critical');
        if (CHECK_STATUSES.has(status)) element.classList.add(`is-${status}`);
    }

    function countCard(label, value, kind) {
        const card = document.createElement('div');
        card.className = `security-state-count${kind ? ` is-${kind}` : ''}`;
        const number = document.createElement('strong');
        number.textContent = displayCount(value);
        const caption = document.createElement('span');
        caption.textContent = label;
        card.append(number, caption);
        return card;
    }

    function renderStateCounts(id, summary) {
        const container = byId(id);
        container.replaceChildren(
            countCard('Online', summary.online, ''),
            countCard('Stale', summary.stale, 'stale'),
            countCard('Offline', summary.offline, 'offline'),
        );
    }

    function detailRow(label, value, kind = '') {
        const row = document.createElement('div');
        const term = document.createElement('dt');
        term.textContent = label;
        const detail = document.createElement('dd');
        detail.textContent = value;
        if (kind) detail.className = `is-${kind}`;
        row.append(term, detail);
        return row;
    }

    function renderHealth(overview) {
        const workstation = overview.workstations;
        renderStateCounts('securityWorkstationCounts', workstation);
        const workstationStatus = stateStatus(workstation, workstation.resource_warnings);
        setStateLabel('securityWorkstationsState', workstationStatus);
        byId('securityWorkstationDetails').replaceChildren(
            detailRow('Inbound throughput', formatRate(workstation.total_network_received_bps)),
            detailRow('Outbound throughput', formatRate(workstation.total_network_sent_bps)),
            detailRow('Resource warnings', displayCount(workstation.resource_warnings), workstation.resource_warnings > 0 ? 'warning' : ''),
        );

        const homelab = overview.homelab;
        renderStateCounts('securityHomelabCounts', homelab);
        const critical = (homelab.engines_unavailable || 0) + (homelab.containers_unhealthy || 0) + (homelab.health_checks_down || 0);
        const homelabStatus = stateStatus(homelab, homelab.updates_available, critical);
        setStateLabel('securityHomelabState', homelabStatus);
        const containers = homelab.containers_running === null || homelab.containers_total === null ? '—' : `${homelab.containers_running} / ${homelab.containers_total}`;
        byId('securityHomelabDetails').replaceChildren(
            detailRow('Containers running', containers, (homelab.containers_unhealthy || 0) > 0 ? 'critical' : ''),
            detailRow('Unhealthy / checks down', homelab.containers_unhealthy === null || homelab.health_checks_down === null ? '—' : `${homelab.containers_unhealthy} / ${homelab.health_checks_down}`, critical > 0 ? 'critical' : ''),
            detailRow('Engines unavailable', displayCount(homelab.engines_unavailable), (homelab.engines_unavailable || 0) > 0 ? 'critical' : ''),
            detailRow('Updates available', displayCount(homelab.updates_available), (homelab.updates_available || 0) > 0 ? 'warning' : ''),
        );

        const launcher = overview.launcher;
        renderStateCounts('securityLauncherCounts', launcher);
        setStateLabel('securityLauncherState', stateStatus(launcher));
    }

    function postureCopy(status) {
        if (status === 'good') return 'Passive signals and configuration checks show a healthy posture.';
        if (status === 'warning') return 'The posture is generally stable, with recommendations worth reviewing.';
        if (status === 'critical') return 'One or more high-impact posture gaps need attention.';
        return 'Not enough passive signal is available to calculate a posture.';
    }

    function derivedGrade(value) {
        if (value === null) return 'Insufficient data';
        if (value >= 90) return 'Grade A';
        if (value >= 80) return 'Grade B';
        if (value >= 70) return 'Grade C';
        if (value >= 60) return 'Grade D';
        return 'Needs attention';
    }

    function renderScore(overview) {
        const ring = byId('securityScoreRing');
        const value = overview.score;
        ring.style.setProperty('--security-score-angle', `${value === null ? 0 : value * 3.6}deg`);
        ring.classList.remove('is-good', 'is-warning', 'is-critical');
        if (CHECK_STATUSES.has(overview.status)) ring.classList.add(`is-${overview.status}`);
        ring.setAttribute('aria-valuenow', String(value === null ? 0 : value));
        ring.setAttribute('aria-valuetext', value === null ? 'Security posture score unavailable' : `${Math.round(value)} out of 100`);
        byId('securityScore').textContent = value === null ? '--' : String(Math.round(value));
        byId('securityGrade').textContent = overview.grade || derivedGrade(value);
        byId('securityScoreSummary').textContent = postureCopy(overview.status);
        byId('securityGeneratedAt').textContent = overview.generated_at ? `Generated ${formatTime(overview.generated_at)}` : 'Generation time unavailable';
        const status = byId('securityStatus');
        status.textContent = overview.status === 'good' ? 'Healthy' : overview.status === 'warning' ? 'Review advised' : overview.status === 'critical' ? 'Attention needed' : 'Insufficient data';
        status.classList.remove('is-ok', 'is-warning', 'is-error');
        if (overview.status === 'good') status.classList.add('is-ok');
        else if (overview.status === 'warning') status.classList.add('is-warning');
        else if (overview.status === 'critical') status.classList.add('is-error');
    }

    function checkCard(check) {
        const card = document.createElement('article');
        card.className = `security-check-card is-${check.status}`;
        const iconBox = document.createElement('span');
        iconBox.className = 'security-check-icon';
        iconBox.appendChild(icon(check.status === 'good' ? 'shield-check' : check.status === 'warning' ? 'shield-alert' : 'shield-x'));
        const copy = document.createElement('div');
        copy.className = 'security-check-copy';
        const heading = document.createElement('div');
        heading.className = 'security-check-title';
        const title = document.createElement('strong');
        title.textContent = check.title;
        const status = document.createElement('span');
        status.textContent = check.status;
        heading.append(title, status);
        const detail = document.createElement('p');
        detail.textContent = check.detail || 'No additional detail was reported.';
        copy.append(heading, detail);
        if (check.recommendation) {
            const recommendation = document.createElement('div');
            recommendation.className = 'security-check-recommendation';
            recommendation.appendChild(icon('lightbulb'));
            const text = document.createElement('span');
            text.textContent = check.recommendation;
            recommendation.appendChild(text);
            copy.appendChild(recommendation);
        }
        card.append(iconBox, copy);
        return card;
    }

    function renderChecks(checks) {
        const container = byId('securityCheckGrid');
        container.replaceChildren();
        container.setAttribute('aria-busy', 'false');
        const totals = { good: 0, warning: 0, critical: 0 };
        checks.forEach(check => { totals[check.status] += 1; container.appendChild(checkCard(check)); });
        const counts = byId('securityCheckCounts');
        counts.replaceChildren();
        Object.entries(totals).forEach(([status, value]) => {
            const badge = document.createElement('span');
            badge.className = `is-${status}`;
            badge.textContent = `${value} ${status}`;
            counts.appendChild(badge);
        });
        if (!checks.length) {
            const empty = document.createElement('div');
            empty.className = 'security-check-empty';
            empty.appendChild(icon('shield-question'));
            const title = document.createElement('strong');
            title.textContent = 'No configuration checks reported';
            const detail = document.createElement('p');
            detail.textContent = 'Connect supported agents and refresh to expand passive posture coverage.';
            empty.append(title, detail);
            container.appendChild(empty);
        }
        refreshIcons();
    }

    function renderCoverage(overview) {
        const sources = overview.sources;
        const container = byId('securitySourceList');
        container.replaceChildren();
        sources.forEach(source => {
            const row = document.createElement('div');
            row.className = 'security-source-row';
            const dot = document.createElement('span');
            dot.className = `security-source-dot${CHECK_STATUSES.has(source.status) ? ` is-${source.status}` : ''}`;
            const title = document.createElement('strong');
            title.textContent = source.label;
            const status = document.createElement('span');
            status.textContent = source.status;
            row.append(dot, title, status);
            container.appendChild(row);
        });
        const disclosure = byId('securityErrorDisclosure');
        const list = byId('securityErrorList');
        disclosure.hidden = overview.errors.length === 0;
        list.replaceChildren();
        overview.errors.forEach(error => {
            const item = document.createElement('div');
            item.className = 'security-error-item';
            const title = document.createElement('strong');
            title.textContent = capitalize(error.source);
            const message = document.createElement('p');
            message.textContent = error.message;
            item.append(title, message);
            list.appendChild(item);
        });
        byId('securityErrorSummary').textContent = `${overview.errors.length} collection issue${overview.errors.length === 1 ? '' : 's'}`;
        const coverage = byId('securityCoverageStatus');
        coverage.textContent = overview.errors.length ? `${overview.errors.length} issue${overview.errors.length === 1 ? '' : 's'}` : 'Complete';
        coverage.classList.remove('is-ok', 'is-warning', 'is-error');
        coverage.classList.add(overview.errors.length ? 'is-warning' : 'is-ok');
        refreshIcons();
    }

    function renderOverview(overview) {
        renderScore(overview);
        renderHealth(overview);
        renderChecks(overview.checks);
        renderCoverage(overview);
    }

    async function loadOverview() {
        if (state.loading) return;
        state.loading = true;
        const generation = ++state.generation;
        const button = byId('refreshSecurity');
        if (button) button.disabled = true;
        byId('securityCheckGrid')?.setAttribute('aria-busy', 'true');
        try {
            const overview = normalizeOverview(await api());
            if (generation !== state.generation) return;
            state.overview = overview;
            renderOverview(overview);
            const feedback = byId('securityFeedback');
            feedback.textContent = '';
            feedback.classList.remove('error');
        } catch (error) {
            if (generation !== state.generation) return;
            byId('securityCheckGrid')?.setAttribute('aria-busy', 'false');
            const status = byId('securityStatus');
            status.textContent = 'Unavailable';
            status.classList.remove('is-ok', 'is-warning');
            status.classList.add('is-error');
            const feedback = byId('securityFeedback');
            feedback.textContent = error.message;
            feedback.classList.add('error');
            feedback.setAttribute('role', 'alert');
        } finally {
            state.loading = false;
            if (button) button.disabled = false;
        }
    }

    function initialize() {
        if (!byId('securityModule')) return;
        byId('refreshSecurity')?.addEventListener('click', loadOverview);
        document.addEventListener('visibilitychange', () => { if (!document.hidden) loadOverview(); });
        state.pollTimer = window.setInterval(() => { if (!document.hidden) loadOverview(); }, 30000);
        loadOverview();
    }

    if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initialize);
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            formatRate,
            normalizeCheck,
            normalizeHomelab,
            normalizeLauncher,
            normalizeOverview,
            normalizeSources,
            normalizeWorkstations,
        };
    }
})();
