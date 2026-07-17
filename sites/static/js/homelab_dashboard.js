(function () {
    'use strict';

    const state = {
        agents: [],
        selectedId: '',
        snapshot: null,
        actions: [],
        loading: false,
        pollTimer: null,
    };

    function byId(id) { return document.getElementById(id); }

    function finite(value, fallback = null) {
        if (value === null || value === undefined || value === '') return fallback;
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function formatPercent(value) {
        const parsed = finite(value);
        return parsed === null ? '—' : `${Math.round(Math.max(0, Math.min(100, parsed)))}%`;
    }

    function formatBytes(value) {
        const parsed = finite(value);
        if (parsed === null || parsed < 0) return '—';
        if (parsed === 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        const power = Math.min(units.length - 1, Math.floor(Math.log(parsed) / Math.log(1024)));
        const scaled = parsed / (1024 ** power);
        return `${scaled >= 100 || power === 0 ? Math.round(scaled) : scaled.toFixed(1)} ${units[power]}`;
    }

    function formatTime(value) {
        const date = new Date(String(value || ''));
        if (Number.isNaN(date.getTime())) return '—';
        return new Intl.DateTimeFormat(undefined, {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit',
        }).format(date);
    }

    async function parseResponse(response) {
        if (response.redirected || response.status === 401) throw new Error('Your session expired. Sign in again.');
        if (response.status === 204) {
            if (!response.ok) throw new Error('Kasugai could not complete that request.');
            return null;
        }
        let payload;
        try { payload = await response.json(); }
        catch (_error) { throw new Error('Kasugai returned an invalid homelab response.'); }
        if (!response.ok) throw new Error(payload?.error || 'Kasugai could not complete that request.');
        return payload;
    }

    async function api(url, options = {}) {
        const method = String(options.method || 'GET').toUpperCase();
        const headers = { Accept: 'application/json', ...(options.headers || {}) };
        let body = options.body;
        if (!['GET', 'HEAD'].includes(method)) {
            const csrf = String(window.KASUGAI_CSRF_TOKEN || '');
            if (!csrf) throw new Error('Reload this page before changing homelab settings.');
            headers['Content-Type'] = 'application/json';
            headers['X-Kasugai-CSRF'] = csrf;
            if (typeof body !== 'string') body = JSON.stringify(body || {});
        }
        return parseResponse(await fetch(url, {
            method, headers, body, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        }));
    }

    function icon(name) {
        const element = document.createElement('i');
        element.setAttribute('data-lucide', name);
        element.setAttribute('aria-hidden', 'true');
        return element;
    }

    function refreshIcons() { if (window.lucide) window.lucide.createIcons(); }

    function setStatus(message, kind) {
        const element = byId('homelabStatus');
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

    function normalizedAgents(payload) {
        const value = payload?.homelabs || payload?.agents || [];
        return Array.isArray(value) ? value : [];
    }

    function publicContainer(container) {
        if (!container || typeof container !== 'object') return null;
        const grants = container.grants && typeof container.grants === 'object' ? container.grants : {};
        return {
            key: typeof container.key === 'string' ? container.key : '',
            name: String(container.name || 'Unnamed container'),
            image: String(container.image || 'Unknown image'),
            compose_project: String(container.compose_project || ''),
            compose_service: String(container.compose_service || ''),
            state: String(container.state || 'unknown').toLowerCase(),
            health: String(container.health || 'unknown').toLowerCase(),
            cpu_percent: finite(container.cpu_percent),
            memory_usage_bytes: finite(container.memory_usage_bytes),
            memory_percent: finite(container.memory_percent),
            grants: {
                logs: grants.logs === true,
                actions: Array.isArray(grants.actions) ? grants.actions.filter(value => value === 'restart') : [],
            },
        };
    }

    function renderSummary(snapshot) {
        const summary = byId('homelabSummary');
        if (!summary) return;
        summary.replaceChildren();
        const engine = snapshot?.engine || {};
        const containers = Array.isArray(snapshot?.containers) ? snapshot.containers : [];
        const checks = Array.isArray(snapshot?.health_checks) ? snapshot.health_checks : [];
        const values = [
            [engine.container_counts?.running ?? containers.filter(item => item.state === 'running').length, 'Running'],
            [engine.container_counts?.stopped ?? containers.filter(item => item.state !== 'running').length, 'Stopped'],
            [containers.filter(item => ['unhealthy', 'starting'].includes(String(item.health).toLowerCase())).length, 'Need attention'],
            [checks.filter(item => item.status === 'down').length, 'Checks down'],
        ];
        values.forEach(([value, label]) => {
            const card = document.createElement('div');
            card.className = 'homelab-summary-card';
            const strong = document.createElement('strong');
            const span = document.createElement('span');
            strong.textContent = String(value ?? 0);
            span.textContent = label;
            card.append(strong, span);
            summary.appendChild(card);
        });
    }

    function badge(label, className) {
        const element = document.createElement('span');
        element.className = `cockpit-repo-badge${className ? ` ${className}` : ''}`;
        element.textContent = label;
        return element;
    }

    function createContainerRow(raw) {
        const container = publicContainer(raw);
        if (!container) return null;
        const row = document.createElement('article');
        row.className = 'homelab-container';
        const copy = document.createElement('div');
        copy.className = 'homelab-container-copy';
        const title = document.createElement('div');
        title.className = 'homelab-container-title';
        const dot = document.createElement('span');
        const unhealthy = ['unhealthy', 'dead', 'exited'].includes(container.health) || ['dead'].includes(container.state);
        dot.className = `homelab-state-dot${unhealthy ? ' is-error' : container.state === 'running' ? ' is-running' : ' is-warning'}`;
        const name = document.createElement('strong');
        name.textContent = container.name;
        title.append(dot, name);
        const imageName = document.createElement('span');
        imageName.className = 'homelab-container-image';
        imageName.textContent = [container.image, container.compose_project && container.compose_service
            ? `${container.compose_project} / ${container.compose_service}` : ''].filter(Boolean).join(' · ');
        const metrics = document.createElement('div');
        metrics.className = 'homelab-container-metrics';
        metrics.append(
            badge(container.state),
            badge(container.health, unhealthy ? 'is-behind' : ''),
            badge(`CPU ${formatPercent(container.cpu_percent)}`),
            badge(`RAM ${formatBytes(container.memory_usage_bytes)}`),
        );
        copy.append(title, imageName, metrics);

        const actions = document.createElement('div');
        actions.className = 'homelab-container-actions';
        const logs = document.createElement('button');
        logs.type = 'button';
        logs.className = 'cockpit-repository-link';
        logs.textContent = 'Logs';
        logs.disabled = !container.key || !container.grants.logs;
        logs.title = logs.disabled ? 'Logs are not granted by the host policy and container label' : 'Request the last 200 log lines';
        logs.addEventListener('click', () => queueAction(container, 'read_logs'));
        const restart = document.createElement('button');
        restart.type = 'button';
        restart.className = 'cockpit-repository-link';
        restart.textContent = 'Restart';
        restart.disabled = !container.key || !container.grants.actions.includes('restart');
        restart.title = restart.disabled ? 'Restart is not granted by the host policy and container label' : 'Restart this container';
        restart.addEventListener('click', () => queueAction(container, 'restart'));
        actions.append(logs, restart);
        row.append(copy, actions);
        return row;
    }

    function renderContainers(snapshot) {
        const list = byId('homelabContainerList');
        if (!list) return;
        list.replaceChildren();
        list.setAttribute('aria-busy', 'false');
        const engine = snapshot?.engine || {};
        const containers = Array.isArray(snapshot?.containers) ? snapshot.containers : [];
        if (!engine.available) {
            const empty = document.createElement('div');
            empty.className = 'workstation-empty';
            empty.appendChild(icon('container'));
            const heading = document.createElement('strong');
            heading.textContent = 'Docker inventory unavailable';
            const copy = document.createElement('p');
            copy.textContent = engine.error_code
                ? `The host reported ${String(engine.error_code).replaceAll('_', ' ')}.`
                : 'Enable Docker monitoring in the local homelab policy.';
            empty.append(heading, copy);
            list.appendChild(empty);
        } else if (!containers.length) {
            const empty = document.createElement('div');
            empty.className = 'workstation-empty';
            empty.appendChild(icon('container'));
            const heading = document.createElement('strong');
            heading.textContent = 'No monitored containers';
            const copy = document.createElement('p');
            copy.textContent = 'Add io.kasugai.monitor=true to containers you want the local agent to report.';
            empty.append(heading, copy);
            list.appendChild(empty);
        } else {
            containers.map(createContainerRow).filter(Boolean).forEach(row => list.appendChild(row));
        }
        refreshIcons();
    }

    function renderHealth(snapshot) {
        const list = byId('homelabHealthList');
        const status = byId('homelabHealthStatus');
        if (!list || !status) return;
        list.replaceChildren();
        const checks = Array.isArray(snapshot?.health_checks) ? snapshot.health_checks : [];
        const down = checks.filter(item => item.status === 'down').length;
        status.textContent = !checks.length ? 'Unconfigured' : down ? `${down} down` : 'All up';
        status.classList.remove('is-ok', 'is-warning', 'is-error');
        if (checks.length) status.classList.add(down ? 'is-error' : 'is-ok');
        if (!checks.length) {
            const empty = document.createElement('p');
            empty.className = 'home-empty-copy';
            empty.textContent = 'Health targets are configured only on the host agent.';
            list.appendChild(empty);
            return;
        }
        checks.slice(0, 8).forEach(check => {
            const item = document.createElement('div');
            item.className = 'homelab-health-item';
            const dot = document.createElement('span');
            dot.className = `homelab-health-state is-${['up', 'degraded', 'down'].includes(check.status) ? check.status : 'unknown'}`;
            const name = document.createElement('strong');
            name.textContent = String(check.name || 'Health check');
            const detail = document.createElement('small');
            const latency = finite(check.latency_ms);
            detail.textContent = latency === null ? String(check.status || 'unknown') : `${Math.round(latency)} ms`;
            item.append(dot, name, detail);
            list.appendChild(item);
        });
    }

    function actionResult(action) {
        return action?.result && typeof action.result === 'object'
            ? action.result
            : action?.result_payload && typeof action.result_payload === 'object'
                ? action.result_payload
                : action;
    }

    function showLogs(action) {
        const result = actionResult(action);
        const excerpt = typeof result?.log_excerpt === 'string' ? result.log_excerpt : '';
        const dialog = document.createElement('dialog');
        dialog.className = 'homelab-log-dialog';
        const heading = document.createElement('h2');
        heading.textContent = 'Container log excerpt';
        const warning = document.createElement('p');
        warning.className = 'settings-help';
        warning.textContent = 'Application logs can contain secrets. Kasugai bounds and encrypts this excerpt, but review it carefully.';
        const pre = document.createElement('pre');
        pre.textContent = excerpt || 'No log output was returned.';
        const close = document.createElement('button');
        close.type = 'button';
        close.className = 'app-button app-button-primary';
        close.textContent = 'Close';
        close.addEventListener('click', () => dialog.close());
        dialog.addEventListener('close', () => dialog.remove(), { once: true });
        dialog.append(heading, warning, pre, close);
        document.body.appendChild(dialog);
        dialog.showModal();
    }

    async function loadAndShowLogs(action) {
        try {
            const detail = await api(
                `/api/homelab/agents/${encodeURIComponent(state.selectedId)}/actions/${encodeURIComponent(action.id)}`,
            );
            showLogs(detail);
        } catch (error) {
            window.alert(error.message);
        }
    }

    function renderActions(payload) {
        state.actions = Array.isArray(payload?.actions) ? payload.actions : Array.isArray(payload) ? payload : [];
        const list = byId('homelabJobList');
        if (!list) return;
        list.replaceChildren();
        if (!state.actions.length) {
            const empty = document.createElement('p');
            empty.className = 'home-empty-copy';
            empty.textContent = 'No Docker actions have been requested.';
            list.appendChild(empty);
            return;
        }
        state.actions.slice(0, 6).forEach(action => {
            const item = document.createElement('div');
            item.className = 'homelab-job-item';
            const stateDot = document.createElement('span');
            const actionState = String(action.state || action.status || 'queued');
            stateDot.className = `homelab-health-state ${actionState === 'succeeded' ? 'is-up' : ['failed', 'rejected', 'unknown'].includes(actionState) ? 'is-down' : 'is-degraded'}`;
            const title = document.createElement('strong');
            title.textContent = String(action.operation || 'Docker action').replaceAll('_', ' ');
            if (action.operation === 'read_logs' && actionState === 'succeeded' && action.id) {
                title.tabIndex = 0;
                title.role = 'button';
                title.title = 'View log excerpt';
                title.addEventListener('click', () => loadAndShowLogs(action));
                title.addEventListener('keydown', event => {
                    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); loadAndShowLogs(action); }
                });
            }
            const detail = document.createElement('small');
            detail.textContent = `${actionState} · ${formatTime(action.completed_at || action.requested_at)}`;
            item.append(stateDot, title, detail);
            list.appendChild(item);
        });
    }

    async function loadActions() {
        if (!state.selectedId) return;
        try {
            renderActions(await api(`/api/homelab/agents/${encodeURIComponent(state.selectedId)}/actions`));
        } catch (_error) {
            renderActions([]);
        }
    }

    async function queueAction(container, operation) {
        if (!state.selectedId || !container.key) return;
        if (operation === 'read_logs' && !window.confirm(`Request the last 200 lines from “${container.name}”? Application logs can contain secrets.`)) return;
        try {
            let result = await api(`/api/homelab/agents/${encodeURIComponent(state.selectedId)}/actions`, {
                method: 'POST', body: { operation, resource_key: container.key },
            });
            if (operation === 'restart' && result?.queued === false && result.preview) {
                const preview = result.preview;
                const target = String(preview.resource?.name || container.name);
                const expires = formatTime(preview.expires_at);
                if (!window.confirm(`Restart “${target}”? This confirmation expires ${expires}. The host will revalidate policy and labels before acting.`)) return;
                result = await api(`/api/homelab/agents/${encodeURIComponent(state.selectedId)}/actions`, {
                    method: 'POST',
                    body: {
                        operation,
                        resource_key: container.key,
                        confirmation_token: String(preview.confirmation_token || ''),
                    },
                });
            }
            if (!result?.queued) throw new Error('Kasugai did not queue this action.');
            setStatus(operation === 'restart' ? 'Restart queued' : 'Logs queued', 'warning');
            await loadActions();
        } catch (error) {
            setStatus('Action blocked', 'error');
            window.alert(error.message);
        }
    }

    function renderUnpaired() {
        setStatus('Not paired');
        byId('homelabName').textContent = 'Waiting for a homelab agent';
        byId('homelabEngineCopy').textContent = 'Outbound Docker inventory';
        renderSummary(null);
        renderContainers({ engine: { available: false }, containers: [] });
        renderHealth(null);
        renderActions([]);
    }

    function renderSelect() {
        const select = byId('homelabSelect');
        if (!select) return;
        select.replaceChildren();
        state.agents.forEach(agent => {
            const option = document.createElement('option');
            option.value = String(agent.id || '');
            option.textContent = `${String(agent.display_name || 'Homelab')} · ${String(agent.status || 'unknown')}`;
            select.appendChild(option);
        });
        select.hidden = state.agents.length < 2;
        select.value = state.selectedId;
    }

    function renderAgentList() {
        const list = byId('homelabAgentList');
        if (!list) return;
        list.replaceChildren();
        if (!state.agents.length) {
            const empty = document.createElement('li');
            empty.className = 'settings-empty';
            empty.textContent = 'No homelab agents paired yet.';
            list.appendChild(empty);
            return;
        }
        state.agents.forEach(agent => {
            const item = document.createElement('li');
            item.className = 'settings-list-item';
            const copy = document.createElement('span');
            copy.className = 'workstation-agent-copy';
            const name = document.createElement('strong');
            name.textContent = String(agent.display_name || 'Homelab agent');
            const detail = document.createElement('small');
            detail.textContent = `${String(agent.platform || 'Unknown platform')} · ${String(agent.status || 'unknown')} · ${formatTime(agent.last_seen_at)}`;
            copy.append(name, detail);
            const actions = document.createElement('span');
            actions.className = 'workstation-agent-actions';
            const rename = document.createElement('button');
            rename.type = 'button'; rename.className = 'settings-remove-btn'; rename.textContent = 'Rename';
            rename.addEventListener('click', () => renameAgent(agent));
            const revoke = document.createElement('button');
            revoke.type = 'button'; revoke.className = 'settings-remove-btn'; revoke.textContent = 'Revoke';
            revoke.addEventListener('click', () => revokeAgent(agent));
            actions.append(rename, revoke);
            item.append(copy, actions);
            list.appendChild(item);
        });
    }

    async function loadLatest() {
        if (!state.selectedId || state.loading) return;
        state.loading = true;
        byId('homelabContainerList')?.setAttribute('aria-busy', 'true');
        try {
            const payload = await api(`/api/homelab/agents/${encodeURIComponent(state.selectedId)}/latest`);
            const agent = payload?.homelab || payload?.agent || state.agents.find(item => String(item.id) === state.selectedId) || {};
            state.snapshot = payload?.snapshot || payload?.latest || null;
            byId('homelabName').textContent = String(agent.display_name || 'Homelab agent');
            const engine = state.snapshot?.engine || {};
            byId('homelabEngineCopy').textContent = engine.available
                ? `${String(engine.kind || 'Docker')} ${String(engine.server_version || '')}`.trim()
                : 'Docker inventory unavailable';
            const status = String(agent.status || 'offline');
            setStatus(status === 'online' ? 'Online' : status === 'stale' ? 'Stale' : 'Offline', status === 'online' ? 'ok' : 'warning');
            renderSummary(state.snapshot);
            renderContainers(state.snapshot);
            renderHealth(state.snapshot);
            await loadActions();
        } catch (error) {
            setStatus('Unavailable', 'error');
            renderContainers({ engine: { available: false, error_code: error.message }, containers: [] });
        } finally {
            state.loading = false;
        }
    }

    async function loadAgents(options = {}) {
        state.agents = normalizedAgents(await api('/api/homelab/agents'));
        if (!state.agents.some(agent => String(agent.id) === state.selectedId)) state.selectedId = String(state.agents[0]?.id || '');
        renderSelect();
        renderAgentList();
        if (!state.selectedId) renderUnpaired();
        else if (options.latest !== false) await loadLatest();
    }

    async function createPairing() {
        const button = byId('createHomelabPairing');
        if (button) button.disabled = true;
        setFeedback('homelabPairingStatus', 'Creating a separate one-time pairing code…');
        try {
            const payload = await api('/api/homelab/pairings', { method: 'POST', body: {} });
            byId('homelabPairing').hidden = false;
            byId('homelabPairingCode').textContent = String(payload?.code || '');
            byId('homelabPairingCommand').textContent = `python -m homelab_agent pair --server ${window.location.origin} --pairing-id ${String(payload?.pairing_id || '')}`;
            byId('homelabPairingExpiry').textContent = `Expires ${formatTime(payload?.expires_at)} · pairing ID ${String(payload?.pairing_id || '')}`;
            setFeedback('homelabPairingStatus', 'The agent will securely prompt for this code.', 'success');
        } catch (error) {
            setFeedback('homelabPairingStatus', error.message, 'error');
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function renameAgent(agent) {
        const value = window.prompt('Homelab agent name', String(agent.display_name || 'Homelab'));
        if (value === null || !value.trim()) return;
        try {
            await api(`/api/homelab/agents/${encodeURIComponent(agent.id)}`, { method: 'PATCH', body: { display_name: value.trim() } });
            setFeedback('homelabAgentStatus', 'Agent renamed.', 'success');
            await loadAgents();
        } catch (error) { setFeedback('homelabAgentStatus', error.message, 'error'); }
    }

    async function revokeAgent(agent) {
        if (!window.confirm(`Revoke “${String(agent.display_name || 'this homelab agent')}” and cancel its pending actions?`)) return;
        try {
            await api(`/api/homelab/agents/${encodeURIComponent(agent.id)}`, { method: 'DELETE', body: { delete_history: true } });
            state.selectedId = '';
            setFeedback('homelabAgentStatus', 'Homelab agent revoked.', 'success');
            await loadAgents();
        } catch (error) { setFeedback('homelabAgentStatus', error.message, 'error'); }
    }

    function openSettings(event) {
        window.KasugaiSettingsModal?.open?.('homelab', event?.currentTarget || event || null);
        loadAgents({ latest: false }).catch(error => setFeedback('homelabAgentStatus', error.message, 'error'));
    }

    function initialize() {
        if (!byId('homelabDashboard')) return;
        document.querySelectorAll('[data-open-homelab-settings]').forEach(button => button.addEventListener('click', openSettings));
        document.querySelector('.settings-tab[data-tab="homelab"]')?.addEventListener('click', () => loadAgents({ latest: false }));
        byId('createHomelabPairing')?.addEventListener('click', createPairing);
        byId('refreshHomelab')?.addEventListener('click', () => loadAgents());
        byId('homelabSelect')?.addEventListener('change', event => { state.selectedId = String(event.currentTarget.value || ''); loadLatest(); });
        document.addEventListener('visibilitychange', () => { if (!document.hidden) loadLatest(); });
        state.pollTimer = window.setInterval(() => { if (!document.hidden) loadLatest(); }, 15000);
        loadAgents().catch(renderUnpaired);
    }

    if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initialize);
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = { normalizedAgents, publicContainer };
    }
})();
