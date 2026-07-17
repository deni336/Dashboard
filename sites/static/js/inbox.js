(function () {
    'use strict';

    const SOURCES = new Set(['github', 'developer', 'workstation', 'homelab', 'launcher', 'automation', 'system']);
    const ITEM_STATES = new Set(['unread', 'read', 'snoozed', 'archived']);
    const PATCH_STATES = new Set(['unread', 'read', 'archived']);
    const SEVERITIES = new Set(['info', 'success', 'warning', 'error']);
    const KINDS = new Set([
        'notification', 'event', 'agent_offline', 'agent_stale', 'container_unhealthy',
        'health_check_down', 'image_update', 'task_run', 'rule_failure',
    ]);
    const FILTER_STATES = new Set(['active', 'unread', 'read', 'snoozed', 'archived', 'all']);
    const KIND_ICONS = Object.freeze({
        notification: 'bell',
        event: 'activity',
        agent_offline: 'unplug',
        agent_stale: 'clock-alert',
        container_unhealthy: 'container',
        health_check_down: 'heart-pulse',
        image_update: 'package-check',
        task_run: 'square-play',
        rule_failure: 'workflow',
    });
    const state = {
        items: [],
        counts: { unread: 0, total: 0, pinned: 0 },
        sources: [],
        connectorErrors: [],
        refreshedAt: '',
        selectedState: 'active',
        selectedSource: '',
        sort: 'priority',
        busyIds: new Set(),
        generation: 0,
        pollTimer: null,
    };

    function byId(id) { return document.getElementById(id); }
    function object(value) { return value && typeof value === 'object' && !Array.isArray(value) ? value : null; }

    function plain(value, maximum = 160) {
        if (typeof value !== 'string' && typeof value !== 'number') return '';
        return String(value).replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, maximum);
    }

    function itemId(value) {
        return typeof value === 'string' && /^[a-f0-9]{32}$/.test(value) ? value : '';
    }

    function safeDate(value) {
        if (typeof value !== 'string') return '';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? '' : date.toISOString();
    }

    function count(value) {
        return Number.isSafeInteger(value) && value >= 0 ? Math.min(value, 1000000) : null;
    }

    function safeOpenTarget(value) {
        if (typeof value !== 'string' || !value) return null;
        if (/^#[A-Za-z][A-Za-z0-9_-]{0,79}$/.test(value)) {
            return Object.freeze({ kind: 'internal', value });
        }
        try {
            const url = new URL(value);
            const hostname = url.hostname.toLocaleLowerCase().replace(/\.$/, '');
            const invalid = url.protocol !== 'https:' || url.username || url.password
                || hostname !== 'github.com' || (url.port && url.port !== '443')
                || url.search || url.hash || !url.pathname.startsWith('/') || value.includes('\\');
            if (invalid) return null;
            return Object.freeze({ kind: 'github', value: `https://github.com${url.pathname}` });
        } catch (_error) { return null; }
    }

    function normalizeItem(value) {
        const source = object(value);
        if (!source) return null;
        const id = itemId(source.id);
        const title = plain(source.title, 160);
        const occurredAt = safeDate(source.occurred_at);
        if (!id || !SOURCES.has(source.source) || !KINDS.has(source.kind) || !SEVERITIES.has(source.severity) || !title || !ITEM_STATES.has(source.state) || !occurredAt) return null;
        const snoozed = source.snoozed_until === null ? '' : safeDate(source.snoozed_until);
        if ((source.snoozed_until !== null && !snoozed) || (source.state === 'snoozed' && !snoozed)) return null;
        return Object.freeze({
            id,
            source: source.source,
            kind: source.kind,
            severity: source.severity,
            title,
            body: plain(source.body, 1000),
            open_target: safeOpenTarget(source.url),
            occurred_at: occurredAt,
            state: source.state,
            pinned: source.pinned === true,
            snoozed_until: snoozed,
            live: source.live === true,
        });
    }

    function normalizeSource(value) {
        const source = object(value);
        if (!source || !SOURCES.has(source.id)) return null;
        const sourceCount = count(source.count);
        if (sourceCount === null) return null;
        return Object.freeze({ id: source.id, label: plain(source.label, 64) || capitalize(source.id), count: sourceCount });
    }

    function normalizeConnectorError(value) {
        const source = object(value);
        if (!source || !SOURCES.has(source.source)) return null;
        const message = plain(source.message, 300);
        return message ? Object.freeze({ source: source.source, message }) : null;
    }

    function normalizeInbox(payload) {
        const source = object(payload);
        const counts = object(source?.counts);
        if (!source || !Array.isArray(source.items) || !counts || !Array.isArray(source.sources) || !Array.isArray(source.connector_errors)) {
            throw new Error('Kasugai returned an invalid inbox response.');
        }
        const unread = count(counts.unread);
        const total = count(counts.total);
        const pinned = count(counts.pinned);
        if ([unread, total, pinned].some(value => value === null)) throw new Error('Kasugai returned invalid inbox counts.');
        const refreshedAt = safeDate(source.refreshed_at);
        if (!refreshedAt) throw new Error('Kasugai returned an invalid inbox refresh time.');
        return Object.freeze({
            items: Object.freeze(source.items.slice(0, 250).map(normalizeItem).filter(Boolean)),
            counts: Object.freeze({ unread, total, pinned }),
            sources: Object.freeze(source.sources.slice(0, 16).map(normalizeSource).filter(Boolean)),
            refreshed_at: refreshedAt,
            connector_errors: Object.freeze(source.connector_errors.slice(0, 16).map(normalizeConnectorError).filter(Boolean)),
        });
    }

    function normalizeItemState(payload) {
        const source = object(payload);
        if (!source) throw new Error('Kasugai returned an invalid inbox item state.');
        const id = itemId(source.id);
        const snoozed = source.snoozed_until === null ? '' : safeDate(source.snoozed_until);
        if (!id || !ITEM_STATES.has(source.state) || typeof source.pinned !== 'boolean' || (source.snoozed_until !== null && !snoozed) || (source.state === 'snoozed' && !snoozed)) {
            throw new Error('Kasugai returned an invalid inbox item state.');
        }
        return Object.freeze({ id, state: source.state, pinned: source.pinned, snoozed_until: snoozed });
    }

    function capitalize(value) {
        const text = plain(value, 64).replaceAll('_', ' ');
        return text ? `${text.charAt(0).toLocaleUpperCase()}${text.slice(1)}` : '';
    }

    function formatTime(value) {
        const date = new Date(String(value || ''));
        if (Number.isNaN(date.getTime())) return 'Time unavailable';
        return new Intl.DateTimeFormat(undefined, {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
        }).format(date);
    }

    function icon(name) {
        const element = document.createElement('i');
        element.setAttribute('data-lucide', name);
        element.setAttribute('aria-hidden', 'true');
        return element;
    }

    function refreshIcons() { if (window.lucide) window.lucide.createIcons(); }

    function csrfToken() {
        return plain(document.querySelector('meta[name="kasugai-csrf-token"]')?.getAttribute('content'), 256);
    }

    async function responseJson(response) {
        if (response.redirected || response.status === 401) throw new Error('Your session expired. Sign in again.');
        if (response.status === 204) {
            if (!response.ok) throw new Error('Kasugai could not complete that inbox request.');
            return null;
        }
        let payload;
        try { payload = await response.json(); }
        catch (_error) { throw new Error('Kasugai returned an invalid inbox response.'); }
        if (!response.ok) throw new Error(plain(payload?.error, 240) || 'Kasugai could not complete that inbox request.');
        return payload;
    }

    async function api(url, options = {}) {
        const method = String(options.method || 'GET').toUpperCase();
        const headers = { Accept: 'application/json' };
        let body;
        if (!['GET', 'HEAD'].includes(method)) {
            const token = csrfToken();
            if (!token) throw new Error('Reload this page before changing inbox items.');
            headers['Content-Type'] = 'application/json';
            headers['X-Kasugai-CSRF'] = token;
            body = JSON.stringify(object(options.body) || {});
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

    function setFeedback(message, kind) {
        const element = byId('inboxFeedback');
        if (!element) return;
        element.textContent = message || '';
        element.classList.remove('success', 'error');
        if (kind) element.classList.add(kind);
        element.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    }

    function setSummary() {
        byId('inboxUnreadCount').textContent = String(state.counts.unread);
        byId('inboxPinnedCount').textContent = String(state.counts.pinned);
        byId('inboxTotalCount').textContent = String(state.counts.total);
        const liveSources = new Set(state.items.filter(item => item.live).map(item => item.source)).size;
        byId('inboxLiveCount').textContent = String(liveSources);
        byId('inboxRefreshedAt').textContent = state.refreshedAt ? `Refreshed ${formatTime(state.refreshedAt)}` : 'Refresh time unavailable';
        const status = byId('inboxStatus');
        status.textContent = state.counts.unread ? `${state.counts.unread} unread` : 'All caught up';
        status.classList.remove('is-ok', 'is-warning', 'is-error');
        status.classList.add(state.counts.unread ? 'is-warning' : 'is-ok');
        byId('inboxMarkAllRead').disabled = state.counts.unread === 0;
        const badge = byId('inboxUnreadBadge');
        badge.hidden = state.counts.unread === 0;
        badge.textContent = state.counts.unread > 99 ? '99+' : String(state.counts.unread);
        badge.setAttribute('aria-label', `${state.counts.unread} unread inbox item${state.counts.unread === 1 ? '' : 's'}`);
    }

    function renderSourceChips() {
        const container = byId('inboxSourceChips');
        if (!container) return;
        container.replaceChildren();
        const all = document.createElement('button');
        all.type = 'button';
        all.className = `inbox-source-chip${state.selectedSource ? '' : ' is-active'}`;
        all.setAttribute('aria-pressed', String(!state.selectedSource));
        all.textContent = 'All sources';
        all.addEventListener('click', () => selectSource(''));
        container.appendChild(all);
        state.sources.forEach(source => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `inbox-source-chip${state.selectedSource === source.id ? ' is-active' : ''}`;
            button.setAttribute('aria-pressed', String(state.selectedSource === source.id));
            const label = document.createElement('strong');
            label.textContent = source.label;
            const value = document.createElement('span');
            value.textContent = String(source.count);
            button.append(label, value);
            button.addEventListener('click', () => selectSource(source.id));
            container.appendChild(button);
        });
    }

    function renderSources() {
        const container = byId('inboxSourceList');
        if (!container) return;
        container.replaceChildren();
        if (!state.sources.length) {
            const empty = document.createElement('p');
            empty.className = 'home-empty-copy';
            empty.textContent = 'No inbox sources have reported yet.';
            container.appendChild(empty);
        } else state.sources.forEach(source => {
            const row = document.createElement('div');
            row.className = 'inbox-source-row';
            const dot = document.createElement('span');
            const live = state.items.some(item => item.source === source.id && item.live);
            dot.className = `inbox-source-dot${live ? ' is-live' : ''}`;
            const label = document.createElement('strong');
            label.textContent = source.label;
            const value = document.createElement('span');
            value.textContent = `${source.count} item${source.count === 1 ? '' : 's'}`;
            row.append(dot, label, value);
            container.appendChild(row);
        });

        const disclosure = byId('inboxConnectorDisclosure');
        const errors = byId('inboxConnectorErrors');
        disclosure.hidden = state.connectorErrors.length === 0;
        errors.replaceChildren();
        state.connectorErrors.forEach(error => {
            const card = document.createElement('div');
            card.className = 'inbox-connector-error';
            const title = document.createElement('strong');
            title.textContent = `${capitalize(error.source)} connector`;
            const message = document.createElement('p');
            message.textContent = error.message;
            card.append(title, message);
            errors.appendChild(card);
        });
        byId('inboxConnectorErrorSummary').textContent = `${state.connectorErrors.length} connector issue${state.connectorErrors.length === 1 ? '' : 's'}`;
        const status = byId('inboxConnectorStatus');
        status.textContent = state.connectorErrors.length ? `${state.connectorErrors.length} issue${state.connectorErrors.length === 1 ? '' : 's'}` : 'Healthy';
        status.classList.remove('is-ok', 'is-warning', 'is-error');
        status.classList.add(state.connectorErrors.length ? 'is-warning' : 'is-ok');
        refreshIcons();
    }

    function priority(item) {
        const severity = { error: 40, warning: 24, success: 8, info: 4 }[item.severity] || 0;
        return (item.pinned ? 100 : 0) + (item.state === 'unread' ? 50 : 0) + (item.live ? 6 : 0) + severity;
    }

    function visibleItems() {
        const query = plain(byId('inboxSearch')?.value, 120).toLocaleLowerCase();
        const values = state.items.filter(item => !query || `${item.title} ${item.body} ${item.source} ${item.kind}`.toLocaleLowerCase().includes(query));
        const timestamp = item => new Date(item.occurred_at || 0).getTime() || 0;
        if (state.sort === 'newest') values.sort((left, right) => timestamp(right) - timestamp(left));
        else if (state.sort === 'oldest') values.sort((left, right) => timestamp(left) - timestamp(right));
        else values.sort((left, right) => priority(right) - priority(left) || timestamp(right) - timestamp(left));
        return values;
    }

    function actionButton(label, className, callback, disabled) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = className;
        button.textContent = label;
        button.disabled = disabled;
        button.addEventListener('click', callback);
        return button;
    }

    function snoozeMenu(item, disabled) {
        if (item.state === 'snoozed') {
            return actionButton('Wake now', 'app-button app-button-secondary', () => patchItem(item, { state: 'unread', snoozed_until: null }, 'Item returned to the inbox.'), disabled);
        }
        const details = document.createElement('details');
        details.className = 'inbox-snooze-menu';
        const summary = document.createElement('summary');
        summary.textContent = 'Snooze';
        const options = document.createElement('div');
        options.className = 'inbox-snooze-options';
        const oneHour = actionButton('For 1 hour', '', () => {
            const wake = new Date(Date.now() + 60 * 60 * 1000).toISOString();
            patchItem(item, { snoozed_until: wake }, 'Item snoozed for one hour.');
        }, disabled);
        const tomorrow = actionButton('Until tomorrow', '', () => {
            const wake = new Date();
            wake.setDate(wake.getDate() + 1);
            wake.setHours(9, 0, 0, 0);
            patchItem(item, { snoozed_until: wake.toISOString() }, 'Item snoozed until tomorrow.');
        }, disabled);
        options.append(oneHour, tomorrow);
        details.append(summary, options);
        if (disabled) details.setAttribute('data-disabled', 'true');
        return details;
    }

    function itemCard(item) {
        const card = document.createElement('article');
        card.className = `inbox-item is-${item.severity}${item.state === 'unread' ? ' is-unread' : ''}${item.state === 'archived' ? ' is-archived' : ''}`;
        const iconBox = document.createElement('span');
        iconBox.className = 'inbox-item-icon';
        iconBox.appendChild(icon(KIND_ICONS[item.kind]));
        const copy = document.createElement('div');
        copy.className = 'inbox-item-copy';
        const heading = document.createElement('div');
        heading.className = 'inbox-item-heading';
        const title = document.createElement('strong');
        title.textContent = item.title;
        const source = document.createElement('span');
        source.textContent = capitalize(item.source);
        heading.append(title, source);
        if (item.live) {
            const live = document.createElement('span');
            live.className = 'is-live';
            live.textContent = 'Live';
            heading.appendChild(live);
        }
        if (item.pinned) {
            const pinned = document.createElement('span');
            pinned.className = 'is-pinned';
            pinned.textContent = 'Pinned';
            heading.appendChild(pinned);
        }
        const body = document.createElement('p');
        body.className = 'inbox-item-body';
        body.textContent = item.body || 'No additional details were provided.';
        const meta = document.createElement('div');
        meta.className = 'inbox-item-meta';
        const occurred = document.createElement('span');
        occurred.append(icon('clock-3'));
        const occurredText = document.createElement('span');
        occurredText.textContent = formatTime(item.occurred_at);
        occurred.appendChild(occurredText);
        const kind = document.createElement('span');
        kind.append(icon('tag'));
        const kindText = document.createElement('span');
        kindText.textContent = capitalize(item.kind);
        kind.appendChild(kindText);
        meta.append(occurred, kind);
        if (item.snoozed_until) {
            const wake = document.createElement('span');
            wake.append(icon('alarm-clock'));
            const wakeText = document.createElement('span');
            wakeText.textContent = `Wakes ${formatTime(item.snoozed_until)}`;
            wake.appendChild(wakeText);
            meta.appendChild(wake);
        }
        copy.append(heading, body, meta);

        const actions = document.createElement('div');
        actions.className = 'inbox-item-actions';
        const disabled = state.busyIds.has(item.id);
        if (item.open_target) actions.appendChild(actionButton('Open', 'app-button app-button-primary', () => openItem(item), disabled));
        actions.appendChild(actionButton(item.state === 'unread' ? 'Mark read' : 'Mark unread', 'app-button app-button-secondary', () => patchItem(item, { state: item.state === 'unread' ? 'read' : 'unread', snoozed_until: null }, `Item marked ${item.state === 'unread' ? 'read' : 'unread'}.`), disabled));
        actions.appendChild(actionButton(item.pinned ? 'Unpin' : 'Pin', 'app-button app-button-secondary', () => patchItem(item, { pinned: !item.pinned }, item.pinned ? 'Item unpinned.' : 'Item pinned.'), disabled));
        if (item.state !== 'archived') actions.appendChild(snoozeMenu(item, disabled));
        actions.appendChild(actionButton(item.state === 'archived' ? 'Restore' : 'Archive', 'app-button app-button-secondary inbox-archive-button', () => patchItem(item, { state: item.state === 'archived' ? 'unread' : 'archived', snoozed_until: null }, item.state === 'archived' ? 'Item restored.' : 'Item archived.'), disabled));
        card.append(iconBox, copy, actions);
        return card;
    }

    function renderItems() {
        const container = byId('inboxItemList');
        if (!container) return;
        container.replaceChildren();
        container.setAttribute('aria-busy', 'false');
        const items = visibleItems();
        if (!items.length) {
            const empty = document.createElement('div');
            empty.className = 'inbox-empty-state';
            empty.appendChild(icon(state.items.length ? 'search-x' : 'inbox'));
            const title = document.createElement('strong');
            title.textContent = state.items.length ? 'Nothing matches this search' : state.selectedState === 'unread' ? 'No unread items' : 'This inbox view is clear';
            const copy = document.createElement('p');
            copy.textContent = state.items.length ? 'Try a shorter search or change the source and state filters.' : 'New developer, workstation, homelab, launcher, and automation activity will collect here.';
            empty.append(title, copy);
            container.appendChild(empty);
        } else items.forEach(item => container.appendChild(itemCard(item)));
        refreshIcons();
    }

    function queryUrl() {
        const params = new URLSearchParams();
        params.set('state', state.selectedState);
        if (state.selectedSource) params.set('source', state.selectedSource);
        return `/api/inbox?${params.toString()}`;
    }

    async function loadInbox() {
        const generation = ++state.generation;
        byId('inboxItemList')?.setAttribute('aria-busy', 'true');
        try {
            const payload = normalizeInbox(await api(queryUrl()));
            if (generation !== state.generation) return;
            state.items = [...payload.items];
            state.counts = payload.counts;
            state.sources = [...payload.sources];
            state.connectorErrors = [...payload.connector_errors];
            state.refreshedAt = payload.refreshed_at;
            renderSourceChips();
            renderSources();
            renderItems();
            setSummary();
            setFeedback('');
        } catch (error) {
            if (generation !== state.generation) return;
            byId('inboxItemList')?.setAttribute('aria-busy', 'false');
            const status = byId('inboxStatus');
            status.textContent = 'Unavailable';
            status.classList.remove('is-ok', 'is-warning');
            status.classList.add('is-error');
            setFeedback(error.message, 'error');
        }
    }

    function selectSource(source) {
        if (source && !SOURCES.has(source)) return;
        state.selectedSource = source;
        loadInbox();
    }

    async function patchItem(item, changes, successMessage) {
        if (state.busyIds.has(item.id)) return;
        const allowed = {};
        if (Object.hasOwn(changes, 'state') && PATCH_STATES.has(changes.state)) allowed.state = changes.state;
        if (Object.hasOwn(changes, 'pinned') && typeof changes.pinned === 'boolean') allowed.pinned = changes.pinned;
        if (Object.hasOwn(changes, 'snoozed_until')) {
            if (changes.snoozed_until === null) allowed.snoozed_until = null;
            else {
                const date = safeDate(changes.snoozed_until);
                if (date) allowed.snoozed_until = date;
            }
        }
        if (!Object.keys(allowed).length) return;
        state.busyIds.add(item.id);
        renderItems();
        try {
            normalizeItemState(await api(`/api/inbox/${encodeURIComponent(item.id)}`, { method: 'PATCH', body: allowed }));
            setFeedback(successMessage, 'success');
            await loadInbox();
        } catch (error) { setFeedback(error.message, 'error'); }
        finally { state.busyIds.delete(item.id); renderItems(); }
    }

    function openItem(item) {
        const target = item.open_target;
        if (!target) return;
        if (target.kind === 'internal') {
            document.getElementById(target.value.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } else if (target.kind === 'github') window.open(target.value, '_blank', 'noopener,noreferrer');
        if (item.state === 'unread') patchItem(item, { state: 'read' }, 'Item marked read.');
    }

    async function markAllRead() {
        const button = byId('inboxMarkAllRead');
        if (button) button.disabled = true;
        try {
            const body = state.selectedSource ? { source: state.selectedSource } : {};
            await api('/api/inbox/mark-all-read', { method: 'POST', body });
            setFeedback(state.selectedSource ? `All ${capitalize(state.selectedSource)} items marked read.` : 'All inbox items marked read.', 'success');
            await loadInbox();
        } catch (error) { setFeedback(error.message, 'error'); }
        finally { if (button) button.disabled = state.counts.unread === 0; }
    }

    function initialize() {
        if (!byId('inboxModule')) return;
        byId('inboxTopbarButton')?.addEventListener('click', () => byId('inboxModule')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
        byId('refreshInbox')?.addEventListener('click', loadInbox);
        byId('inboxMarkAllRead')?.addEventListener('click', markAllRead);
        byId('inboxSearch')?.addEventListener('input', renderItems);
        byId('inboxStateFilter')?.addEventListener('change', event => {
            const value = String(event.currentTarget.value || 'active');
            if (FILTER_STATES.has(value)) { state.selectedState = value; loadInbox(); }
        });
        byId('inboxSort')?.addEventListener('change', event => {
            const value = String(event.currentTarget.value || 'priority');
            state.sort = ['priority', 'newest', 'oldest'].includes(value) ? value : 'priority';
            renderItems();
        });
        document.addEventListener('visibilitychange', () => { if (!document.hidden) loadInbox(); });
        state.pollTimer = window.setInterval(() => { if (!document.hidden) loadInbox(); }, 30000);
        loadInbox();
    }

    if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initialize);
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            normalizeConnectorError,
            normalizeInbox,
            normalizeItem,
            normalizeItemState,
            normalizeSource,
            safeOpenTarget,
        };
    }
})();
