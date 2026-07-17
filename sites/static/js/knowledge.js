(function () {
    'use strict';

    const LANGUAGES = Object.freeze([
        'text', 'markdown', 'python', 'javascript', 'typescript', 'powershell', 'shell',
        'sql', 'json', 'yaml', 'html', 'css', 'go', 'rust', 'java', 'csharp', 'cpp',
    ]);
    const LANGUAGE_SET = new Set(LANGUAGES);
    const NOTE_LANGUAGES = new Set(['text', 'markdown']);
    const KINDS = new Set(['note', 'snippet']);
    const MAX_CONTENT_BYTES = 64 * 1024;
    const state = {
        items: [],
        detail: null,
        counts: { total: 0, notes: 0, snippets: 0, pinned: 0 },
        tags: [],
        languages: [],
        selectedId: '',
        filters: { q: '', kind: 'all', tag: '', pinned: 'all' },
        busy: false,
        listGeneration: 0,
        detailGeneration: 0,
        searchTimer: null,
    };

    function byId(id) { return document.getElementById(id); }
    function object(value) { return value && typeof value === 'object' && !Array.isArray(value) ? value : null; }

    function plain(value, maximum = 160) {
        if (typeof value !== 'string' && typeof value !== 'number') return '';
        return String(value).replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, maximum);
    }

    function itemId(value) {
        return typeof value === 'string' && /^[A-Za-z0-9_-]{16,64}$/.test(value) ? value : '';
    }

    function safeVersion(value) {
        return Number.isSafeInteger(value) && value >= 1 ? value : null;
    }

    function safeDate(value) {
        if (typeof value !== 'string') return '';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? '' : date.toISOString();
    }

    function byteLength(value) {
        return new TextEncoder().encode(String(value || '')).length;
    }

    function safeContent(value) {
        if (typeof value !== 'string' || byteLength(value) > MAX_CONTENT_BYTES) return null;
        return value.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, ' ');
    }

    function normalizeTag(value) {
        if (typeof value !== 'string') return '';
        const tag = value.trim();
        if (!tag || tag.length > 32 || /[\u0000-\u001f\u007f,]/.test(tag)) return '';
        return tag;
    }

    function normalizeTags(values) {
        if (!Array.isArray(values) || values.length > 12) return null;
        const tags = [];
        const seen = new Set();
        for (const value of values) {
            const tag = normalizeTag(value);
            const key = tag.toLocaleLowerCase();
            if (!tag || seen.has(key)) return null;
            seen.add(key);
            tags.push(tag);
        }
        return Object.freeze(tags);
    }

    function parseTags(value) {
        if (typeof value !== 'string') throw new Error('Tags must be comma-separated text.');
        const tags = [];
        const seen = new Set();
        for (const raw of value.split(',')) {
            if (!raw.trim()) continue;
            const tag = normalizeTag(raw);
            if (!tag) throw new Error('Each tag must be printable text up to 32 characters and cannot contain commas.');
            const key = tag.toLocaleLowerCase();
            if (seen.has(key)) continue;
            seen.add(key);
            tags.push(tag);
            if (tags.length > 12) throw new Error('Use no more than 12 tags.');
        }
        return tags;
    }

    function normalizeSummary(value) {
        const source = object(value);
        if (!source) return null;
        const id = itemId(source.id);
        const kind = KINDS.has(source.kind) ? source.kind : '';
        const title = typeof source.title === 'string' ? plain(source.title, 160) : '';
        const preview = typeof source.preview === 'string' ? plain(source.preview, 240) : null;
        const language = LANGUAGE_SET.has(source.language) ? source.language : '';
        const tags = normalizeTags(source.tags);
        const version = safeVersion(source.version);
        const createdAt = safeDate(source.created_at);
        const updatedAt = safeDate(source.updated_at);
        if (!id || !kind || !title || preview === null || !language || !tags || typeof source.pinned !== 'boolean' || version === null || !createdAt || !updatedAt || (kind === 'note' && !NOTE_LANGUAGES.has(language))) return null;
        return Object.freeze({
            id,
            kind,
            title,
            preview,
            language,
            tags,
            pinned: source.pinned === true,
            version,
            created_at: createdAt,
            updated_at: updatedAt,
        });
    }

    function normalizeFull(value) {
        const summary = normalizeSummary(value);
        const content = safeContent(object(value)?.content);
        return summary && content !== null ? Object.freeze({ ...summary, content }) : null;
    }

    function nonnegativeCount(value) {
        return Number.isSafeInteger(value) && value >= 0 ? Math.min(value, 1000000) : null;
    }

    function normalizeTagCount(value) {
        const source = object(value);
        if (!source) return null;
        const name = normalizeTag(source.name);
        const count = nonnegativeCount(source.count);
        return name && count !== null ? Object.freeze({ name, count }) : null;
    }

    function normalizeList(payload) {
        const source = object(payload);
        const counts = object(source?.counts);
        if (!source || !Array.isArray(source.items) || !counts || !Array.isArray(source.tags) || !Array.isArray(source.languages)) {
            throw new Error('Kasugai returned an invalid knowledge response.');
        }
        const total = nonnegativeCount(counts.total);
        const notes = nonnegativeCount(counts.notes);
        const snippets = nonnegativeCount(counts.snippets);
        const pinned = nonnegativeCount(counts.pinned);
        if ([total, notes, snippets, pinned].some(value => value === null) || notes + snippets !== total || pinned > total) throw new Error('Kasugai returned invalid knowledge counts.');
        return Object.freeze({
            items: Object.freeze(source.items.slice(0, 500).map(normalizeSummary).filter(Boolean)),
            counts: Object.freeze({ total, notes, snippets, pinned }),
            tags: Object.freeze(source.tags.slice(0, 500).map(normalizeTagCount).filter(Boolean)),
            languages: Object.freeze([...new Set(source.languages.filter(language => LANGUAGE_SET.has(language)))]),
        });
    }

    function formatTime(value) {
        const date = new Date(String(value || ''));
        if (Number.isNaN(date.getTime())) return 'Time unavailable';
        return new Intl.DateTimeFormat(undefined, {
            month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit',
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
            if (!response.ok) throw new Error('Kasugai could not complete that knowledge request.');
            return null;
        }
        let payload;
        try { payload = await response.json(); }
        catch (_error) { throw new Error('Kasugai returned an invalid knowledge response.'); }
        if (!response.ok) {
            const error = new Error(plain(payload?.error, 240) || 'Kasugai could not complete that knowledge request.');
            error.conflict = response.status === 409;
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
            if (!token) throw new Error('Reload this page before changing the knowledge vault.');
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
        const element = byId('knowledgeFeedback');
        if (!element) return;
        element.textContent = message || '';
        element.classList.remove('success', 'error');
        if (kind) element.classList.add(kind);
        element.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    }

    function setEditorFeedback(message, kind) {
        const element = byId('knowledgeEditorStatus');
        if (!element) return;
        element.textContent = message || '';
        element.classList.remove('success', 'error');
        if (kind) element.classList.add(kind);
        element.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    }

    function setSummary() {
        byId('knowledgeTotalCount').textContent = String(state.counts.total);
        byId('knowledgeNoteCount').textContent = String(state.counts.notes);
        byId('knowledgeSnippetCount').textContent = String(state.counts.snippets);
        byId('knowledgePinnedCount').textContent = String(state.counts.pinned);
        byId('knowledgeResultCount').textContent = `${state.items.length} entr${state.items.length === 1 ? 'y' : 'ies'}`;
        const status = byId('knowledgeStatus');
        status.textContent = state.counts.total ? `${state.counts.total} entries` : 'Vault is empty';
        status.classList.remove('is-ok', 'is-warning', 'is-error');
        if (state.counts.total) status.classList.add('is-ok');
    }

    function renderTagFilter() {
        const select = byId('knowledgeTagFilter');
        if (!select) return;
        const desired = state.filters.tag;
        select.replaceChildren();
        const all = document.createElement('option');
        all.value = '';
        all.textContent = 'All tags';
        select.appendChild(all);
        state.tags.forEach(tag => {
            const option = document.createElement('option');
            option.value = tag.name;
            option.textContent = `${tag.name} (${tag.count})`;
            select.appendChild(option);
        });
        if (desired && !state.tags.some(tag => tag.name === desired)) {
            const current = document.createElement('option');
            current.value = desired;
            current.textContent = desired;
            select.appendChild(current);
        }
        select.value = desired;
    }

    function listItem(item) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `knowledge-list-item${state.selectedId === item.id ? ' is-selected' : ''}`;
        button.setAttribute('aria-pressed', String(state.selectedId === item.id));
        const iconBox = document.createElement('span');
        iconBox.className = `knowledge-list-icon is-${item.kind}`;
        iconBox.appendChild(icon(item.kind === 'note' ? 'notebook-pen' : 'code-2'));
        const copy = document.createElement('span');
        copy.className = 'knowledge-list-copy';
        const titleRow = document.createElement('span');
        titleRow.className = 'knowledge-list-title';
        const title = document.createElement('strong');
        title.textContent = item.title;
        titleRow.appendChild(title);
        if (item.pinned) titleRow.appendChild(icon('pin'));
        const preview = document.createElement('p');
        preview.textContent = item.preview || 'No preview available.';
        const meta = document.createElement('span');
        meta.className = 'knowledge-list-meta';
        const language = document.createElement('span');
        language.textContent = item.language;
        meta.appendChild(language);
        item.tags.slice(0, 3).forEach(tag => {
            const badge = document.createElement('span');
            badge.textContent = tag;
            meta.appendChild(badge);
        });
        copy.append(titleRow, preview, meta);
        const updated = document.createElement('span');
        updated.className = 'knowledge-list-updated';
        updated.textContent = formatTime(item.updated_at);
        button.append(iconBox, copy, updated);
        button.addEventListener('click', () => selectItem(item.id));
        button.addEventListener('keydown', moveListFocus);
        return button;
    }

    function moveListFocus(event) {
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        const buttons = [...document.querySelectorAll('#knowledgeItemList .knowledge-list-item')];
        const current = buttons.indexOf(event.currentTarget);
        if (current < 0 || !buttons.length) return;
        event.preventDefault();
        const index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
        buttons[index].focus();
    }

    function renderList() {
        const container = byId('knowledgeItemList');
        if (!container) return;
        container.replaceChildren();
        container.setAttribute('aria-busy', 'false');
        if (!state.items.length) {
            const filtered = state.filters.q || state.filters.kind !== 'all' || state.filters.tag || state.filters.pinned !== 'all';
            const empty = document.createElement('div');
            empty.className = 'knowledge-empty-state';
            empty.appendChild(icon(filtered ? 'search-x' : 'library-big'));
            const title = document.createElement('strong');
            title.textContent = filtered ? 'No entries match these filters' : 'Your vault is ready';
            const copy = document.createElement('p');
            copy.textContent = filtered ? 'Try a shorter search or clear a kind, tag, or pin filter.' : 'Capture durable notes and reusable snippets without sending their content anywhere else.';
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'app-button app-button-primary';
            button.textContent = 'New entry';
            button.addEventListener('click', openNewEditor);
            empty.append(title, copy, button);
            container.appendChild(empty);
        } else state.items.forEach(item => container.appendChild(listItem(item)));
        setSummary();
        refreshIcons();
    }

    function renderDetail() {
        const detail = state.detail;
        byId('knowledgeDetailEmpty').hidden = Boolean(detail);
        byId('knowledgeDetail').hidden = !detail;
        if (!detail) return;
        const kind = byId('knowledgeDetailKind');
        kind.textContent = detail.kind;
        kind.className = `knowledge-kind-badge is-${detail.kind}`;
        byId('knowledgeDetailTitle').textContent = detail.title;
        byId('knowledgeDetailMeta').textContent = `${detail.language} · updated ${formatTime(detail.updated_at)} · version ${detail.version}`;
        const tags = byId('knowledgeDetailTags');
        tags.replaceChildren();
        detail.tags.forEach(tag => {
            const badge = document.createElement('span');
            badge.textContent = tag;
            tags.appendChild(badge);
        });
        const content = byId('knowledgeContent');
        content.textContent = detail.content;
        content.className = `knowledge-content is-${detail.kind}`;
        const pin = byId('knowledgePinItem');
        pin.setAttribute('aria-pressed', String(detail.pinned));
        pin.setAttribute('aria-label', detail.pinned ? 'Unpin entry' : 'Pin entry');
        pin.title = detail.pinned ? 'Unpin entry' : 'Pin entry';
        pin.classList.toggle('is-active', detail.pinned);
        refreshIcons();
    }

    function clearDetail() {
        state.selectedId = '';
        state.detail = null;
        renderList();
        renderDetail();
    }

    function listUrl() {
        const params = new URLSearchParams();
        if (state.filters.q) params.set('q', state.filters.q);
        if (state.filters.kind !== 'all') params.set('kind', state.filters.kind);
        if (state.filters.tag) params.set('tag', state.filters.tag);
        if (state.filters.pinned !== 'all') params.set('pinned', state.filters.pinned);
        const query = params.toString();
        return query ? `/api/knowledge?${query}` : '/api/knowledge';
    }

    async function loadDetail(id) {
        if (!itemId(id)) return;
        const generation = ++state.detailGeneration;
        try {
            const detail = normalizeFull(await api(`/api/knowledge/${encodeURIComponent(id)}`));
            if (!detail) throw new Error('Kasugai returned an invalid knowledge entry.');
            if (generation !== state.detailGeneration || state.selectedId !== id) return;
            state.detail = detail;
            renderDetail();
        } catch (error) {
            if (generation !== state.detailGeneration) return;
            state.detail = null;
            renderDetail();
            setFeedback(error.message, 'error');
        }
    }

    function selectItem(id) {
        if (!state.items.some(item => item.id === id)) return;
        state.selectedId = id;
        state.detail = null;
        renderList();
        renderDetail();
        loadDetail(id);
    }

    async function loadList(preferredId = '') {
        const generation = ++state.listGeneration;
        byId('knowledgeItemList')?.setAttribute('aria-busy', 'true');
        try {
            const payload = normalizeList(await api(listUrl()));
            if (generation !== state.listGeneration) return;
            state.items = [...payload.items];
            state.counts = payload.counts;
            state.tags = [...payload.tags];
            state.languages = [...payload.languages];
            renderTagFilter();
            const target = [preferredId, state.selectedId, state.items[0]?.id].find(id => id && state.items.some(item => item.id === id)) || '';
            state.selectedId = target;
            if (!target) state.detail = null;
            renderList();
            renderDetail();
            setFeedback('');
            if (target) await loadDetail(target);
        } catch (error) {
            if (generation !== state.listGeneration) return;
            byId('knowledgeItemList')?.setAttribute('aria-busy', 'false');
            const status = byId('knowledgeStatus');
            status.textContent = 'Unavailable';
            status.classList.remove('is-ok', 'is-warning');
            status.classList.add('is-error');
            setFeedback(error.message, 'error');
        }
    }

    function allowedLanguages(kind) {
        return kind === 'note' ? LANGUAGES.filter(language => NOTE_LANGUAGES.has(language)) : LANGUAGES;
    }

    function renderLanguageOptions(selected = '') {
        const select = byId('knowledgeEditorLanguage');
        const kind = byId('knowledgeEditorKind').value;
        const options = allowedLanguages(kind);
        const desired = options.includes(selected) ? selected : options.includes(select.value) ? select.value : 'text';
        select.replaceChildren();
        options.forEach(language => {
            const option = document.createElement('option');
            option.value = language;
            option.textContent = language;
            select.appendChild(option);
        });
        select.value = desired;
    }

    function updateEditorSize() {
        const bytes = byteLength(byId('knowledgeEditorContent')?.value || '');
        const element = byId('knowledgeEditorSize');
        element.textContent = `${formatBytes(bytes)} of 64 KB`;
        element.classList.remove('is-warning', 'is-error');
        if (bytes > MAX_CONTENT_BYTES) element.classList.add('is-error');
        else if (bytes > MAX_CONTENT_BYTES * .9) element.classList.add('is-warning');
    }

    function openNewEditor() {
        const form = byId('knowledgeEditorForm');
        form.reset();
        form.removeAttribute('data-edit-id');
        form.removeAttribute('data-version');
        byId('knowledgeEditorKind').value = 'note';
        renderLanguageOptions('text');
        byId('knowledgeEditorMode').textContent = 'New entry';
        byId('knowledgeEditorTitle').textContent = 'Add to Knowledge Vault';
        byId('saveKnowledgeLabel').textContent = 'Save entry';
        setEditorFeedback('');
        updateEditorSize();
        byId('knowledgeEditorDialog').showModal();
        window.setTimeout(() => byId('knowledgeEditorTitleInput').focus(), 0);
        refreshIcons();
    }

    function fillEditor(detail) {
        const form = byId('knowledgeEditorForm');
        form.setAttribute('data-edit-id', detail.id);
        form.setAttribute('data-version', String(detail.version));
        byId('knowledgeEditorKind').value = detail.kind;
        renderLanguageOptions(detail.language);
        byId('knowledgeEditorTitleInput').value = detail.title;
        byId('knowledgeEditorTags').value = detail.tags.join(', ');
        byId('knowledgeEditorContent').value = detail.content;
        byId('knowledgeEditorPinned').checked = detail.pinned;
        byId('knowledgeEditorMode').textContent = 'Editing entry';
        byId('knowledgeEditorTitle').textContent = 'Edit Knowledge Vault entry';
        byId('saveKnowledgeLabel').textContent = 'Save changes';
        setEditorFeedback('');
        updateEditorSize();
    }

    function openEditEditor() {
        if (!state.detail) return;
        fillEditor(state.detail);
        byId('knowledgeEditorDialog').showModal();
        window.setTimeout(() => byId('knowledgeEditorTitleInput').focus(), 0);
        refreshIcons();
    }

    function editorBody() {
        const kind = byId('knowledgeEditorKind').value;
        const title = plain(byId('knowledgeEditorTitleInput').value, 160);
        const content = byId('knowledgeEditorContent').value;
        const language = byId('knowledgeEditorLanguage').value;
        if (!KINDS.has(kind)) throw new Error('Choose note or snippet.');
        if (!title) throw new Error('Enter a title.');
        if (!content) throw new Error('Enter note or snippet content.');
        if (byteLength(content) > MAX_CONTENT_BYTES) throw new Error('Content must be 64 KB or smaller after UTF-8 encoding.');
        if (!LANGUAGE_SET.has(language) || (kind === 'note' && !NOTE_LANGUAGES.has(language))) throw new Error('Choose a valid language for this entry.');
        return {
            kind,
            title,
            content,
            language,
            tags: parseTags(byId('knowledgeEditorTags').value),
            pinned: byId('knowledgeEditorPinned').checked === true,
        };
    }

    async function recoverConflict(id, editorOpen) {
        await loadList(id);
        if (editorOpen && state.detail?.id === id) fillEditor(state.detail);
        const message = 'This entry changed in another session. The latest version was loaded; review it before trying again.';
        if (editorOpen) setEditorFeedback(message, 'error');
        else setFeedback(message, 'error');
    }

    async function saveEditor(event) {
        event.preventDefault();
        if (state.busy) return;
        const form = byId('knowledgeEditorForm');
        const editId = itemId(form.getAttribute('data-edit-id'));
        const version = Number(form.getAttribute('data-version'));
        const button = byId('saveKnowledgeItem');
        state.busy = true;
        button.disabled = true;
        try {
            const body = editorBody();
            let saved;
            if (editId) {
                if (safeVersion(version) === null) throw new Error('Refresh this entry before editing it.');
                saved = normalizeFull(await api(`/api/knowledge/${encodeURIComponent(editId)}`, { method: 'PATCH', body: { ...body, version } }));
            } else saved = normalizeFull(await api('/api/knowledge', { method: 'POST', body }));
            if (!saved) throw new Error('Kasugai returned an invalid saved entry.');
            byId('knowledgeEditorDialog').close();
            await loadList(saved.id);
            setFeedback(editId ? 'Entry updated.' : 'Entry created.', 'success');
        } catch (error) {
            if (error.conflict && editId) await recoverConflict(editId, true);
            else setEditorFeedback(error.message, 'error');
        } finally {
            state.busy = false;
            button.disabled = false;
        }
    }

    async function togglePin() {
        const detail = state.detail;
        if (!detail || state.busy) return;
        state.busy = true;
        byId('knowledgePinItem').disabled = true;
        try {
            const saved = normalizeFull(await api(`/api/knowledge/${encodeURIComponent(detail.id)}`, {
                method: 'PATCH', body: { pinned: !detail.pinned, version: detail.version },
            }));
            if (!saved) throw new Error('Kasugai returned an invalid updated entry.');
            await loadList(saved.id);
            setFeedback(saved.pinned ? 'Entry pinned.' : 'Entry unpinned.', 'success');
        } catch (error) {
            if (error.conflict) await recoverConflict(detail.id, false);
            else setFeedback(error.message, 'error');
        } finally {
            state.busy = false;
            byId('knowledgePinItem').disabled = false;
        }
    }

    async function duplicateItem() {
        const detail = state.detail;
        if (!detail || state.busy) return;
        state.busy = true;
        byId('duplicateKnowledgeItem').disabled = true;
        try {
            const duplicate = normalizeFull(await api(`/api/knowledge/${encodeURIComponent(detail.id)}/duplicate`, { method: 'POST', body: {} }));
            if (!duplicate) throw new Error('Kasugai returned an invalid duplicated entry.');
            await loadList(duplicate.id);
            setFeedback('Entry duplicated.', 'success');
        } catch (error) { setFeedback(error.message, 'error'); }
        finally { state.busy = false; byId('duplicateKnowledgeItem').disabled = false; }
    }

    async function deleteItem() {
        const detail = state.detail;
        if (!detail || state.busy || !window.confirm(`Delete "${detail.title}" from the Knowledge Vault?`)) return;
        state.busy = true;
        byId('deleteKnowledgeItem').disabled = true;
        try {
            await api(`/api/knowledge/${encodeURIComponent(detail.id)}`, { method: 'DELETE', body: { version: detail.version } });
            clearDetail();
            await loadList();
            setFeedback('Entry deleted.', 'success');
        } catch (error) {
            if (error.conflict) await recoverConflict(detail.id, false);
            else setFeedback(error.message, 'error');
        } finally { state.busy = false; byId('deleteKnowledgeItem').disabled = false; }
    }

    async function copyItem() {
        const detail = state.detail;
        if (!detail) return;
        try {
            if (!navigator.clipboard?.writeText) throw new Error('Clipboard access is unavailable in this browser.');
            await navigator.clipboard.writeText(detail.content);
            setFeedback(`${detail.kind === 'snippet' ? 'Snippet' : 'Note'} copied to the clipboard.`, 'success');
        } catch (error) { setFeedback(error.message, 'error'); }
    }

    function scheduleSearch() {
        window.clearTimeout(state.searchTimer);
        state.searchTimer = window.setTimeout(() => {
            state.filters.q = plain(byId('knowledgeSearch').value, 120);
            loadList();
        }, 250);
    }

    function initialize() {
        if (!byId('knowledgeModule')) return;
        byId('newKnowledgeItem')?.addEventListener('click', openNewEditor);
        byId('refreshKnowledge')?.addEventListener('click', () => loadList(state.selectedId));
        byId('knowledgeSearch')?.addEventListener('input', scheduleSearch);
        byId('knowledgeKindFilter')?.addEventListener('change', event => {
            const value = String(event.currentTarget.value || 'all');
            state.filters.kind = ['all', 'note', 'snippet'].includes(value) ? value : 'all';
            loadList();
        });
        byId('knowledgeTagFilter')?.addEventListener('change', event => {
            const value = normalizeTag(event.currentTarget.value);
            state.filters.tag = value;
            loadList();
        });
        byId('knowledgePinnedFilter')?.addEventListener('change', event => {
            const value = String(event.currentTarget.value || 'all');
            state.filters.pinned = ['all', 'true', 'false'].includes(value) ? value : 'all';
            loadList();
        });
        byId('knowledgePinItem')?.addEventListener('click', togglePin);
        byId('copyKnowledgeItem')?.addEventListener('click', copyItem);
        byId('editKnowledgeItem')?.addEventListener('click', openEditEditor);
        byId('duplicateKnowledgeItem')?.addEventListener('click', duplicateItem);
        byId('deleteKnowledgeItem')?.addEventListener('click', deleteItem);
        byId('knowledgeEditorForm')?.addEventListener('submit', saveEditor);
        byId('knowledgeEditorKind')?.addEventListener('change', () => renderLanguageOptions());
        byId('knowledgeEditorContent')?.addEventListener('input', updateEditorSize);
        byId('closeKnowledgeEditor')?.addEventListener('click', () => byId('knowledgeEditorDialog')?.close());
        byId('cancelKnowledgeEditor')?.addEventListener('click', () => byId('knowledgeEditorDialog')?.close());
        byId('knowledgeEditorDialog')?.addEventListener('keydown', event => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 'k') {
                event.preventDefault();
                event.stopPropagation();
                return;
            }
            if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
                event.preventDefault();
                byId('knowledgeEditorForm')?.requestSubmit();
            }
        });
        loadList();
    }

    if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initialize);
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            byteLength,
            normalizeFull,
            normalizeList,
            normalizeSummary,
            normalizeTags,
            parseTags,
            safeContent,
        };
    }
})();
