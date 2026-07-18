(function () {
    'use strict';

    const ICONS = new Set([
        'activity', 'archive', 'blocks', 'box', 'briefcase-business', 'brush', 'bug',
        'check-check', 'circle-play', 'cloud', 'code-2', 'command', 'container',
        'database', 'folder-git-2', 'git-branch', 'hammer', 'hard-drive', 'house',
        'messages-square', 'monitor-up', 'package', 'play', 'refresh-cw', 'rocket',
        'search', 'server-cog', 'settings', 'shield-check', 'sparkles', 'square-play',
        'test-tube-2', 'wrench', 'zap',
    ]);
    const RUN_STATES = new Set([
        'queued', 'claimed', 'running', 'succeeded', 'failed', 'rejected', 'expired', 'cancelled',
    ]);
    const state = {
        commands: [],
        results: [],
        activeIndex: 0,
        agents: [],
        tasks: [],
        runs: [],
        busyTaskIds: new Set(),
        pollTimer: null,
    };

    function byId(id) { return document.getElementById(id); }
    function object(value) { return value && typeof value === 'object' && !Array.isArray(value) ? value : null; }

    function plain(value, maximum = 160) {
        if (typeof value !== 'string' && typeof value !== 'number') return '';
        return String(value).replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, maximum);
    }

    function opaqueId(value) {
        return typeof value === 'string' && /^[A-Za-z0-9_-]{16,128}$/.test(value) ? value : '';
    }

    function publicTaskId(value) {
        return typeof value === 'string' && /^[a-f0-9]{32}$/.test(value) ? value : '';
    }

    function safeExternalUrl(value) {
        try {
            const url = new URL(String(value || ''));
            if (url.protocol !== 'https:' || url.username || url.password) return '';
            return url.href;
        } catch (_error) { return ''; }
    }

    function safeIcon(value) {
        const name = plain(value, 40).toLocaleLowerCase();
        return ICONS.has(name) ? name : 'square-play';
    }

    function safeDate(value) {
        if (typeof value !== 'string') return '';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? '' : date.toISOString();
    }

    function boundedInteger(value, maximum = 10000) {
        return Number.isSafeInteger(value) && value >= 0 ? Math.min(value, maximum) : 0;
    }

    function normalizeAgent(value) {
        const source = object(value);
        if (!source) return null;
        const id = opaqueId(source.id);
        if (!id) return null;
        return Object.freeze({
            id,
            display_name: plain(source.display_name, 100) || 'Task runner',
            platform: plain(source.platform, 80) || 'Unknown platform',
            agent_version: plain(source.agent_version, 40),
            paired_at: safeDate(source.paired_at),
            last_seen_at: safeDate(source.last_seen_at),
            online: source.online === true,
            task_count: boundedInteger(source.task_count),
        });
    }

    function normalizeTask(value) {
        const source = object(value);
        if (!source) return null;
        const id = publicTaskId(source.id);
        const agentId = opaqueId(source.agent_id);
        const title = plain(source.title, 120);
        if (!id || !agentId || !title) return null;
        return Object.freeze({
            id,
            title,
            description: plain(source.description, 280),
            category: plain(source.category, 60) || 'General',
            icon: safeIcon(source.icon),
            requires_confirmation: source.requires_confirmation === true,
            agent_id: agentId,
            agent_name: plain(source.agent_name, 100) || 'Task runner',
            available: source.available === true,
        });
    }

    function normalizeRun(value) {
        const source = object(value);
        if (!source) return null;
        const id = opaqueId(source.id);
        const taskId = publicTaskId(source.task_id);
        const agentId = opaqueId(source.agent_id);
        if (!id || !taskId || !agentId) return null;
        const candidateState = plain(source.state, 24).toLocaleLowerCase();
        return Object.freeze({
            id,
            task_id: taskId,
            task_title: plain(source.task_title, 120) || 'Approved task',
            agent_id: agentId,
            agent_name: plain(source.agent_name, 100) || 'Task runner',
            state: RUN_STATES.has(candidateState) ? candidateState : 'unknown',
            requested_at: safeDate(source.requested_at),
            claimed_at: safeDate(source.claimed_at),
            completed_at: safeDate(source.completed_at),
            result_status: plain(source.result_status, 80),
            result_code: plain(source.result_code, 80),
            summary: plain(source.summary, 800),
        });
    }

    function normalizeCatalog(payload) {
        const source = object(payload);
        if (!source || !Array.isArray(source.agents) || !Array.isArray(source.tasks)) {
            throw new Error('Kasugai returned an invalid launcher catalog.');
        }
        return Object.freeze({
            agents: Object.freeze(source.agents.slice(0, 64).map(normalizeAgent).filter(Boolean)),
            tasks: Object.freeze(source.tasks.slice(0, 256).map(normalizeTask).filter(Boolean)),
        });
    }

    function normalizeAgents(payload) {
        const source = object(payload);
        if (!source || !Array.isArray(source.agents)) throw new Error('Kasugai returned an invalid runner list.');
        return Object.freeze(source.agents.slice(0, 64).map(normalizeAgent).filter(Boolean));
    }

    function normalizeRuns(payload) {
        const source = object(payload);
        if (!source || !Array.isArray(source.runs)) throw new Error('Kasugai returned an invalid run history.');
        return Object.freeze(source.runs.slice(0, 100).map(normalizeRun).filter(Boolean));
    }

    function normalizePairing(payload) {
        const source = object(payload);
        if (!source) throw new Error('Kasugai returned an invalid pairing response.');
        const id = opaqueId(source.pairing_id);
        const code = typeof source.code === 'string' && /^[A-Za-z0-9_-]{20,128}$/.test(source.code)
            ? source.code
            : '';
        const expiresAt = safeDate(source.expires_at);
        if (!id || !code || !expiresAt) throw new Error('Kasugai returned an invalid pairing response.');
        return Object.freeze({ pairing_id: id, code, expires_at: expiresAt });
    }

    function normalizeSubmission(payload) {
        const source = object(payload);
        if (!source || typeof source.queued !== 'boolean') throw new Error('Kasugai returned an invalid task response.');
        if (source.queued) {
            const run = normalizeRun(source.run);
            if (!run) throw new Error('Kasugai returned an invalid queued run.');
            return Object.freeze({ queued: true, run });
        }
        const preview = object(source.preview);
        const token = preview && typeof preview.confirmation_token === 'string' ? preview.confirmation_token : '';
        const expiresAt = preview ? safeDate(preview.expires_at) : '';
        if (!preview || !/^[A-Za-z0-9_-]{16,256}$/.test(token) || !expiresAt) {
            throw new Error('Kasugai returned an invalid confirmation preview.');
        }
        return Object.freeze({
            queued: false,
            preview: Object.freeze({
                confirmation_token: token,
                expires_at: expiresAt,
                title: plain(preview.title, 120) || 'Approved local task',
                description: plain(preview.description, 280),
            }),
        });
    }

    function formatTime(value) {
        const date = new Date(String(value || ''));
        if (Number.isNaN(date.getTime())) return 'Not reported';
        return new Intl.DateTimeFormat(undefined, {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit',
        }).format(date);
    }

    function scoreCommand(item, query) {
        const needle = plain(query).toLocaleLowerCase();
        if (!needle) return item.priority || 0;
        const title = item.title.toLocaleLowerCase();
        const subtitle = item.subtitle.toLocaleLowerCase();
        const keywords = item.keywords.toLocaleLowerCase();
        if (title === needle) return 1000;
        if (title.startsWith(needle)) return 700 - title.length;
        if (title.includes(needle)) return 500 - title.indexOf(needle);
        if (keywords.includes(needle)) return 300 - keywords.indexOf(needle);
        if (subtitle.includes(needle)) return 100 - subtitle.indexOf(needle);
        const words = needle.split(/\s+/).filter(Boolean);
        const haystack = `${title} ${subtitle} ${keywords}`;
        return words.every(word => haystack.includes(word)) ? 50 : -1;
    }

    function searchCommands(commands, query) {
        return (Array.isArray(commands) ? commands : [])
            .map(item => ({ item, score: scoreCommand(item, query) }))
            .filter(entry => entry.score >= 0)
            .sort((left, right) => right.score - left.score || left.item.title.localeCompare(right.item.title))
            .slice(0, 30)
            .map(entry => entry.item);
    }

    function command(input) {
        const source = object(input);
        if (!source) return null;
        const id = plain(source.id, 160);
        const title = plain(source.title, 120);
        if (!id || !title) return null;
        return {
            id,
            title,
            subtitle: plain(source.subtitle, 180),
            keywords: plain(source.keywords, 240),
            kind: plain(source.kind || 'Command', 32),
            icon: safeIcon(source.icon || 'command'),
            priority: Number.isFinite(Number(source.priority)) ? Number(source.priority) : 0,
            enabled: source.enabled !== false,
            disabled_reason: plain(source.disabled_reason, 180),
            activate: typeof source.activate === 'function' ? source.activate : null,
            external_url: safeExternalUrl(source.external_url),
        };
    }

    function staticCommands() {
        const navigate = (id, title, subtitle, selector, iconName, keywords, priority) => command({
            id, title, subtitle, icon: iconName, keywords, priority,
            activate: () => { closePalette(); document.querySelector(selector)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); },
        });
        return [
            navigate('nav.developer', 'Developer Cockpit', 'Repositories and GitHub', '#developerCockpit', 'git-branch', 'home code repositories github', 90),
            navigate('nav.workstation', 'Workstation Monitor', 'CPU, memory, GPU, disk, and network', '#workstationMonitor', 'monitor-up', 'system telemetry machine', 80),
            navigate('nav.homelab', 'Docker & Homelab', 'Containers and service health', '#homelabDashboard', 'container', 'docker servers infrastructure', 80),
            navigate('nav.launcher', 'Universal Launcher', 'Commands and approved tasks', '#launcherModule', 'command', 'run action task', 70),
            command({ id: 'nav.projects', title: 'Open Projects', subtitle: 'Portfolio and project workspace', icon: 'briefcase-business', keywords: 'tasks planning management', priority: 90, activate: () => window.location.assign('/projects') }),
            command({ id: 'nav.team-room', title: 'Open Team Room', subtitle: 'Chat, files, and screen sharing', icon: 'messages-square', keywords: 'chat transfer share collaboration', priority: 85, activate: () => { closePalette(); document.querySelector('[data-team-room-trigger]')?.click(); } }),
            command({ id: 'nav.settings', title: 'Open Settings', subtitle: 'Runners, agents, appearance, and application', icon: 'settings', keywords: 'configure preferences', priority: 75, activate: () => { closePalette(); window.KasugaiSettingsModal?.open?.('launcher', byId('commandPaletteButton')); } }),
            command({ id: 'action.refresh', title: 'Refresh dashboard telemetry', subtitle: 'Repositories, workstation, homelab, and launcher', icon: 'refresh-cw', keywords: 'reload update', priority: 65, activate: () => { closePalette(); byId('refreshDeveloperCockpit')?.click(); byId('refreshWorkstation')?.click(); byId('refreshHomelab')?.click(); byId('refreshLauncher')?.click(); } }),
        ].filter(Boolean);
    }

    function icon(name) {
        const element = document.createElement('i');
        element.setAttribute('data-lucide', safeIcon(name));
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
            if (!response.ok) throw new Error('Kasugai could not complete that launcher request.');
            return null;
        }
        let payload;
        try { payload = await response.json(); }
        catch (_error) { throw new Error('Kasugai returned an invalid launcher response.'); }
        if (!response.ok) throw new Error(plain(payload?.error, 240) || 'Kasugai could not complete that launcher request.');
        return payload;
    }

    async function api(url, options = {}) {
        const method = String(options.method || 'GET').toUpperCase();
        const headers = { Accept: 'application/json' };
        let body;
        if (!['GET', 'HEAD'].includes(method)) {
            const token = csrfToken();
            if (!token) throw new Error('Reload this page before changing launcher settings.');
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
        const element = byId('launcherFeedback');
        if (!element) return;
        element.textContent = message || '';
        element.classList.remove('success', 'error');
        if (kind) element.classList.add(kind);
        element.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    }

    function setSettingsFeedback(id, message, kind) {
        const element = byId(id);
        if (!element) return;
        element.textContent = message || '';
        element.classList.remove('success', 'error');
        if (kind) element.classList.add(kind);
        element.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    }

    function setStatus() {
        const online = state.agents.filter(agent => agent.online).length;
        const available = state.tasks.filter(task => task.available).length;
        const main = byId('launcherStatus');
        const runner = byId('launcherRunnerStatus');
        if (main) {
            main.textContent = !state.agents.length
                ? 'Browser actions only'
                : available
                    ? `${available} task${available === 1 ? '' : 's'} ready`
                    : state.tasks.length ? 'Tasks unavailable' : 'No tasks published';
            main.classList.remove('is-ok', 'is-warning', 'is-error');
            if (available) main.classList.add('is-ok');
            else if (state.agents.length) main.classList.add('is-warning');
        }
        if (runner) {
            runner.textContent = !state.agents.length ? 'Unconfigured' : online ? `${online} online` : 'Offline';
            runner.classList.remove('is-ok', 'is-warning', 'is-error');
            if (online) runner.classList.add('is-ok');
            else if (state.agents.length) runner.classList.add('is-warning');
        }
        if (byId('launcherOnlineCount')) byId('launcherOnlineCount').textContent = String(online);
        if (byId('launcherTaskCount')) byId('launcherTaskCount').textContent = String(state.tasks.length);
    }

    function renderRunners() {
        const container = byId('launcherRunnerList');
        if (!container) return;
        container.replaceChildren();
        if (!state.agents.length) {
            const empty = document.createElement('p');
            empty.className = 'home-empty-copy';
            empty.textContent = 'Pair a separate runner to make local tasks available.';
            container.appendChild(empty);
        } else {
            state.agents.slice(0, 4).forEach(agent => {
                const row = document.createElement('div');
                row.className = 'launcher-runner-row';
                const dot = document.createElement('span');
                dot.className = `launcher-state-dot${agent.online ? ' is-online' : ''}`;
                const copy = document.createElement('span');
                const name = document.createElement('strong');
                name.textContent = agent.display_name;
                const detail = document.createElement('small');
                detail.textContent = `${agent.platform} - ${agent.task_count} task${agent.task_count === 1 ? '' : 's'}`;
                copy.append(name, detail);
                const status = document.createElement('span');
                status.className = `launcher-runner-state${agent.online ? ' is-online' : ''}`;
                status.textContent = agent.online ? 'Online' : 'Offline';
                row.append(dot, copy, status);
                container.appendChild(row);
            });
        }
        setStatus();
    }

    function renderCategories() {
        const select = byId('launcherTaskCategory');
        if (!select) return;
        const current = select.value;
        select.replaceChildren();
        const all = document.createElement('option');
        all.value = '';
        all.textContent = 'All categories';
        select.appendChild(all);
        [...new Set(state.tasks.map(task => task.category))].sort((a, b) => a.localeCompare(b)).forEach(category => {
            const option = document.createElement('option');
            option.value = category;
            option.textContent = category;
            select.appendChild(option);
        });
        select.value = [...select.options].some(option => option.value === current) ? current : '';
    }

    function taskCard(task) {
        const card = document.createElement('article');
        card.className = `launcher-task-card${task.available ? '' : ' is-unavailable'}`;
        const heading = document.createElement('div');
        heading.className = 'launcher-task-heading';
        const iconBox = document.createElement('span');
        iconBox.className = 'launcher-task-icon';
        iconBox.appendChild(icon(task.icon));
        const copy = document.createElement('span');
        const title = document.createElement('strong');
        title.textContent = task.title;
        const agent = document.createElement('small');
        agent.textContent = task.agent_name;
        copy.append(title, agent);
        heading.append(iconBox, copy);
        const description = document.createElement('p');
        description.textContent = task.description || 'No task description was published by this runner.';
        const footer = document.createElement('div');
        footer.className = 'launcher-task-footer';
        const badges = document.createElement('span');
        badges.className = 'launcher-task-badges';
        const category = document.createElement('span');
        category.textContent = task.category;
        badges.appendChild(category);
        if (task.requires_confirmation) {
            const guarded = document.createElement('span');
            guarded.className = 'is-guarded';
            guarded.textContent = 'Confirm';
            badges.appendChild(guarded);
        }
        const run = document.createElement('button');
        run.type = 'button';
        run.className = 'app-button app-button-primary launcher-run-button';
        run.append(icon('play'));
        const runLabel = document.createElement('span');
        runLabel.textContent = state.busyTaskIds.has(task.id) ? 'Queueing' : task.available ? 'Run' : 'Unavailable';
        run.appendChild(runLabel);
        run.disabled = !task.available || state.busyTaskIds.has(task.id);
        run.title = task.available ? `Run ${task.title}` : 'Task execution is currently unavailable';
        run.addEventListener('click', () => startRun(task));
        footer.append(badges, run);
        card.append(heading, description, footer);
        return card;
    }

    function renderTasks() {
        const container = byId('launcherTaskGrid');
        if (!container) return;
        const query = plain(byId('launcherTaskSearch')?.value, 120).toLocaleLowerCase();
        const category = plain(byId('launcherTaskCategory')?.value, 60);
        const filtered = state.tasks.filter(task => {
            if (category && task.category !== category) return false;
            if (!query) return true;
            return `${task.title} ${task.description} ${task.category} ${task.agent_name}`.toLocaleLowerCase().includes(query);
        });
        container.replaceChildren();
        container.setAttribute('aria-busy', 'false');
        if (!filtered.length) {
            const empty = document.createElement('div');
            empty.className = 'launcher-empty-state';
            empty.appendChild(icon(state.tasks.length ? 'search' : 'shield-check'));
            const strong = document.createElement('strong');
            strong.textContent = state.tasks.length ? 'No approved tasks match' : 'No local tasks published';
            const copy = document.createElement('p');
            copy.textContent = state.tasks.length ? 'Try a different search or category.' : 'Pair a runner and configure its local allowlist. The browser cannot create tasks.';
            empty.append(strong, copy);
            container.appendChild(empty);
        } else {
            filtered.forEach(task => container.appendChild(taskCard(task)));
        }
        if (byId('launcherCatalogCount')) byId('launcherCatalogCount').textContent = `${filtered.length} of ${state.tasks.length} task${state.tasks.length === 1 ? '' : 's'}`;
        refreshIcons();
    }

    function stateLabel(value) {
        return value === 'succeeded' ? 'Succeeded' : value === 'failed' ? 'Failed' : value === 'cancelled' ? 'Cancelled' : value === 'expired' ? 'Expired' : value === 'rejected' ? 'Rejected' : value === 'running' ? 'Running' : value === 'claimed' ? 'Claimed' : value === 'queued' ? 'Queued' : 'Unknown';
    }

    function renderRuns() {
        const container = byId('launcherRunList');
        if (!container) return;
        container.replaceChildren();
        container.setAttribute('aria-busy', 'false');
        if (!state.runs.length) {
            const empty = document.createElement('p');
            empty.className = 'home-empty-copy';
            empty.textContent = 'No approved tasks have been queued yet.';
            container.appendChild(empty);
            return;
        }
        state.runs.slice(0, 12).forEach(run => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'launcher-run-row';
            const dot = document.createElement('span');
            dot.className = `launcher-run-state is-${run.state}`;
            const copy = document.createElement('span');
            const title = document.createElement('strong');
            title.textContent = run.task_title;
            const detail = document.createElement('small');
            detail.textContent = `${run.agent_name} - ${formatTime(run.completed_at || run.requested_at)}`;
            copy.append(title, detail);
            const status = document.createElement('span');
            status.textContent = stateLabel(run.state);
            button.append(dot, copy, status);
            button.addEventListener('click', () => showRunResult(run));
            container.appendChild(button);
        });
    }

    function detailRow(term, value) {
        const row = document.createElement('div');
        const dt = document.createElement('dt');
        const dd = document.createElement('dd');
        dt.textContent = term;
        dd.textContent = value;
        row.append(dt, dd);
        return row;
    }

    function showRunResult(run) {
        const dialog = byId('launcherResultDialog');
        const details = byId('launcherResultDetails');
        if (!dialog || !details) return;
        byId('launcherResultTitle').textContent = run.task_title;
        details.replaceChildren(
            detailRow('State', stateLabel(run.state)),
            detailRow('Runner', run.agent_name),
            detailRow('Requested', formatTime(run.requested_at)),
            detailRow('Completed', formatTime(run.completed_at)),
            detailRow('Result status', run.result_status || 'Not reported'),
            detailRow('Result code', run.result_code || 'Not reported'),
        );
        byId('launcherResultSummary').textContent = run.summary || (run.completed_at ? 'The runner returned no additional summary.' : 'This run has not completed yet.');
        dialog.showModal();
        refreshIcons();
    }

    function renderAgentSettings() {
        const list = byId('launcherAgentList');
        if (!list) return;
        list.replaceChildren();
        if (!state.agents.length) {
            const empty = document.createElement('li');
            empty.className = 'settings-empty';
            empty.textContent = 'No task runners paired yet.';
            list.appendChild(empty);
            return;
        }
        state.agents.forEach(agent => {
            const item = document.createElement('li');
            item.className = 'settings-list-item';
            const copy = document.createElement('span');
            copy.className = 'workstation-agent-copy';
            const name = document.createElement('strong');
            name.textContent = agent.display_name;
            const detail = document.createElement('small');
            detail.textContent = `${agent.platform} - ${agent.online ? 'online' : 'offline'} - ${agent.task_count} task${agent.task_count === 1 ? '' : 's'} - last seen ${formatTime(agent.last_seen_at)}`;
            copy.append(name, detail);
            const actions = document.createElement('span');
            actions.className = 'workstation-agent-actions';
            const rename = document.createElement('button');
            rename.type = 'button';
            rename.className = 'settings-remove-btn';
            rename.textContent = 'Rename';
            rename.addEventListener('click', () => renameAgent(agent));
            const revoke = document.createElement('button');
            revoke.type = 'button';
            revoke.className = 'settings-remove-btn';
            revoke.textContent = 'Revoke';
            revoke.addEventListener('click', () => revokeAgent(agent));
            actions.append(rename, revoke);
            item.append(copy, actions);
            list.appendChild(item);
        });
    }

    function renderTaskSettings() {
        const list = byId('launcherSettingsTaskList');
        if (!list) return;
        list.replaceChildren();
        if (!state.tasks.length) {
            const empty = document.createElement('li');
            empty.className = 'settings-empty';
            empty.textContent = 'No approved tasks are currently published.';
            list.appendChild(empty);
            return;
        }
        state.tasks.forEach(task => {
            const item = document.createElement('li');
            item.className = 'settings-list-item launcher-settings-task';
            const iconBox = document.createElement('span');
            iconBox.className = 'launcher-settings-task-icon';
            iconBox.appendChild(icon(task.icon));
            const copy = document.createElement('span');
            const title = document.createElement('strong');
            title.textContent = task.title;
            const detail = document.createElement('small');
            detail.textContent = `${task.category} - ${task.agent_name}${task.requires_confirmation ? ' - confirmation required' : ''}`;
            copy.append(title, detail);
            const status = document.createElement('span');
            status.className = `launcher-runner-state${task.available ? ' is-online' : ''}`;
            status.textContent = task.available ? 'Available' : 'Unavailable';
            item.append(iconBox, copy, status);
            list.appendChild(item);
        });
        refreshIcons();
    }

    function replaceDynamic(prefix, commands) {
        state.commands = state.commands.filter(item => !item.id.startsWith(prefix));
        commands.filter(Boolean).forEach(item => state.commands.push(item));
        if (byId('commandPalette')?.open) renderPalette();
    }

    function repositoryCommands(repositories) {
        return (Array.isArray(repositories) ? repositories : []).slice(0, 200).map(repository => {
            const source = object(repository) || {};
            const url = safeExternalUrl(source.web_url);
            return command({
                id: `repo.${plain(source.id, 64)}`,
                title: plain(source.name, 120) || 'Repository',
                subtitle: 'Repository',
                icon: 'folder-git-2', kind: 'Repository', keywords: 'git code github',
                external_url: url,
                enabled: Boolean(url),
                disabled_reason: url ? '' : 'This repository has no safe browser action yet',
            });
        });
    }

    function taskCommands() {
        return state.tasks.map(task => command({
            id: `host.${task.id}`,
            title: task.title,
            subtitle: `${task.description || task.category} - ${task.agent_name}`,
            keywords: `${task.category} ${task.agent_name} approved local`,
            icon: task.icon,
            kind: task.requires_confirmation ? 'Guarded task' : 'Local task',
            enabled: task.available && !state.busyTaskIds.has(task.id),
            disabled_reason: task.available ? 'This task is already being queued' : 'Task execution is currently unavailable',
            activate: () => startRun(task),
        }));
    }

    function renderPalette() {
        const container = byId('commandPaletteResults');
        if (!container) return;
        state.results = searchCommands(state.commands, byId('commandPaletteQuery')?.value || '');
        state.activeIndex = Math.max(0, Math.min(state.activeIndex, state.results.length - 1));
        container.replaceChildren();
        if (!state.results.length) {
            const empty = document.createElement('div');
            empty.className = 'command-palette-empty';
            empty.textContent = 'No commands match this search.';
            container.appendChild(empty);
            byId('commandPaletteStatus').textContent = '0 results';
            return;
        }
        state.results.forEach((item, index) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `command-result${index === state.activeIndex ? ' is-active' : ''}`;
            button.id = `command-result-${index}`;
            button.setAttribute('role', 'option');
            button.setAttribute('aria-selected', String(index === state.activeIndex));
            button.disabled = !item.enabled;
            button.title = item.enabled ? item.title : item.disabled_reason;
            const iconBox = document.createElement('span');
            iconBox.className = 'command-result-icon';
            iconBox.appendChild(icon(item.icon));
            const copy = document.createElement('span');
            copy.className = 'command-result-copy';
            const title = document.createElement('strong');
            title.textContent = item.title;
            const subtitle = document.createElement('small');
            subtitle.textContent = item.enabled ? item.subtitle : item.disabled_reason || item.subtitle;
            copy.append(title, subtitle);
            const kind = document.createElement('span');
            kind.className = 'command-result-kind';
            kind.textContent = item.kind;
            button.append(iconBox, copy, kind);
            button.addEventListener('mousemove', () => { if (state.activeIndex !== index) { state.activeIndex = index; renderPalette(); } });
            button.addEventListener('click', () => activate(item));
            container.appendChild(button);
        });
        container.setAttribute('aria-activedescendant', `command-result-${state.activeIndex}`);
        byId('commandPaletteStatus').textContent = `${state.results.length} result${state.results.length === 1 ? '' : 's'}`;
        refreshIcons();
    }

    function activate(item) {
        if (!item?.enabled) return;
        if (item.external_url) {
            window.open(item.external_url, '_blank', 'noopener,noreferrer');
            closePalette();
        } else if (item.activate) item.activate();
    }

    function move(delta) {
        if (!state.results.length) return;
        state.activeIndex = (state.activeIndex + delta + state.results.length) % state.results.length;
        renderPalette();
        byId(`command-result-${state.activeIndex}`)?.scrollIntoView({ block: 'nearest' });
    }

    function openPalette(event) {
        const dialog = byId('commandPalette');
        if (byId('launcherConfirmationDialog')?.open || byId('launcherResultDialog')?.open) {
            event?.preventDefault?.();
            return;
        }
        if (!dialog || dialog.open) return;
        window.KasugaiTeamRoom?.close?.({ restoreFocus: false });
        window.KasugaiSettingsModal?.close?.({ restoreFocus: false });
        state.activeIndex = 0;
        dialog.showModal();
        byId('commandPaletteButton')?.setAttribute('aria-expanded', 'true');
        const input = byId('commandPaletteQuery');
        if (input) { input.value = ''; renderPalette(); window.setTimeout(() => input.focus(), 0); }
        event?.preventDefault?.();
    }

    function closePalette() {
        const dialog = byId('commandPalette');
        if (dialog?.open) dialog.close();
    }

    async function loadCatalog() {
        const catalog = normalizeCatalog(await api('/api/launcher/catalog'));
        state.agents = [...catalog.agents];
        state.tasks = [...catalog.tasks];
        replaceDynamic('host.', taskCommands());
        renderCategories();
        renderTasks();
        renderRunners();
        renderAgentSettings();
        renderTaskSettings();
        setFeedback('');
    }

    async function loadAgents() {
        state.agents = [...normalizeAgents(await api('/api/launcher/agents'))];
        renderRunners();
        renderAgentSettings();
    }

    async function loadRuns() {
        state.runs = [...normalizeRuns(await api('/api/launcher/runs'))];
        renderRuns();
    }

    function confirmPreview(preview) {
        return new Promise(resolve => {
            const dialog = byId('launcherConfirmationDialog');
            const confirm = byId('confirmLauncherRun');
            const cancel = byId('cancelLauncherRun');
            if (!dialog || !confirm || !cancel) { resolve(false); return; }
            byId('launcherConfirmationTitle').textContent = preview.title;
            byId('launcherConfirmationDescription').textContent = preview.description || 'The owning runner requires explicit approval before this task can be queued.';
            byId('launcherConfirmationExpiry').textContent = `This one-use approval expires ${formatTime(preview.expires_at)}. The runner will revalidate its local allowlist before execution.`;
            let settled = false;
            const finish = approved => {
                if (settled) return;
                settled = true;
                confirm.onclick = null;
                cancel.onclick = null;
                dialog.oncancel = null;
                dialog.onclose = null;
                if (dialog.open) dialog.close();
                resolve(approved);
            };
            confirm.onclick = () => finish(true);
            cancel.onclick = () => finish(false);
            dialog.oncancel = event => { event.preventDefault(); finish(false); };
            dialog.onclose = () => finish(false);
            dialog.showModal();
            refreshIcons();
        });
    }

    async function startRun(task) {
        const current = state.tasks.find(item => item.id === task?.id);
        if (!current || !current.available || state.busyTaskIds.has(current.id)) return;
        closePalette();
        state.busyTaskIds.add(current.id);
        renderTasks();
        replaceDynamic('host.', taskCommands());
        setFeedback(`Requesting ${current.title}...`);
        try {
            let submission = normalizeSubmission(await api(`/api/launcher/tasks/${encodeURIComponent(current.id)}/runs`, {
                method: 'POST', body: {},
            }));
            if (!submission.queued) {
                const approved = await confirmPreview(submission.preview);
                if (!approved) {
                    setFeedback('Task cancelled before it was queued.');
                    return;
                }
                submission = normalizeSubmission(await api(`/api/launcher/tasks/${encodeURIComponent(current.id)}/runs`, {
                    method: 'POST', body: { confirmation_token: submission.preview.confirmation_token },
                }));
            }
            if (!submission.queued) throw new Error('Kasugai did not queue the approved task.');
            state.runs = [submission.run, ...state.runs.filter(run => run.id !== submission.run.id)];
            renderRuns();
            setFeedback(`${current.title} was queued on ${submission.run.agent_name}.`, 'success');
            await loadRuns();
        } catch (error) {
            setFeedback(error.message, 'error');
        } finally {
            state.busyTaskIds.delete(current.id);
            renderTasks();
            replaceDynamic('host.', taskCommands());
        }
    }

    async function createPairing() {
        const button = byId('createLauncherPairing');
        if (button) button.disabled = true;
        setSettingsFeedback('launcherPairingStatus', 'Creating a one-time runner pairing...');
        try {
            const pairing = normalizePairing(await api('/api/launcher/pairings', { method: 'POST', body: {} }));
            byId('launcherPairing').hidden = false;
            byId('launcherPairingCode').textContent = pairing.code;
            byId('launcherPairingCommand').textContent = `powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\install-launcher-agent.ps1 -ServerUrl ${window.location.origin} -PairingId ${pairing.pairing_id}`;
            byId('launcherPairingExpiry').textContent = `Expires ${formatTime(pairing.expires_at)} - pairing ID ${pairing.pairing_id}`;
            setSettingsFeedback('launcherPairingStatus', 'The runner will securely prompt for the one-time code.', 'success');
        } catch (error) {
            setSettingsFeedback('launcherPairingStatus', error.message, 'error');
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function renameAgent(agent) {
        const value = window.prompt('Task runner name', agent.display_name);
        if (value === null) return;
        const displayName = plain(value, 100);
        if (!displayName) return;
        try {
            await api(`/api/launcher/agents/${encodeURIComponent(agent.id)}`, { method: 'PATCH', body: { display_name: displayName } });
            setSettingsFeedback('launcherAgentStatus', 'Task runner renamed.', 'success');
            await Promise.all([loadAgents(), loadCatalog()]);
        } catch (error) { setSettingsFeedback('launcherAgentStatus', error.message, 'error'); }
    }

    async function revokeAgent(agent) {
        if (!window.confirm(`Revoke "${agent.display_name}" and cancel its pending runs?`)) return;
        try {
            await api(`/api/launcher/agents/${encodeURIComponent(agent.id)}`, { method: 'DELETE', body: {} });
            setSettingsFeedback('launcherAgentStatus', 'Task runner revoked.', 'success');
            await Promise.all([loadAgents(), loadCatalog(), loadRuns()]);
        } catch (error) { setSettingsFeedback('launcherAgentStatus', error.message, 'error'); }
    }

    function renderLoadError(containerId, title, message) {
        const container = byId(containerId);
        if (!container) return;
        container.replaceChildren();
        container.setAttribute('aria-busy', 'false');
        const empty = document.createElement('div');
        empty.className = 'launcher-empty-state';
        empty.appendChild(icon('activity'));
        const strong = document.createElement('strong');
        strong.textContent = title;
        const copy = document.createElement('p');
        copy.textContent = plain(message, 240) || 'Try refreshing this module.';
        empty.append(strong, copy);
        container.appendChild(empty);
        refreshIcons();
    }

    function openSettings(event) {
        window.KasugaiSettingsModal?.open?.('launcher', event?.currentTarget || event || null);
        Promise.all([loadAgents(), loadCatalog()]).catch(error => setSettingsFeedback('launcherAgentStatus', error.message, 'error'));
    }

    async function refreshAll() {
        byId('launcherTaskGrid')?.setAttribute('aria-busy', 'true');
        byId('launcherRunList')?.setAttribute('aria-busy', 'true');
        const results = await Promise.allSettled([loadCatalog(), loadRuns()]);
        const failure = results.find(result => result.status === 'rejected');
        if (failure) {
            setFeedback(failure.reason?.message || 'Launcher data is unavailable.', 'error');
            if (results[0].status === 'rejected' && !state.tasks.length) {
                renderLoadError('launcherTaskGrid', 'Task catalog unavailable', results[0].reason?.message);
                const status = byId('launcherStatus');
                if (status) {
                    status.textContent = 'Unavailable';
                    status.classList.remove('is-ok', 'is-warning');
                    status.classList.add('is-error');
                }
            } else byId('launcherTaskGrid')?.setAttribute('aria-busy', 'false');
            if (results[1].status === 'rejected' && !state.runs.length) {
                renderLoadError('launcherRunList', 'Run history unavailable', results[1].reason?.message);
            } else byId('launcherRunList')?.setAttribute('aria-busy', 'false');
        }
    }

    function initialize() {
        if (!byId('launcherModule')) return;
        state.commands = staticCommands();
        byId('commandPaletteButton')?.addEventListener('click', openPalette);
        document.querySelectorAll('[data-open-command-palette]').forEach(button => button.addEventListener('click', openPalette));
        document.querySelectorAll('[data-open-launcher-settings]').forEach(button => button.addEventListener('click', openSettings));
        document.querySelector('.settings-tab[data-tab="launcher"]')?.addEventListener('click', () => Promise.all([loadAgents(), loadCatalog()]).catch(error => setSettingsFeedback('launcherAgentStatus', error.message, 'error')));
        byId('commandPaletteQuery')?.addEventListener('input', () => { state.activeIndex = 0; renderPalette(); });
        byId('commandPaletteQuery')?.addEventListener('keydown', event => {
            if (event.key === 'ArrowDown') { event.preventDefault(); move(1); }
            else if (event.key === 'ArrowUp') { event.preventDefault(); move(-1); }
            else if (event.key === 'Enter') { event.preventDefault(); activate(state.results[state.activeIndex]); }
        });
        byId('commandPalette')?.addEventListener('close', () => byId('commandPaletteButton')?.setAttribute('aria-expanded', 'false'));
        byId('launcherTaskSearch')?.addEventListener('input', renderTasks);
        byId('launcherTaskCategory')?.addEventListener('change', renderTasks);
        byId('refreshLauncher')?.addEventListener('click', refreshAll);
        byId('refreshLauncherRuns')?.addEventListener('click', () => loadRuns().catch(error => setFeedback(error.message, 'error')));
        byId('createLauncherPairing')?.addEventListener('click', createPairing);
        byId('closeLauncherResult')?.addEventListener('click', () => byId('launcherResultDialog')?.close());
        document.addEventListener('keydown', event => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 'k') openPalette(event);
        });
        document.addEventListener('kasugai:repositories', event => replaceDynamic('repo.', repositoryCommands(event.detail)));
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) refreshAll();
        });
        state.pollTimer = window.setInterval(() => {
            const active = state.runs.some(run => ['queued', 'claimed', 'running'].includes(run.state));
            if (!document.hidden && active) loadRuns().catch(error => setFeedback(error.message, 'error'));
        }, 5000);
        refreshAll();
    }

    if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initialize);
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            command,
            normalizeAgent,
            normalizeCatalog,
            normalizePairing,
            normalizeRun,
            normalizeRuns,
            normalizeSubmission,
            normalizeTask,
            safeExternalUrl,
            searchCommands,
        };
    }
})();
