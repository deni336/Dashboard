(function () {
    'use strict';

    const MODES = Object.freeze(['assistant', 'explain', 'review', 'refactor', 'tests', 'docs', 'regex', 'sql']);
    const MODE_SET = new Set(MODES);
    const MODE_LABELS = Object.freeze({
        assistant: 'Assistant', explain: 'Explain', review: 'Review', refactor: 'Refactor',
        tests: 'Tests', docs: 'Docs', regex: 'Regex', sql: 'SQL',
    });
    const MODE_DESCRIPTIONS = Object.freeze({
        assistant: 'General help', explain: 'Clarify text', review: 'Find issues', refactor: 'Improve structure',
        tests: 'Design tests', docs: 'Draft docs', regex: 'Pattern help', sql: 'Query help',
    });
    const MAX_SESSIONS = 30;
    const MAX_MESSAGES = 24;
    const MAX_TITLE_LENGTH = 100;
    const MAX_USER_BYTES = 16 * 1024;
    const MAX_ASSISTANT_BYTES = 32 * 1024;
    const state = {
        status: null,
        modes: [],
        sessions: [],
        detail: null,
        selectedId: '',
        indexLoading: false,
        mutationBusy: false,
        listGeneration: 0,
        detailGeneration: 0,
    };

    function byId(id) { return document.getElementById(id); }
    function object(value) { return value && typeof value === 'object' && !Array.isArray(value) ? value : null; }

    function plain(value, maximum = 160) {
        if (typeof value !== 'string' && typeof value !== 'number') return '';
        return String(value).replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, maximum);
    }

    function sessionId(value) {
        return typeof value === 'string' && /^[0-9a-f]{32}$/.test(value) ? value : '';
    }

    function safeVersion(value) {
        return Number.isSafeInteger(value) && value >= 1 ? value : null;
    }

    function safeCount(value, maximum = 1000000) {
        return Number.isSafeInteger(value) && value >= 0 && value <= maximum ? value : null;
    }

    function safeDate(value) {
        if (typeof value !== 'string') return '';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? '' : date.toISOString();
    }

    function byteLength(value) {
        return new TextEncoder().encode(String(value || '')).length;
    }

    function safeTitle(value) {
        if (typeof value !== 'string') return '';
        const title = value.replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim();
        return title && title.length <= MAX_TITLE_LENGTH ? title : '';
    }

    function safeModel(value) {
        if (typeof value !== 'string' || /[\u0000-\u001f\u007f]/.test(value)) return null;
        const model = value.trim();
        return model.length <= 200 ? model : null;
    }

    function safeContent(value, maximumBytes) {
        if (typeof value !== 'string' || !value.trim() || value.includes('\u0000') || byteLength(value) > maximumBytes) return null;
        return value.replace(/[\u0001-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, ' ');
    }

    function normalizeStatus(value) {
        const source = object(value);
        if (!source || typeof source.configured !== 'boolean' || source.provider !== 'ollama') return null;
        const model = safeModel(source.model);
        if (model === null || (source.configured && !model)) return null;
        return Object.freeze({ configured: source.configured, provider: 'ollama', model });
    }

    function normalizeModes(value) {
        if (!Array.isArray(value) || !value.length || value.length > MODES.length) return null;
        const modes = [];
        const seen = new Set();
        for (const mode of value) {
            if (!MODE_SET.has(mode) || seen.has(mode)) return null;
            seen.add(mode);
            modes.push(mode);
        }
        return Object.freeze(modes);
    }

    function normalizeSummary(value) {
        const source = object(value);
        if (!source) return null;
        const id = sessionId(source.id);
        const title = safeTitle(source.title);
        const mode = MODE_SET.has(source.mode) ? source.mode : '';
        const version = safeVersion(source.version);
        const messageCount = safeCount(source.message_count, MAX_MESSAGES);
        const createdAt = safeDate(source.created_at);
        const updatedAt = safeDate(source.updated_at);
        if (!id || !title || !mode || version === null || messageCount === null || !createdAt || !updatedAt) return null;
        return Object.freeze({
            id, title, mode, version, message_count: messageCount,
            created_at: createdAt, updated_at: updatedAt,
        });
    }

    function normalizeMessage(value) {
        const source = object(value);
        if (!source || !['user', 'assistant'].includes(source.role)) return null;
        const maximum = source.role === 'user' ? MAX_USER_BYTES : MAX_ASSISTANT_BYTES;
        const content = safeContent(source.content, maximum);
        return content === null ? null : Object.freeze({ role: source.role, content });
    }

    function normalizeDetail(value) {
        const source = object(value);
        if (!source || !Array.isArray(source.messages) || source.messages.length > MAX_MESSAGES) return null;
        const id = sessionId(source.id);
        const title = safeTitle(source.title);
        const mode = MODE_SET.has(source.mode) ? source.mode : '';
        const version = safeVersion(source.version);
        const createdAt = safeDate(source.created_at);
        const updatedAt = safeDate(source.updated_at);
        const messages = source.messages.map(normalizeMessage);
        if (!id || !title || !mode || version === null || !createdAt || !updatedAt || messages.some(message => message === null)) return null;
        return Object.freeze({
            id, title, mode, version, messages: Object.freeze(messages),
            created_at: createdAt, updated_at: updatedAt,
        });
    }

    function normalizeIndex(value) {
        const source = object(value);
        if (!source || !Array.isArray(source.sessions)) throw new Error('Kasugai returned an invalid Local AI response.');
        const status = normalizeStatus(source.status);
        const modes = normalizeModes(source.modes);
        if (!status || !modes) throw new Error('Kasugai returned an invalid Local AI response.');
        return Object.freeze({
            status,
            modes,
            sessions: Object.freeze(source.sessions.slice(0, MAX_SESSIONS).map(normalizeSummary).filter(Boolean)),
        });
    }

    function summaryFromDetail(detail) {
        return Object.freeze({
            id: detail.id,
            title: detail.title,
            mode: detail.mode,
            version: detail.version,
            message_count: detail.messages.length,
            created_at: detail.created_at,
            updated_at: detail.updated_at,
        });
    }

    function modeLabel(mode) { return MODE_LABELS[mode] || 'Assistant'; }

    function formatTime(value) {
        const date = new Date(String(value || ''));
        if (Number.isNaN(date.getTime())) return 'Time unavailable';
        return new Intl.DateTimeFormat(undefined, {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
        }).format(date);
    }

    function formatBytes(bytes) {
        if (bytes < 1024) return `${bytes} B`;
        return `${(bytes / 1024).toFixed(bytes >= 10240 ? 0 : 1)} KB`;
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
            if (!response.ok) throw new Error('Kasugai could not complete that Local AI request.');
            return null;
        }
        let payload;
        try { payload = await response.json(); }
        catch (_error) { throw new Error('Kasugai returned an invalid Local AI response.'); }
        if (!response.ok) {
            const error = new Error(plain(payload?.error, 240) || 'Kasugai could not complete that Local AI request.');
            error.status = response.status;
            error.conflict = response.status === 409;
            error.busy = response.status === 429;
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
            if (!token) throw new Error('Reload this page before changing Local AI sessions.');
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

    function setFeedback(message, kind = '') {
        const element = byId('aiToolboxFeedback');
        if (!element) return;
        element.textContent = message || '';
        element.classList.remove('success', 'error');
        if (kind) element.classList.add(kind);
        element.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    }

    function setDialogFeedback(message, kind = '') {
        const element = byId('aiSessionDialogStatus');
        if (!element) return;
        element.textContent = message || '';
        element.classList.remove('success', 'error');
        if (kind) element.classList.add(kind);
        element.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    }

    function renderReadiness() {
        const status = state.status;
        const badge = byId('aiReadinessState');
        const moduleStatus = byId('aiToolboxStatus');
        badge.classList.remove('is-ready', 'is-unconfigured');
        moduleStatus.classList.remove('is-ok', 'is-warning', 'is-error');
        if (!status) {
            byId('aiModelName').textContent = 'Configuration unavailable';
            byId('aiProviderName').textContent = 'Ollama · deployment controlled';
            byId('aiReadinessCopy').textContent = 'Refresh to check the local model configuration.';
            badge.textContent = 'Unknown';
            moduleStatus.textContent = 'Unavailable';
            moduleStatus.classList.add('is-error');
        } else if (status.configured) {
            byId('aiModelName').textContent = status.model;
            byId('aiProviderName').textContent = 'Ollama · deployment controlled';
            byId('aiReadinessCopy').textContent = 'A deployment-controlled local model is configured. Availability is verified when you send a message.';
            badge.textContent = 'Configured';
            badge.classList.add('is-ready');
            moduleStatus.textContent = 'Configured';
            moduleStatus.classList.add('is-ok');
        } else {
            byId('aiModelName').textContent = status.model || 'No local model configured';
            byId('aiProviderName').textContent = 'Ollama · deployment controlled';
            byId('aiReadinessCopy').textContent = 'Conversation history remains available, but sending is disabled until Local AI is configured.';
            badge.textContent = 'Setup needed';
            badge.classList.add('is-unconfigured');
            moduleStatus.textContent = 'Setup needed';
            moduleStatus.classList.add('is-warning');
        }
        updateComposer();
    }

    function renderModes() {
        const container = byId('aiModeChips');
        container.replaceChildren();
        state.modes.forEach(mode => {
            const chip = document.createElement('span');
            chip.className = `ai-mode-chip${state.detail?.mode === mode ? ' is-active' : ''}`;
            chip.textContent = modeLabel(mode);
            container.appendChild(chip);
        });
    }

    function emptyState(iconName, titleText, detailText) {
        const empty = document.createElement('div');
        empty.className = 'ai-empty-state';
        empty.appendChild(icon(iconName));
        const title = document.createElement('strong');
        title.textContent = titleText;
        const detail = document.createElement('p');
        detail.textContent = detailText;
        empty.append(title, detail);
        return empty;
    }

    function renderSessions() {
        const container = byId('aiSessionList');
        container.replaceChildren();
        container.setAttribute('aria-busy', state.indexLoading ? 'true' : 'false');
        byId('aiSessionCount').textContent = `${state.sessions.length} session${state.sessions.length === 1 ? '' : 's'}`;
        if (!state.sessions.length) {
            container.appendChild(emptyState('messages-square', 'No Local AI sessions', 'Start a focused session for explanations, reviews, tests, documentation, regex, or SQL help.'));
            refreshIcons();
            return;
        }
        state.sessions.forEach(session => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `ai-session-item${session.id === state.selectedId ? ' is-selected' : ''}`;
            button.setAttribute('role', 'option');
            button.setAttribute('aria-selected', session.id === state.selectedId ? 'true' : 'false');
            button.setAttribute('data-session-id', session.id);
            button.disabled = state.mutationBusy;
            button.appendChild((() => {
                const box = document.createElement('span');
                box.className = 'ai-session-icon';
                box.appendChild(icon(session.mode === 'assistant' ? 'message-circle' : 'sparkles'));
                return box;
            })());
            const copy = document.createElement('span');
            copy.className = 'ai-session-copy';
            const title = document.createElement('strong');
            title.textContent = session.title;
            const meta = document.createElement('span');
            meta.className = 'ai-session-meta';
            const mode = document.createElement('span');
            mode.className = 'ai-session-mode';
            mode.textContent = modeLabel(session.mode);
            const count = document.createElement('span');
            count.textContent = `${session.message_count} message${session.message_count === 1 ? '' : 's'}`;
            const time = document.createElement('span');
            time.className = 'ai-session-time';
            time.textContent = formatTime(session.updated_at);
            meta.append(mode, count, time);
            copy.append(title, meta);
            button.appendChild(copy);
            button.addEventListener('click', () => loadDetail(session.id));
            container.appendChild(button);
        });
        refreshIcons();
    }

    function copyButton(content) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'ai-copy-response';
        button.appendChild(icon('copy'));
        const label = document.createElement('span');
        label.textContent = 'Copy response';
        button.appendChild(label);
        button.addEventListener('click', () => copyResponse(content));
        return button;
    }

    async function copyResponse(content) {
        try {
            if (!navigator.clipboard?.writeText) throw new Error('Clipboard access is unavailable in this browser.');
            await navigator.clipboard.writeText(content);
            setFeedback('Assistant response copied to the clipboard.', 'success');
        } catch (error) {
            setFeedback(error.message, 'error');
        }
    }

    function renderMessages() {
        const container = byId('aiMessageList');
        container.replaceChildren();
        const detail = state.detail;
        if (!detail) {
            container.appendChild(emptyState('bot', 'Local conversation workspace', 'Choose a session from the rail or create a new one. Messages remain inert plain text in the browser.'));
        } else if (!detail.messages.length) {
            container.appendChild(emptyState('message-square-dashed', 'Start the conversation', `Use this ${modeLabel(detail.mode).toLocaleLowerCase()} session with only the text you choose to provide.`));
        } else {
            detail.messages.forEach(message => {
                const item = document.createElement('article');
                item.className = `ai-message is-${message.role}`;
                const heading = document.createElement('header');
                heading.className = 'ai-message-heading';
                const role = document.createElement('span');
                role.className = 'ai-message-role';
                role.textContent = message.role === 'assistant' ? 'Local assistant' : 'You';
                heading.appendChild(role);
                if (message.role === 'assistant') heading.appendChild(copyButton(message.content));
                const content = document.createElement('pre');
                content.className = 'ai-message-content';
                content.textContent = message.content;
                item.append(heading, content);
                container.appendChild(item);
            });
        }
        refreshIcons();
        container.scrollTop = container.scrollHeight;
    }

    function renderConversation() {
        const detail = state.detail;
        const deleteButton = byId('deleteAIToolboxSession');
        if (!detail) {
            byId('aiConversationMode').textContent = 'Conversation';
            byId('aiConversationTitle').textContent = 'Choose a session';
            byId('aiConversationMeta').textContent = 'Select an existing session or start a focused local conversation.';
            deleteButton.hidden = true;
        } else {
            byId('aiConversationMode').textContent = `${modeLabel(detail.mode)} mode`;
            byId('aiConversationTitle').textContent = detail.title;
            byId('aiConversationMeta').textContent = `${detail.messages.length} message${detail.messages.length === 1 ? '' : 's'} · version ${detail.version} · updated ${formatTime(detail.updated_at)}`;
            deleteButton.hidden = false;
        }
        renderModes();
        renderMessages();
        updateControls();
    }

    function updateComposer() {
        const input = byId('aiMessageInput');
        if (!input) return;
        const message = input.value;
        const bytes = byteLength(message);
        const meter = byId('aiMessageMeter');
        const fill = byId('aiMessageMeterFill');
        meter.setAttribute('aria-valuenow', String(Math.min(bytes, MAX_USER_BYTES)));
        meter.setAttribute('aria-valuetext', `${formatBytes(bytes)} of 16 KB`);
        fill.style.width = `${Math.min(100, (bytes / MAX_USER_BYTES) * 100)}%`;
        meter.classList.remove('is-warning', 'is-error');
        if (bytes > MAX_USER_BYTES) meter.classList.add('is-error');
        else if (bytes > MAX_USER_BYTES * .9) meter.classList.add('is-warning');
        byId('aiMessageSize').textContent = `${formatBytes(bytes)} of 16 KB`;

        const configured = state.status?.configured === true;
        const hasMessage = Boolean(message.trim()) && !message.includes('\u0000');
        const busy = state.mutationBusy || state.indexLoading;
        input.disabled = !state.detail || busy;
        byId('sendAIMessage').disabled = !state.detail || !configured || busy || !hasMessage || bytes > MAX_USER_BYTES;
        const hint = byId('aiComposerHint');
        hint.classList.remove('is-warning', 'is-error');
        if (!state.detail) hint.textContent = 'Select or create a session to begin.';
        else if (!configured) {
            hint.textContent = 'Send is disabled until an administrator configures the deployment-controlled local Ollama model. Sessions remain available.';
            hint.classList.add('is-warning');
        } else if (state.mutationBusy) hint.textContent = 'Local AI is working. This request returns as one complete plain-text response.';
        else if (bytes > MAX_USER_BYTES) {
            hint.textContent = 'Shorten this message to 16 KB or less after UTF-8 encoding.';
            hint.classList.add('is-error');
        } else hint.textContent = 'Plain text only · Ctrl/⌘ + Enter to send · no browsing, files, links, or tool execution.';
    }

    function updateControls() {
        const busy = state.mutationBusy || state.indexLoading;
        byId('refreshAIToolbox').disabled = busy;
        byId('newAIToolboxSession').disabled = busy || !state.modes.length;
        byId('deleteAIToolboxSession').disabled = busy || !state.detail;
        const create = byId('createAISession');
        if (create) create.disabled = state.mutationBusy;
        byId('aiSessionList')?.querySelectorAll('.ai-session-item').forEach(button => { button.disabled = state.mutationBusy; });
        updateComposer();
    }

    function upsertSession(detail) {
        const summary = summaryFromDetail(detail);
        state.sessions = [summary, ...state.sessions.filter(item => item.id !== summary.id)]
            .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
            .slice(0, MAX_SESSIONS);
    }

    function clearDetail() {
        state.detail = null;
        state.selectedId = '';
        renderSessions();
        renderConversation();
    }

    async function loadDetail(id) {
        const selected = sessionId(id);
        if (!selected || state.mutationBusy) return;
        const generation = ++state.detailGeneration;
        state.selectedId = selected;
        renderSessions();
        byId('aiMessageList').setAttribute('aria-busy', 'true');
        try {
            const detail = normalizeDetail(await api(`/api/ai-toolbox/sessions/${encodeURIComponent(selected)}`));
            if (!detail || detail.id !== selected) throw new Error('Kasugai returned an invalid AI session.');
            if (generation !== state.detailGeneration) return;
            state.detail = detail;
            upsertSession(detail);
            renderSessions();
            renderConversation();
            setFeedback('');
        } catch (error) {
            if (generation !== state.detailGeneration) return;
            setFeedback(error.message, 'error');
        } finally {
            if (generation === state.detailGeneration) byId('aiMessageList').setAttribute('aria-busy', 'false');
        }
    }

    async function loadIndex(preferredId = state.selectedId, announce = false) {
        if (state.indexLoading || state.mutationBusy) return;
        const generation = ++state.listGeneration;
        state.indexLoading = true;
        updateControls();
        byId('aiSessionList').setAttribute('aria-busy', 'true');
        try {
            const index = normalizeIndex(await api('/api/ai-toolbox'));
            if (generation !== state.listGeneration) return;
            state.status = index.status;
            state.modes = [...index.modes];
            state.sessions = [...index.sessions];
            renderReadiness();
            renderModes();
            const requested = sessionId(preferredId);
            const target = (requested && state.sessions.some(item => item.id === requested)) ? requested : (state.sessions[0]?.id || '');
            renderSessions();
            if (target) await loadDetail(target);
            else clearDetail();
            if (announce) setFeedback('Local AI Toolbox refreshed.', 'success');
        } catch (error) {
            if (generation !== state.listGeneration) return;
            state.status = null;
            renderReadiness();
            setFeedback(error.message, 'error');
        } finally {
            if (generation === state.listGeneration) {
                state.indexLoading = false;
                byId('aiSessionList').setAttribute('aria-busy', 'false');
                updateControls();
            }
        }
    }

    function renderDialogModes() {
        const container = byId('aiSessionModeOptions');
        container.replaceChildren();
        const preferred = state.detail?.mode && state.modes.includes(state.detail.mode) ? state.detail.mode : (state.modes.includes('assistant') ? 'assistant' : state.modes[0]);
        state.modes.forEach((mode, index) => {
            const label = document.createElement('label');
            label.className = 'ai-mode-option';
            const input = document.createElement('input');
            input.type = 'radio';
            input.name = 'aiSessionMode';
            input.value = mode;
            input.checked = mode === preferred || (!preferred && index === 0);
            const card = document.createElement('span');
            const title = document.createElement('strong');
            title.textContent = modeLabel(mode);
            const description = document.createElement('small');
            description.textContent = MODE_DESCRIPTIONS[mode];
            card.append(title, description);
            label.append(input, card);
            container.appendChild(label);
        });
    }

    function openNewSession() {
        if (state.mutationBusy || state.indexLoading || !state.modes.length) return;
        byId('aiSessionTitle').value = '';
        renderDialogModes();
        setDialogFeedback('');
        byId('aiSessionDialog').showModal();
        window.setTimeout(() => byId('aiSessionTitle')?.focus(), 0);
        refreshIcons();
    }

    async function createSession(event) {
        event.preventDefault();
        if (state.mutationBusy) return;
        const title = safeTitle(byId('aiSessionTitle').value);
        const mode = byId('aiSessionModeOptions').querySelector('input[name="aiSessionMode"]:checked')?.value || '';
        if (!title) {
            setDialogFeedback('Enter a session title using no more than 100 characters.', 'error');
            byId('aiSessionTitle').focus();
            return;
        }
        if (!MODE_SET.has(mode) || !state.modes.includes(mode)) {
            setDialogFeedback('Choose one of the available Local AI modes.', 'error');
            return;
        }
        state.mutationBusy = true;
        updateControls();
        setDialogFeedback('Creating encrypted session…');
        try {
            const detail = normalizeDetail(await api('/api/ai-toolbox/sessions', {
                method: 'POST', body: { title, mode },
            }));
            if (!detail) throw new Error('Kasugai returned an invalid created AI session.');
            state.detail = detail;
            state.selectedId = detail.id;
            upsertSession(detail);
            byId('aiSessionDialog').close();
            renderSessions();
            renderConversation();
            setFeedback('Local AI session created.', 'success');
            byId('aiMessageInput').focus();
        } catch (error) {
            setDialogFeedback(error.message, 'error');
        } finally {
            state.mutationBusy = false;
            updateControls();
        }
    }

    async function recoverConflict(id) {
        const current = sessionId(id);
        if (!current) return;
        const previousBusy = state.mutationBusy;
        state.mutationBusy = false;
        await loadDetail(current);
        state.mutationBusy = previousBusy;
        setFeedback('This session changed elsewhere. The latest version was loaded; your draft was kept so you can review it before trying again.', 'error');
    }

    async function sendMessage(event) {
        event.preventDefault();
        const detail = state.detail;
        if (!detail || state.mutationBusy || !state.status?.configured) {
            updateComposer();
            return;
        }
        const input = byId('aiMessageInput');
        const message = input.value;
        const bytes = byteLength(message);
        if (!message.trim() || message.includes('\u0000')) {
            setFeedback('Enter a plain-text message before sending.', 'error');
            return;
        }
        if (bytes > MAX_USER_BYTES) {
            setFeedback('Shorten this message to 16 KB or less after UTF-8 encoding.', 'error');
            updateComposer();
            return;
        }
        state.mutationBusy = true;
        byId('aiMessageList').setAttribute('aria-busy', 'true');
        updateControls();
        setFeedback('Waiting for the local model…');
        try {
            const saved = normalizeDetail(await api(`/api/ai-toolbox/sessions/${encodeURIComponent(detail.id)}/messages`, {
                method: 'POST', body: { version: detail.version, message },
            }));
            if (!saved || saved.id !== detail.id) throw new Error('Kasugai returned an invalid AI response.');
            state.detail = saved;
            state.selectedId = saved.id;
            upsertSession(saved);
            input.value = '';
            renderSessions();
            renderConversation();
            setFeedback('Local response received.', 'success');
            input.focus();
        } catch (error) {
            if (error.conflict) await recoverConflict(detail.id);
            else if (error.busy) setFeedback('Local AI is busy. Your draft was kept; try again in a moment.', 'error');
            else setFeedback(`${error.message} Your draft was kept.`, 'error');
        } finally {
            state.mutationBusy = false;
            byId('aiMessageList').setAttribute('aria-busy', 'false');
            updateControls();
        }
    }

    async function deleteSession() {
        const detail = state.detail;
        if (!detail || state.mutationBusy || !window.confirm(`Delete the Local AI session "${detail.title}"?`)) return;
        state.mutationBusy = true;
        updateControls();
        try {
            await api(`/api/ai-toolbox/sessions/${encodeURIComponent(detail.id)}`, {
                method: 'DELETE', body: { version: detail.version },
            });
            state.sessions = state.sessions.filter(session => session.id !== detail.id);
            state.detail = null;
            state.selectedId = '';
            const next = state.sessions[0]?.id || '';
            renderSessions();
            renderConversation();
            state.mutationBusy = false;
            if (next) await loadDetail(next);
            setFeedback('Local AI session deleted.', 'success');
        } catch (error) {
            if (error.conflict) await recoverConflict(detail.id);
            else setFeedback(error.message, 'error');
        } finally {
            state.mutationBusy = false;
            updateControls();
        }
    }

    function navigateSessionList(event) {
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        const buttons = [...byId('aiSessionList').querySelectorAll('.ai-session-item:not(:disabled)')];
        if (!buttons.length) return;
        let index = buttons.indexOf(document.activeElement);
        if (event.key === 'Home') index = 0;
        else if (event.key === 'End') index = buttons.length - 1;
        else if (event.key === 'ArrowDown') index = Math.min(buttons.length - 1, index + 1);
        else index = Math.max(0, index < 0 ? 0 : index - 1);
        event.preventDefault();
        buttons[index].focus();
    }

    function initialize() {
        if (!byId('aiToolboxModule')) return;
        renderReadiness();
        renderModes();
        renderSessions();
        renderConversation();
        byId('newAIToolboxSession').addEventListener('click', openNewSession);
        byId('refreshAIToolbox').addEventListener('click', () => loadIndex(state.selectedId, true));
        byId('deleteAIToolboxSession').addEventListener('click', deleteSession);
        byId('aiMessageForm').addEventListener('submit', sendMessage);
        byId('aiMessageInput').addEventListener('input', updateComposer);
        byId('aiMessageInput').addEventListener('keydown', event => {
            if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
                event.preventDefault();
                byId('aiMessageForm').requestSubmit();
            } else if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 'k') {
                event.preventDefault();
                event.stopPropagation();
            }
        });
        byId('aiSessionList').addEventListener('keydown', navigateSessionList);
        byId('aiSessionForm').addEventListener('submit', createSession);
        byId('closeAISessionDialog').addEventListener('click', () => byId('aiSessionDialog').close());
        byId('cancelAISession').addEventListener('click', () => byId('aiSessionDialog').close());
        byId('aiSessionDialog').addEventListener('cancel', event => { if (state.mutationBusy) event.preventDefault(); });
        byId('aiSessionDialog').addEventListener('keydown', event => {
            if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
                event.preventDefault();
                byId('aiSessionForm').requestSubmit();
            } else if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 'k') {
                event.preventDefault();
                event.stopPropagation();
            }
        });
        loadIndex();
    }

    if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initialize);
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            MAX_ASSISTANT_BYTES,
            MAX_USER_BYTES,
            MODES,
            byteLength,
            normalizeDetail,
            normalizeIndex,
            normalizeMessage,
            normalizeModes,
            normalizeStatus,
            normalizeSummary,
            safeContent,
            sessionId,
        };
    }
})();
