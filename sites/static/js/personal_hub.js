(function () {
    'use strict';

    const KINDS = Object.freeze(['reminder', 'countdown', 'habit', 'bookmark']);
    const KIND_SET = new Set(KINDS);
    const CADENCES = Object.freeze(['daily', 'weekdays', 'weekly']);
    const CADENCE_SET = new Set(CADENCES);
    const MAX_ITEMS = 250;
    const MAX_CHECKINS = 90;
    const TIMER_PRESETS = Object.freeze([25, 5, 50]);
    const REQUIRED_DOM_IDS = Object.freeze([
        'personalHubModule', 'personalHubStatus', 'personalHubFeedback',
        'refreshPersonalHub', 'addPersonalHubItem', 'personalHubTotalCount',
        'personalHubReminderCount', 'personalHubCountdownCount', 'personalHubHabitCount',
        'personalHubBookmarkCount', 'personalHubReminders', 'personalHubCountdowns',
        'personalHubHabits', 'personalHubBookmarks', 'addHubReminder',
        'addHubCountdown', 'addHubHabit', 'addHubBookmark', 'focusTimerDisplay',
        'focusTimerLabel', 'focusTimerStart', 'focusTimerPause', 'focusTimerReset',
        'focusPreset25', 'focusPreset5', 'focusPreset50', 'personalHubEditorDialog',
        'personalHubEditorForm', 'personalHubEditorMode', 'personalHubEditorHeading',
        'closePersonalHubEditor', 'personalHubEditorKind', 'personalHubEditorTitle',
        'personalHubEditorNote', 'personalHubReminderFields', 'personalHubDueAt',
        'personalHubCompleted', 'personalHubCountdownFields', 'personalHubTargetAt',
        'personalHubHabitFields', 'personalHubCadence', 'personalHubBookmarkFields',
        'personalHubBookmarkUrl', 'personalHubEditorStatus', 'cancelPersonalHubEditor',
        'savePersonalHubEditor',
    ]);

    const state = {
        generatedAt: '',
        counts: { total: 0, reminders: 0, countdowns: 0, habits: 0, bookmarks: 0 },
        items: [],
        loading: false,
        loadError: false,
        mutationBusy: false,
        generation: 0,
        editor: { id: '', detail: null },
        timer: null,
        timerInterval: null,
    };

    function object(value) { return value && typeof value === 'object' && !Array.isArray(value) ? value : null; }
    function byId(id) { return document.getElementById(id); }

    function plain(value, maximum = 160) {
        if (typeof value !== 'string' && typeof value !== 'number') return '';
        return String(value).replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, maximum);
    }

    function itemId(value) {
        return typeof value === 'string' && /^[0-9a-f]{32}$/.test(value) ? value : '';
    }

    function safeVersion(value) {
        return Number.isSafeInteger(value) && value >= 1 ? value : null;
    }

    function safeCount(value, maximum = MAX_ITEMS) {
        return Number.isSafeInteger(value) && value >= 0 && value <= maximum ? value : null;
    }

    function safeTimestamp(value) {
        if (typeof value !== 'string' || value.length > 40 || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return '';
        const parsed = new Date(value);
        return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString();
    }

    function safeTitle(value) {
        if (typeof value !== 'string' || /[\u0000-\u001f\u007f]/.test(value)) return '';
        const title = value.replace(/\s+/g, ' ').trim();
        return title && title.length <= 120 ? title : '';
    }

    function safeNote(value) {
        return typeof value === 'string'
            && value.length <= 1000
            && !/[\u0000-\u001f\u007f]/.test(value)
            ? value
            : null;
    }

    function safeDateKey(value) {
        if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return '';
        const [year, month, day] = value.split('-').map(Number);
        const parsed = new Date(Date.UTC(year, month - 1, day));
        return parsed.getUTCFullYear() === year
            && parsed.getUTCMonth() === month - 1
            && parsed.getUTCDate() === day
            ? value
            : '';
    }

    function safeCheckins(value) {
        if (!Array.isArray(value) || value.length > MAX_CHECKINS) return null;
        const normalized = value.map(safeDateKey);
        if (normalized.some(entry => !entry)) return null;
        const unique = new Set(normalized);
        if (unique.size !== normalized.length) return null;
        const sorted = [...normalized].sort();
        if (sorted.some((entry, index) => entry !== normalized[index])) return null;
        return Object.freeze(normalized);
    }

    function safeBookmarkUrl(value) {
        if (typeof value !== 'string'
            || !value
            || value.length > 2048
            || /[\u0000-\u0020\u007f]/.test(value)
            || value.includes('\\')) return '';
        try {
            const parsed = new URL(value);
            if (parsed.protocol !== 'https:' || !parsed.hostname || parsed.username || parsed.password) return '';
            return value;
        } catch (_error) {
            return '';
        }
    }

    function normalizeSummary(value) {
        const source = object(value);
        if (!source) return null;
        const id = itemId(source.id);
        const kind = KIND_SET.has(source.kind) ? source.kind : '';
        const title = safeTitle(source.title);
        const version = safeVersion(source.version);
        const createdAt = safeTimestamp(source.created_at);
        const updatedAt = safeTimestamp(source.updated_at);
        if (!id || !kind || !title || version === null || !createdAt || !updatedAt) return null;
        const common = { id, kind, title, version, created_at: createdAt, updated_at: updatedAt };
        if (kind === 'reminder') {
            const dueAt = safeTimestamp(source.due_at);
            return dueAt && typeof source.completed === 'boolean'
                ? Object.freeze({ ...common, due_at: dueAt, completed: source.completed })
                : null;
        }
        if (kind === 'countdown') {
            const targetAt = safeTimestamp(source.target_at);
            return targetAt ? Object.freeze({ ...common, target_at: targetAt }) : null;
        }
        if (kind === 'habit') {
            const checkins = safeCheckins(source.checkins);
            return CADENCE_SET.has(source.cadence) && checkins
                ? Object.freeze({ ...common, cadence: source.cadence, checkins })
                : null;
        }
        const url = safeBookmarkUrl(source.url);
        return url ? Object.freeze({ ...common, url }) : null;
    }

    function normalizeDetail(value) {
        const source = object(value);
        const summary = normalizeSummary(source);
        const note = safeNote(source?.note);
        return summary && note !== null ? Object.freeze({ ...summary, note }) : null;
    }

    function normalizeList(value) {
        const source = object(value);
        const counts = object(source?.counts);
        if (!source || !counts || !Array.isArray(source.items) || source.items.length > MAX_ITEMS) {
            throw new Error('Kasugai returned an invalid Personal Hub response.');
        }
        const generatedAt = safeTimestamp(source.generated_at);
        const normalizedCounts = {
            total: safeCount(counts.total),
            reminders: safeCount(counts.reminders),
            countdowns: safeCount(counts.countdowns),
            habits: safeCount(counts.habits),
            bookmarks: safeCount(counts.bookmarks),
        };
        const countValues = Object.values(normalizedCounts);
        if (!generatedAt
            || countValues.some(entry => entry === null)
            || normalizedCounts.reminders + normalizedCounts.countdowns
                + normalizedCounts.habits + normalizedCounts.bookmarks !== normalizedCounts.total
            || source.items.length !== normalizedCounts.total) {
            throw new Error('Kasugai returned invalid Personal Hub counts.');
        }
        const items = source.items.map(normalizeSummary);
        if (items.some(item => item === null)) {
            throw new Error('Kasugai returned an invalid Personal Hub item.');
        }
        return Object.freeze({
            generated_at: generatedAt,
            counts: Object.freeze(normalizedCounts),
            items: Object.freeze(items),
        });
    }

    function localDateTimeToIso(value) {
        if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$/.test(value)) return '';
        const [datePart, timePart] = value.split('T');
        const [year, month, day] = datePart.split('-').map(Number);
        const [hour, minute, second = 0] = timePart.split(':').map(Number);
        const parsed = new Date(year, month - 1, day, hour, minute, second, 0);
        if (Number.isNaN(parsed.getTime())
            || parsed.getFullYear() !== year
            || parsed.getMonth() !== month - 1
            || parsed.getDate() !== day
            || parsed.getHours() !== hour
            || parsed.getMinutes() !== minute
            || parsed.getSeconds() !== second) return '';
        return parsed.toISOString();
    }

    function isoToLocalDateTime(value) {
        const iso = safeTimestamp(value);
        if (!iso) return '';
        const date = new Date(iso);
        const part = number => String(number).padStart(2, '0');
        return `${date.getFullYear()}-${part(date.getMonth() + 1)}-${part(date.getDate())}`
            + `T${part(date.getHours())}:${part(date.getMinutes())}`;
    }

    function localDateKey(now = Date.now()) {
        const date = new Date(now);
        const part = number => String(number).padStart(2, '0');
        return `${date.getFullYear()}-${part(date.getMonth() + 1)}-${part(date.getDate())}`;
    }

    function validPreset(minutes) {
        return TIMER_PRESETS.includes(minutes) ? minutes : 25;
    }

    function createTimerState(minutes = 25) {
        const selected = validPreset(minutes);
        const duration = selected * 60 * 1000;
        return Object.freeze({
            minutes: selected,
            duration_ms: duration,
            remaining_ms: duration,
            deadline_ms: null,
            running: false,
        });
    }

    function timerRemaining(timer, now = Date.now()) {
        const source = object(timer);
        if (!source || !Number.isFinite(now)) return 0;
        const remaining = source.running
            ? Number(source.deadline_ms) - now
            : Number(source.remaining_ms);
        return Number.isFinite(remaining) ? Math.max(0, Math.min(source.duration_ms, remaining)) : 0;
    }

    function startTimer(timer, now = Date.now()) {
        const remaining = timerRemaining(timer, now) || timer.duration_ms;
        return Object.freeze({
            ...timer,
            remaining_ms: remaining,
            deadline_ms: now + remaining,
            running: true,
        });
    }

    function pauseTimer(timer, now = Date.now()) {
        return Object.freeze({
            ...timer,
            remaining_ms: timerRemaining(timer, now),
            deadline_ms: null,
            running: false,
        });
    }

    function resetTimer(timer, minutes = timer?.minutes || 25) {
        return createTimerState(minutes);
    }

    function formatTimer(milliseconds) {
        const totalSeconds = Math.max(0, Math.ceil(Number(milliseconds) / 1000));
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }

    function formatCountdown(target, now = Date.now()) {
        const iso = safeTimestamp(target);
        if (!iso) return 'Time unavailable';
        const remaining = new Date(iso).getTime() - now;
        if (remaining <= 0) return 'Reached';
        const seconds = Math.floor(remaining / 1000);
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;
        if (days) return `${days}d ${String(hours).padStart(2, '0')}h ${String(minutes).padStart(2, '0')}m`;
        if (hours) return `${hours}h ${String(minutes).padStart(2, '0')}m ${String(secs).padStart(2, '0')}s`;
        return `${minutes}m ${String(secs).padStart(2, '0')}s`;
    }

    function csrfToken() {
        return plain(document.querySelector('meta[name="kasugai-csrf-token"]')?.getAttribute('content'), 256);
    }

    async function responseJson(response) {
        if (response.redirected || response.status === 401) throw new Error('Your session expired. Sign in again.');
        if (response.status === 204) {
            if (!response.ok) throw new Error('Kasugai could not complete that Personal Hub request.');
            return null;
        }
        let payload;
        try { payload = await response.json(); }
        catch (_error) { throw new Error('Kasugai returned an invalid Personal Hub response.'); }
        if (!response.ok) {
            const error = new Error(plain(payload?.error, 240) || 'Kasugai could not complete that Personal Hub request.');
            error.status = response.status;
            error.conflict = response.status === 409;
            error.currentVersion = safeVersion(payload?.current_version);
            throw error;
        }
        return payload;
    }

    async function api(url, options = {}) {
        const method = String(options.method || 'GET').toUpperCase();
        const headers = { Accept: 'application/json' };
        let body;
        if (!['GET', 'HEAD'].includes(method)) {
            const token = csrfToken();
            if (!token) throw new Error('Reload this page before changing the Personal Hub.');
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

    function icon(name) {
        const element = document.createElement('i');
        element.setAttribute('data-lucide', name);
        element.setAttribute('aria-hidden', 'true');
        return element;
    }

    function refreshIcons() { if (window.lucide) window.lucide.createIcons(); }

    function setFeedback(message, tone = '') {
        const element = byId('personalHubFeedback');
        if (!element) return;
        element.textContent = plain(message, 300);
        element.dataset.tone = tone;
    }

    function setEditorFeedback(message, tone = '') {
        const element = byId('personalHubEditorStatus');
        if (!element) return;
        element.textContent = plain(message, 300);
        element.dataset.tone = tone;
    }

    function formatDate(value, includeTime = true) {
        const iso = safeTimestamp(value);
        if (!iso) return 'Time unavailable';
        const options = includeTime
            ? { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }
            : { month: 'short', day: 'numeric', year: 'numeric' };
        return new Intl.DateTimeFormat(undefined, options).format(new Date(iso));
    }

    function actionButton(label, iconName, handler, className = '') {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `personal-hub-item-action ${className}`.trim();
        button.setAttribute('aria-label', label);
        button.title = label;
        button.append(icon(iconName));
        button.addEventListener('click', handler);
        return button;
    }

    function emptyState(kind) {
        const empty = document.createElement('div');
        empty.className = 'personal-hub-empty';
        empty.append(icon({ reminder: 'bell', countdown: 'hourglass', habit: 'repeat-2', bookmark: 'bookmark' }[kind]));
        const text = document.createElement('p');
        text.textContent = `No ${kind === 'countdown' ? 'countdowns' : `${kind}s`} yet.`;
        empty.append(text);
        return empty;
    }

    function commonItem(item) {
        const article = document.createElement('article');
        article.className = `personal-hub-item is-${item.kind}`;
        const body = document.createElement('div');
        body.className = 'personal-hub-item-body';
        const title = document.createElement('strong');
        title.textContent = item.title;
        body.append(title);
        const meta = document.createElement('span');
        meta.className = 'personal-hub-item-meta';
        body.append(meta);
        const actions = document.createElement('div');
        actions.className = 'personal-hub-item-actions';
        actions.append(
            actionButton(`Edit ${item.title}`, 'pencil', () => openEditorForItem(item.id)),
            actionButton(`Delete ${item.title}`, 'trash-2', () => deleteItem(item), 'is-danger'),
        );
        article.append(body, actions);
        return { article, body, meta, actions };
    }

    function renderReminder(item) {
        const parts = commonItem(item);
        parts.article.classList.toggle('is-complete', item.completed);
        parts.meta.textContent = `${item.completed ? 'Completed' : 'Due'} · ${formatDate(item.due_at)}`;
        parts.actions.prepend(actionButton(
            item.completed ? `Reopen ${item.title}` : `Complete ${item.title}`,
            item.completed ? 'rotate-ccw' : 'check',
            () => patchItem(item, { completed: !item.completed }),
            item.completed ? '' : 'is-success',
        ));
        return parts.article;
    }

    function renderCountdown(item) {
        const parts = commonItem(item);
        parts.meta.classList.add('personal-hub-live-countdown');
        parts.meta.dataset.target = item.target_at;
        parts.meta.textContent = formatCountdown(item.target_at);
        const target = document.createElement('small');
        target.textContent = formatDate(item.target_at);
        parts.body.append(target);
        return parts.article;
    }

    function renderHabit(item) {
        const parts = commonItem(item);
        const today = localDateKey();
        const checked = item.checkins.includes(today);
        parts.article.classList.toggle('is-complete', checked);
        const cadence = { daily: 'Daily', weekdays: 'Weekdays', weekly: 'Weekly' }[item.cadence];
        parts.meta.textContent = `${cadence} · ${item.checkins.length} recent check-in${item.checkins.length === 1 ? '' : 's'}`;
        parts.actions.prepend(actionButton(
            checked ? `Undo today's check-in for ${item.title}` : `Check in to ${item.title}`,
            checked ? 'undo-2' : 'check-circle-2',
            () => toggleHabit(item, today),
            checked ? '' : 'is-success',
        ));
        return parts.article;
    }

    function renderBookmark(item) {
        const parts = commonItem(item);
        parts.meta.textContent = new URL(item.url).hostname;
        const anchor = document.createElement('a');
        anchor.className = 'personal-hub-bookmark-link';
        anchor.href = item.url;
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
        anchor.referrerPolicy = 'no-referrer';
        anchor.setAttribute('aria-label', `Open ${item.title} in a new tab`);
        anchor.append(icon('external-link'));
        parts.actions.prepend(anchor);
        return parts.article;
    }

    function renderCollection(containerId, items, kind) {
        const container = byId(containerId);
        if (!container) return;
        container.replaceChildren();
        if (!items.length) {
            container.append(emptyState(kind));
            return;
        }
        const renderer = {
            reminder: renderReminder,
            countdown: renderCountdown,
            habit: renderHabit,
            bookmark: renderBookmark,
        }[kind];
        items.forEach(item => container.append(renderer(item)));
    }

    function renderHub() {
        const counts = state.counts;
        byId('personalHubTotalCount').textContent = String(counts.total);
        byId('personalHubReminderCount').textContent = String(counts.reminders);
        byId('personalHubCountdownCount').textContent = String(counts.countdowns);
        byId('personalHubHabitCount').textContent = String(counts.habits);
        byId('personalHubBookmarkCount').textContent = String(counts.bookmarks);
        const grouped = Object.fromEntries(KINDS.map(kind => [kind, state.items.filter(item => item.kind === kind)]));
        grouped.reminder.sort((left, right) => Number(left.completed) - Number(right.completed)
            || new Date(left.due_at) - new Date(right.due_at));
        grouped.countdown.sort((left, right) => new Date(left.target_at) - new Date(right.target_at));
        grouped.habit.sort((left, right) => left.title.localeCompare(right.title));
        grouped.bookmark.sort((left, right) => left.title.localeCompare(right.title));
        renderCollection('personalHubReminders', grouped.reminder, 'reminder');
        renderCollection('personalHubCountdowns', grouped.countdown, 'countdown');
        renderCollection('personalHubHabits', grouped.habit, 'habit');
        renderCollection('personalHubBookmarks', grouped.bookmark, 'bookmark');
        const status = byId('personalHubStatus');
        status.textContent = state.loadError ? 'Unavailable' : (state.loading ? 'Loading' : `${counts.total} saved`);
        status.dataset.tone = state.loadError ? 'error' : (state.loading ? '' : 'success');
        updateCountdownDisplays();
        refreshIcons();
    }

    async function loadHub() {
        const generation = ++state.generation;
        state.loading = true;
        state.loadError = false;
        renderHub();
        try {
            const result = normalizeList(await api('/api/personal-hub'));
            if (generation !== state.generation) return;
            state.generatedAt = result.generated_at;
            state.counts = result.counts;
            state.items = [...result.items];
            setFeedback('');
        } catch (error) {
            if (generation !== state.generation) return;
            state.loadError = true;
            setFeedback(error.message, 'error');
        } finally {
            if (generation === state.generation) {
                state.loading = false;
                renderHub();
            }
        }
    }

    async function refreshAfterConflict(error, editing = false) {
        if (!error.conflict) throw error;
        await loadHub();
        if (editing && state.editor.id) {
            try {
                const detail = normalizeDetail(await api(`/api/personal-hub/items/${encodeURIComponent(state.editor.id)}`));
                if (detail) populateEditor(detail.kind, detail);
            } catch (_refreshError) {
                byId('personalHubEditorDialog').close();
            }
        }
        throw new Error('That item changed elsewhere. The latest version has been loaded.');
    }

    async function patchItem(item, changes) {
        if (state.mutationBusy) return;
        state.mutationBusy = true;
        try {
            await api(`/api/personal-hub/items/${encodeURIComponent(item.id)}`, {
                method: 'PATCH', body: { version: item.version, ...changes },
            });
            await loadHub();
        } catch (error) {
            try { await refreshAfterConflict(error); }
            catch (resolved) { setFeedback(resolved.message, 'error'); }
        } finally {
            state.mutationBusy = false;
        }
    }

    async function toggleHabit(item, date) {
        if (state.mutationBusy) return;
        state.mutationBusy = true;
        try {
            await api(`/api/personal-hub/items/${encodeURIComponent(item.id)}/check-in`, {
                method: 'POST', body: { version: item.version, date },
            });
            await loadHub();
        } catch (error) {
            try { await refreshAfterConflict(error); }
            catch (resolved) { setFeedback(resolved.message, 'error'); }
        } finally {
            state.mutationBusy = false;
        }
    }

    async function deleteItem(item) {
        if (state.mutationBusy || !window.confirm(`Delete “${item.title}”?`)) return;
        state.mutationBusy = true;
        try {
            await api(`/api/personal-hub/items/${encodeURIComponent(item.id)}`, {
                method: 'DELETE', body: { version: item.version },
            });
            await loadHub();
        } catch (error) {
            try { await refreshAfterConflict(error); }
            catch (resolved) { setFeedback(resolved.message, 'error'); }
        } finally {
            state.mutationBusy = false;
        }
    }

    function showKindFields(kind) {
        const mapping = {
            reminder: 'personalHubReminderFields', countdown: 'personalHubCountdownFields',
            habit: 'personalHubHabitFields', bookmark: 'personalHubBookmarkFields',
        };
        Object.entries(mapping).forEach(([name, id]) => { byId(id).hidden = name !== kind; });
    }

    function populateEditor(kind, detail = null) {
        const editing = Boolean(detail);
        state.editor = { id: detail?.id || '', detail };
        byId('personalHubEditorMode').textContent = editing ? 'Editing item' : 'New item';
        byId('personalHubEditorHeading').textContent = editing ? `Edit ${detail.title}` : 'Add to Personal Hub';
        byId('personalHubEditorKind').value = kind;
        byId('personalHubEditorKind').disabled = editing;
        byId('personalHubEditorTitle').value = detail?.title || '';
        byId('personalHubEditorNote').value = detail?.note || '';
        byId('personalHubDueAt').value = detail?.kind === 'reminder' ? isoToLocalDateTime(detail.due_at) : '';
        byId('personalHubCompleted').checked = detail?.kind === 'reminder' && detail.completed;
        byId('personalHubCompleted').disabled = !editing;
        byId('personalHubCompleted').closest('label').hidden = !editing;
        byId('personalHubTargetAt').value = detail?.kind === 'countdown' ? isoToLocalDateTime(detail.target_at) : '';
        byId('personalHubCadence').value = detail?.kind === 'habit' ? detail.cadence : 'daily';
        byId('personalHubBookmarkUrl').value = detail?.kind === 'bookmark' ? detail.url : '';
        showKindFields(kind);
        setEditorFeedback('');
    }

    function openNewEditor(kind = 'reminder') {
        populateEditor(KIND_SET.has(kind) ? kind : 'reminder');
        byId('personalHubEditorDialog').showModal();
        window.setTimeout(() => byId('personalHubEditorTitle').focus(), 0);
    }

    async function openEditorForItem(id) {
        if (state.mutationBusy) return;
        try {
            const detail = normalizeDetail(await api(`/api/personal-hub/items/${encodeURIComponent(id)}`));
            if (!detail) throw new Error('Kasugai returned an invalid Personal Hub item.');
            populateEditor(detail.kind, detail);
            byId('personalHubEditorDialog').showModal();
        } catch (error) {
            setFeedback(error.message, 'error');
        }
    }

    function editorPayload() {
        const kind = byId('personalHubEditorKind').value;
        const title = safeTitle(byId('personalHubEditorTitle').value);
        const note = safeNote(byId('personalHubEditorNote').value);
        if (!KIND_SET.has(kind) || !title) throw new Error('Enter a title up to 120 characters.');
        if (note === null) throw new Error('Notes must be a single line up to 1,000 characters.');
        const body = { kind, title, note };
        if (kind === 'reminder') {
            const dueAt = localDateTimeToIso(byId('personalHubDueAt').value);
            if (!dueAt) throw new Error('Choose a valid reminder date and time.');
            body.due_at = dueAt;
            body.completed = state.editor.detail
                ? byId('personalHubCompleted').checked
                : false;
        } else if (kind === 'countdown') {
            const targetAt = localDateTimeToIso(byId('personalHubTargetAt').value);
            if (!targetAt) throw new Error('Choose a valid countdown date and time.');
            body.target_at = targetAt;
        } else if (kind === 'habit') {
            const cadence = byId('personalHubCadence').value;
            if (!CADENCE_SET.has(cadence)) throw new Error('Choose a valid habit cadence.');
            body.cadence = cadence;
            body.checkins = state.editor.detail?.checkins ? [...state.editor.detail.checkins] : [];
        } else {
            const url = safeBookmarkUrl(byId('personalHubBookmarkUrl').value);
            if (!url) throw new Error('Enter a credential-free HTTPS bookmark URL.');
            body.url = url;
        }
        return body;
    }

    async function saveEditor(event) {
        event.preventDefault();
        if (state.mutationBusy) return;
        state.mutationBusy = true;
        byId('savePersonalHubEditor').disabled = true;
        try {
            const body = editorPayload();
            if (state.editor.detail) {
                const detail = state.editor.detail;
                const patchBody = { ...body, version: detail.version };
                delete patchBody.kind;
                if (detail.kind === 'habit') delete patchBody.checkins;
                await api(`/api/personal-hub/items/${encodeURIComponent(detail.id)}`, {
                    method: 'PATCH', body: patchBody,
                });
            } else {
                await api('/api/personal-hub/items', { method: 'POST', body });
            }
            byId('personalHubEditorDialog').close();
            await loadHub();
        } catch (error) {
            try { await refreshAfterConflict(error, true); }
            catch (resolved) { setEditorFeedback(resolved.message, 'error'); }
        } finally {
            state.mutationBusy = false;
            byId('savePersonalHubEditor').disabled = false;
        }
    }

    function timerLabel(minutes) {
        return { 5: 'Short break', 25: 'Focus', 50: 'Deep focus' }[minutes] || 'Focus';
    }

    function renderTimer(now = Date.now()) {
        if (!state.timer) state.timer = createTimerState(25);
        let remaining = timerRemaining(state.timer, now);
        if (state.timer.running && remaining <= 0) {
            state.timer = pauseTimer(state.timer, now);
            remaining = 0;
        }
        byId('focusTimerDisplay').textContent = formatTimer(remaining);
        byId('focusTimerLabel').textContent = remaining === 0 ? 'Complete' : timerLabel(state.timer.minutes);
        byId('focusTimerStart').disabled = state.timer.running;
        byId('focusTimerPause').disabled = !state.timer.running;
        [25, 5, 50].forEach(minutes => {
            const button = byId(`focusPreset${minutes}`);
            button.classList.toggle('is-active', state.timer.minutes === minutes);
            button.setAttribute('aria-pressed', state.timer.minutes === minutes ? 'true' : 'false');
        });
    }

    function updateCountdownDisplays(now = Date.now()) {
        document.querySelectorAll('.personal-hub-live-countdown[data-target]').forEach(element => {
            element.textContent = formatCountdown(element.dataset.target, now);
        });
    }

    function chooseTimer(minutes) {
        state.timer = resetTimer(state.timer, minutes);
        renderTimer();
    }

    function initialize() {
        if (typeof document === 'undefined' || !byId('personalHubModule')) return;
        const missing = REQUIRED_DOM_IDS.filter(id => !byId(id));
        if (missing.length) return;
        byId('refreshPersonalHub').addEventListener('click', loadHub);
        byId('addPersonalHubItem').addEventListener('click', () => openNewEditor('reminder'));
        byId('addHubReminder').addEventListener('click', () => openNewEditor('reminder'));
        byId('addHubCountdown').addEventListener('click', () => openNewEditor('countdown'));
        byId('addHubHabit').addEventListener('click', () => openNewEditor('habit'));
        byId('addHubBookmark').addEventListener('click', () => openNewEditor('bookmark'));
        byId('personalHubEditorKind').addEventListener('change', event => showKindFields(event.target.value));
        byId('personalHubEditorForm').addEventListener('submit', saveEditor);
        byId('closePersonalHubEditor').addEventListener('click', () => byId('personalHubEditorDialog').close());
        byId('cancelPersonalHubEditor').addEventListener('click', () => byId('personalHubEditorDialog').close());
        byId('focusTimerStart').addEventListener('click', () => {
            state.timer = startTimer(state.timer, Date.now());
            renderTimer();
        });
        byId('focusTimerPause').addEventListener('click', () => {
            state.timer = pauseTimer(state.timer, Date.now());
            renderTimer();
        });
        byId('focusTimerReset').addEventListener('click', () => {
            state.timer = resetTimer(state.timer);
            renderTimer();
        });
        byId('focusPreset25').addEventListener('click', () => chooseTimer(25));
        byId('focusPreset5').addEventListener('click', () => chooseTimer(5));
        byId('focusPreset50').addEventListener('click', () => chooseTimer(50));
        state.timer = createTimerState(25);
        renderTimer();
        state.timerInterval = window.setInterval(() => {
            renderTimer(Date.now());
            updateCountdownDisplays(Date.now());
        }, 250);
        loadHub();
    }

    const exported = {
        CADENCES,
        KINDS,
        REQUIRED_DOM_IDS,
        TIMER_PRESETS,
        createTimerState,
        formatCountdown,
        formatTimer,
        isoToLocalDateTime,
        localDateKey,
        localDateTimeToIso,
        normalizeDetail,
        normalizeList,
        normalizeSummary,
        pauseTimer,
        resetTimer,
        safeBookmarkUrl,
        safeCheckins,
        startTimer,
        timerRemaining,
    };

    if (typeof module !== 'undefined' && module.exports) module.exports = exported;
    if (typeof window !== 'undefined') window.KasugaiPersonalHub = Object.freeze(exported);
    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
        else initialize();
    }
}());
