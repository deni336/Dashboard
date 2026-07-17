(function () {
    'use strict';

    const state = {
        workstations: [],
        selectedId: '',
        pollTimer: null,
        generation: 0,
        loading: false,
    };

    function byId(id) {
        return document.getElementById(id);
    }

    function finite(value, fallback = null) {
        if (value === null || value === undefined || value === '') return fallback;
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function clampPercent(value) {
        return Math.max(0, Math.min(100, finite(value, 0)));
    }

    function formatPercent(value) {
        const parsed = finite(value);
        return parsed === null ? '—' : `${Math.round(clampPercent(parsed))}%`;
    }

    function formatBytes(value) {
        const parsed = finite(value);
        if (parsed === null || parsed < 0) return '—';
        if (parsed === 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
        const power = Math.min(units.length - 1, Math.floor(Math.log(parsed) / Math.log(1024)));
        const scaled = parsed / (1024 ** power);
        return `${scaled >= 100 || power === 0 ? Math.round(scaled) : scaled.toFixed(1)} ${units[power]}`;
    }

    function formatRate(value) {
        const formatted = formatBytes(value);
        return formatted === '—' ? formatted : `${formatted}/s`;
    }

    function formatDuration(value) {
        let seconds = Math.max(0, Math.floor(finite(value, 0)));
        const days = Math.floor(seconds / 86400);
        seconds %= 86400;
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        if (days) return `${days}d ${hours}h`;
        if (hours) return `${hours}h ${minutes}m`;
        return `${minutes}m`;
    }

    function formatTime(value) {
        const date = new Date(String(value || ''));
        if (Number.isNaN(date.getTime())) return '—';
        return new Intl.DateTimeFormat(undefined, {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit',
        }).format(date);
    }

    async function responseJson(response) {
        if (response.redirected || response.status === 401) throw new Error('Your session expired. Sign in again.');
        if (response.status === 204) {
            if (!response.ok) throw new Error('Kasugai could not complete that request.');
            return null;
        }
        let payload;
        try {
            payload = await response.json();
        } catch (_error) {
            throw new Error('Kasugai returned an invalid workstation response.');
        }
        if (!response.ok) throw new Error(payload?.error || 'Kasugai could not complete that request.');
        return payload;
    }

    async function api(url, options = {}) {
        const method = String(options.method || 'GET').toUpperCase();
        const headers = { Accept: 'application/json', ...(options.headers || {}) };
        let body = options.body;
        if (!['GET', 'HEAD'].includes(method)) {
            const token = String(window.KASUGAI_CSRF_TOKEN || '');
            if (!token) throw new Error('Reload this page before changing workstation settings.');
            headers['Content-Type'] = 'application/json';
            headers['X-Kasugai-CSRF'] = token;
            if (typeof body !== 'string') body = JSON.stringify(body || {});
        }
        return responseJson(await fetch(url, {
            method,
            headers,
            body,
            credentials: 'same-origin',
            cache: 'no-store',
            redirect: 'error',
        }));
    }

    function setStatus(message, kind) {
        const element = byId('workstationStatus');
        if (!element) return;
        element.textContent = message;
        element.classList.remove('is-ok', 'is-warning', 'is-error');
        if (kind) element.classList.add(`is-${kind}`);
    }

    function setFeedback(id, message, kind) {
        const element = byId(id);
        if (!element) return;
        element.textContent = message || '';
        element.classList.remove('success', 'error');
        if (kind) element.classList.add(kind);
        element.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    }

    function icon(name) {
        const element = document.createElement('i');
        element.setAttribute('data-lucide', name);
        element.setAttribute('aria-hidden', 'true');
        return element;
    }

    function refreshIcons() {
        if (window.lucide) window.lucide.createIcons();
    }

    function snapshotFrom(payload) {
        if (!payload || typeof payload !== 'object') return null;
        const candidate = payload.snapshot || payload.latest || payload.telemetry || payload;
        return candidate && typeof candidate === 'object' ? candidate : null;
    }

    function metric(label, iconName, value, detail, percent) {
        const card = document.createElement('div');
        card.className = 'workstation-metric';
        const heading = document.createElement('div');
        heading.className = 'workstation-metric-heading';
        const text = document.createElement('span');
        text.textContent = label;
        heading.append(text, icon(iconName));
        const strong = document.createElement('strong');
        strong.className = 'workstation-metric-value';
        strong.textContent = value;
        const small = document.createElement('span');
        small.className = 'workstation-metric-detail';
        small.textContent = detail || 'No additional detail';
        card.append(heading, strong, small);
        if (percent !== null && percent !== undefined) {
            const bounded = clampPercent(percent);
            const meter = document.createElement('div');
            meter.className = `workstation-meter${bounded >= 90 ? ' is-critical' : bounded >= 75 ? ' is-warning' : ''}`;
            const fill = document.createElement('span');
            fill.style.setProperty('--workstation-meter-value', `${bounded}%`);
            meter.appendChild(fill);
            card.appendChild(meter);
        }
        return card;
    }

    function diskSummary(snapshot) {
        const disks = Array.isArray(snapshot.disks) ? snapshot.disks : [];
        const disk = disks[0];
        if (!disk) return { value: '—', detail: 'No fixed disk reported', percent: null };
        return {
            value: formatPercent(disk.percent),
            detail: `${String(disk.name || 'Disk')} · ${formatBytes(disk.used_bytes)} of ${formatBytes(disk.total_bytes)}`,
            percent: disk.percent,
        };
    }

    function gpuSummary(snapshot) {
        const gpus = Array.isArray(snapshot.gpus) ? snapshot.gpus : [];
        const gpu = gpus[0];
        if (!gpu) return { value: '—', detail: 'No supported GPU reported', percent: null };
        const details = [String(gpu.name || 'GPU')];
        if (finite(gpu.temperature_c) !== null) details.push(`${Math.round(finite(gpu.temperature_c))}°C`);
        return { value: formatPercent(gpu.utilization_percent), detail: details.join(' · '), percent: gpu.utilization_percent };
    }

    function renderDetails(workstation, snapshot, status) {
        const details = byId('workstationDetails');
        if (!details) return;
        details.replaceChildren();
        const battery = snapshot?.battery;
        const values = [
            ['State', status || workstation?.status || 'unknown'],
            ['Last report', formatTime(snapshot?.captured_at || workstation?.last_seen_at)],
            ['Uptime', snapshot ? formatDuration(snapshot.system?.uptime_seconds) : '—'],
            ['Battery', battery ? `${formatPercent(battery.percent)}${battery.plugged ? ' · plugged in' : ''}` : 'Not reported'],
        ];
        values.forEach(([term, value]) => {
            const row = document.createElement('div');
            const dt = document.createElement('dt');
            const dd = document.createElement('dd');
            dt.textContent = term;
            dd.textContent = value;
            row.append(dt, dd);
            details.appendChild(row);
        });
    }

    function renderSnapshot(workstation, payload) {
        workstation = payload?.workstation && typeof payload.workstation === 'object'
            ? payload.workstation
            : workstation;
        const snapshot = snapshotFrom(payload);
        const status = String(payload?.status || workstation?.status || 'offline').toLowerCase();
        const grid = byId('workstationMetricGrid');
        if (!grid) return;
        grid.replaceChildren();
        grid.setAttribute('aria-busy', 'false');
        byId('workstationName').textContent = String(workstation?.display_name || 'Workstation');
        byId('workstationSource').textContent = String(workstation?.platform || 'Outbound host agent');

        if (!snapshot || !snapshot.cpu || !snapshot.memory) {
            const empty = document.createElement('div');
            empty.className = 'workstation-empty';
            empty.appendChild(icon(status === 'offline' ? 'monitor-x' : 'loader-circle'));
            const heading = document.createElement('strong');
            heading.textContent = status === 'offline' ? 'Workstation is offline' : 'Waiting for the first report';
            const copy = document.createElement('p');
            copy.textContent = 'Start the Kasugai companion agent on this computer, then refresh this widget.';
            empty.append(heading, copy);
            grid.appendChild(empty);
            setStatus(status === 'offline' ? 'Offline' : 'Waiting', status === 'offline' ? 'error' : 'warning');
            renderDetails(workstation, null, status);
            refreshIcons();
            return;
        }

        const disk = diskSummary(snapshot);
        const gpu = gpuSummary(snapshot);
        const memoryUsed = finite(snapshot.memory.used_bytes, 0);
        const memoryTotal = finite(snapshot.memory.total_bytes, 0);
        const network = snapshot.network || {};
        const io = snapshot.disk_io || {};
        grid.append(
            metric('CPU', 'cpu', formatPercent(snapshot.cpu.percent), `${finite(snapshot.cpu.logical_count, 0)} logical cores`, snapshot.cpu.percent),
            metric('Memory', 'memory-stick', formatPercent(snapshot.memory.percent), `${formatBytes(memoryUsed)} of ${formatBytes(memoryTotal)}`, snapshot.memory.percent),
            metric('GPU', 'circuit-board', gpu.value, gpu.detail, gpu.percent),
            metric('Primary disk', 'hard-drive', disk.value, disk.detail, disk.percent),
            metric('Network', 'activity', formatRate(network.received_bps), `Up ${formatRate(network.sent_bps)}`, null),
            metric('Disk activity', 'database', formatRate(io.read_bps), `Write ${formatRate(io.write_bps)}`, null),
        );
        setStatus(status === 'online' ? 'Online' : status === 'stale' ? 'Stale' : 'Offline', status === 'online' ? 'ok' : 'warning');
        renderDetails(workstation, snapshot, status);
        refreshIcons();
    }

    function renderUnpaired() {
        setStatus('Not paired');
        byId('workstationName').textContent = 'Waiting for a workstation';
        byId('workstationSource').textContent = 'Outbound host agent';
        const grid = byId('workstationMetricGrid');
        if (grid) {
            grid.replaceChildren();
            const empty = document.createElement('div');
            empty.className = 'workstation-empty';
            empty.appendChild(icon('monitor-up'));
            const heading = document.createElement('strong');
            heading.textContent = 'Pair your computer';
            const copy = document.createElement('p');
            copy.textContent = 'The companion agent sends privacy-safe workstation totals to this dashboard.';
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'cockpit-text-button';
            button.textContent = 'Start pairing';
            button.addEventListener('click', openSettings);
            empty.append(heading, copy, button);
            grid.appendChild(empty);
        }
        renderDetails(null, null, 'Not paired');
        refreshIcons();
    }

    function renderSelect() {
        const select = byId('workstationSelect');
        if (!select) return;
        select.replaceChildren();
        state.workstations.forEach(workstation => {
            const option = document.createElement('option');
            option.value = String(workstation.id || '');
            option.textContent = `${String(workstation.display_name || 'Workstation')} · ${String(workstation.status || 'unknown')}`;
            select.appendChild(option);
        });
        select.hidden = state.workstations.length < 2;
        select.value = state.selectedId;
    }

    async function loadLatest() {
        if (!state.selectedId || state.loading) return;
        state.loading = true;
        const generation = ++state.generation;
        byId('workstationMetricGrid')?.setAttribute('aria-busy', 'true');
        try {
            const payload = await api(`/api/workstations/${encodeURIComponent(state.selectedId)}/latest`);
            if (generation !== state.generation) return;
            const workstation = state.workstations.find(item => String(item.id) === state.selectedId);
            renderSnapshot(workstation, payload);
        } catch (error) {
            if (generation !== state.generation) return;
            setStatus('Unavailable', 'error');
            const grid = byId('workstationMetricGrid');
            if (grid) {
                grid.setAttribute('aria-busy', 'false');
                grid.replaceChildren();
                const empty = document.createElement('div');
                empty.className = 'workstation-empty';
                empty.appendChild(icon('triangle-alert'));
                const heading = document.createElement('strong');
                heading.textContent = 'Telemetry unavailable';
                const copy = document.createElement('p');
                copy.textContent = error.message;
                empty.append(heading, copy);
                grid.appendChild(empty);
            }
            refreshIcons();
        } finally {
            if (generation === state.generation) state.loading = false;
        }
    }

    async function loadWorkstations(options = {}) {
        const payload = await api('/api/workstations');
        state.workstations = Array.isArray(payload?.workstations) ? payload.workstations : [];
        if (!state.workstations.some(item => String(item.id) === state.selectedId)) {
            state.selectedId = String(state.workstations[0]?.id || '');
        }
        renderSelect();
        renderAgentList();
        if (!state.selectedId) renderUnpaired();
        else if (options.loadLatest !== false) await loadLatest();
    }

    function renderAgentList() {
        const list = byId('workstationAgentList');
        if (!list) return;
        list.replaceChildren();
        if (!state.workstations.length) {
            const empty = document.createElement('li');
            empty.className = 'settings-empty';
            empty.textContent = 'No workstations paired yet.';
            list.appendChild(empty);
            return;
        }
        state.workstations.forEach(workstation => {
            const item = document.createElement('li');
            item.className = 'settings-list-item';
            const copy = document.createElement('span');
            copy.className = 'workstation-agent-copy';
            const name = document.createElement('strong');
            name.textContent = String(workstation.display_name || 'Workstation');
            const detail = document.createElement('small');
            detail.textContent = `${String(workstation.platform || 'Unknown platform')} · ${String(workstation.status || 'unknown')} · ${formatTime(workstation.last_seen_at)}`;
            copy.append(name, detail);
            const actions = document.createElement('span');
            actions.className = 'workstation-agent-actions';
            const rename = document.createElement('button');
            rename.type = 'button';
            rename.className = 'settings-remove-btn';
            rename.textContent = 'Rename';
            rename.addEventListener('click', () => renameWorkstation(workstation));
            const revoke = document.createElement('button');
            revoke.type = 'button';
            revoke.className = 'settings-remove-btn';
            revoke.textContent = 'Revoke';
            revoke.addEventListener('click', () => revokeWorkstation(workstation));
            actions.append(rename, revoke);
            item.append(copy, actions);
            list.appendChild(item);
        });
    }

    async function createPairing() {
        const button = byId('createWorkstationPairing');
        if (button) button.disabled = true;
        setFeedback('workstationPairingStatus', 'Creating a one-time pairing code…');
        try {
            const payload = await api('/api/workstations/pairings', { method: 'POST', body: {} });
            const pairing = byId('workstationPairing');
            if (pairing) pairing.hidden = false;
            byId('workstationPairingCode').textContent = String(payload?.code || '');
            const command = `powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\install-workstation-agent.ps1 -ServerUrl ${window.location.origin} -PairingId ${String(payload?.pairing_id || '')}`;
            byId('workstationPairingCommand').textContent = command;
            byId('workstationPairingExpiry').textContent = `Expires ${formatTime(payload?.expires_at)} · pairing ID ${String(payload?.pairing_id || '')}`;
            setFeedback('workstationPairingStatus', 'Enter the one-time code when the agent prompts for it.', 'success');
        } catch (error) {
            setFeedback('workstationPairingStatus', error.message, 'error');
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function renameWorkstation(workstation) {
        const value = window.prompt('Workstation name', String(workstation.display_name || 'Workstation'));
        if (value === null) return;
        const displayName = value.trim();
        if (!displayName) return;
        try {
            await api(`/api/workstations/${encodeURIComponent(workstation.id)}`, {
                method: 'PATCH', body: { display_name: displayName },
            });
            setFeedback('workstationAgentStatus', 'Workstation renamed.', 'success');
            await loadWorkstations();
        } catch (error) {
            setFeedback('workstationAgentStatus', error.message, 'error');
        }
    }

    async function revokeWorkstation(workstation) {
        if (!window.confirm(`Revoke “${String(workstation.display_name || 'this workstation')}”? The agent will stop reporting immediately.`)) return;
        try {
            await api(`/api/workstations/${encodeURIComponent(workstation.id)}`, { method: 'DELETE' });
            setFeedback('workstationAgentStatus', 'Workstation revoked.', 'success');
            state.selectedId = '';
            await loadWorkstations();
        } catch (error) {
            setFeedback('workstationAgentStatus', error.message, 'error');
        }
    }

    function openSettings(event) {
        const opener = event?.currentTarget || (event?.focus ? event : null);
        window.KasugaiSettingsModal?.open?.('workstations', opener);
        loadWorkstations({ loadLatest: false }).catch(error => {
            setFeedback('workstationAgentStatus', error.message, 'error');
        });
    }

    function schedulePoll() {
        window.clearInterval(state.pollTimer);
        state.pollTimer = window.setInterval(() => {
            if (!document.hidden && state.selectedId) loadLatest();
        }, 10000);
    }

    function initialize() {
        if (!byId('workstationMonitor')) return;
        document.querySelectorAll('[data-open-workstation-settings]').forEach(button => {
            button.addEventListener('click', openSettings);
        });
        document.querySelector('.settings-tab[data-tab="workstations"]')?.addEventListener('click', () => {
            loadWorkstations({ loadLatest: false }).catch(error => setFeedback('workstationAgentStatus', error.message, 'error'));
        });
        byId('createWorkstationPairing')?.addEventListener('click', createPairing);
        byId('refreshWorkstation')?.addEventListener('click', () => loadWorkstations());
        byId('workstationSelect')?.addEventListener('change', event => {
            state.selectedId = String(event.currentTarget.value || '');
            loadLatest();
        });
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) loadLatest();
        });
        loadWorkstations().catch(() => renderUnpaired());
        schedulePoll();
    }

    if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initialize);

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            clampPercent,
            formatBytes,
            formatDuration,
            snapshotFrom,
        };
    }
})();
