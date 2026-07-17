(function () {
    'use strict';

    const state = {
        repositories: [],
        roots: [],
        overviewGeneration: 0,
        githubGeneration: 0,
        settingsGeneration: 0,
        refreshGeneration: 0,
        favoriteRequests: new Set(),
    };

    function byId(id) {
        return document.getElementById(id);
    }

    function numeric(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
    }

    function repositoryNeedsSync(repository) {
        return numeric(repository?.ahead) > 0 || numeric(repository?.behind) > 0;
    }

    function filterRepositories(repositories, query, selectedFilter) {
        const needle = String(query || '').trim().toLocaleLowerCase();
        const filter = String(selectedFilter || 'all');
        return (Array.isArray(repositories) ? repositories : []).filter(repository => {
            if (filter === 'favorites' && !repository.favorite) return false;
            if (filter === 'dirty' && !repository.dirty) return false;
            if (filter === 'sync' && !repositoryNeedsSync(repository)) return false;
            if (!needle) return true;
            return [
                repository.name,
                repository.display_path,
                repository.branch,
                repository.github_slug,
                repository.last_commit?.subject,
            ].some(value => String(value || '').toLocaleLowerCase().includes(needle));
        });
    }

    function validatedGithubUrl(value) {
        if (typeof value !== 'string' || !value) return null;
        try {
            const parsed = new URL(value);
            if (
                parsed.protocol !== 'https:'
                || parsed.hostname !== 'github.com'
                || parsed.port
                || parsed.username
                || parsed.password
                || parsed.search
                || parsed.hash
            ) return null;
            const path = parsed.pathname.replace(/\/$/, '');
            if (!/^\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(path)) return null;
            const segments = path.slice(1).split('/');
            if (segments.some(segment => segment === '.' || segment === '..')) return null;
            return `https://github.com${path}`;
        } catch (_error) {
            return null;
        }
    }

    function refreshIcons() {
        if (typeof window !== 'undefined' && window.lucide) window.lucide.createIcons();
    }

    function icon(name) {
        const element = document.createElement('i');
        element.setAttribute('data-lucide', name);
        element.setAttribute('aria-hidden', 'true');
        return element;
    }

    function setCockpitStatus(element, message, kind) {
        if (!element) return;
        element.textContent = message;
        element.classList.remove('is-ok', 'is-warning', 'is-error');
        if (kind) element.classList.add(`is-${kind}`);
    }

    function setSettingsFeedback(element, message, kind) {
        if (!element) return;
        element.textContent = message || '';
        element.classList.remove('success', 'error');
        if (kind) element.classList.add(kind);
        element.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    }

    async function readJsonResponse(response) {
        if (response.redirected || response.status === 401) {
            throw new Error('Your session expired. Sign in again and retry.');
        }
        if (response.status === 204) {
            if (!response.ok) throw new Error('Kasugai could not complete that request.');
            return null;
        }
        let payload;
        try {
            payload = await response.json();
        } catch (_error) {
            throw new Error('Kasugai returned an invalid dashboard response.');
        }
        if (!response.ok) {
            throw new Error(
                payload && typeof payload.error === 'string'
                    ? payload.error
                    : 'Kasugai could not complete that request.',
            );
        }
        return payload;
    }

    async function apiRequest(url, options = {}) {
        const method = String(options.method || 'GET').toUpperCase();
        const headers = { Accept: 'application/json', ...(options.headers || {}) };
        let body = options.body;
        if (!['GET', 'HEAD'].includes(method)) {
            const token = String(window.KASUGAI_CSRF_TOKEN || '');
            if (!token) throw new Error('Reload this page before changing dashboard settings.');
            headers['Content-Type'] = 'application/json';
            headers['X-Kasugai-CSRF'] = token;
            if (body !== undefined && typeof body !== 'string') body = JSON.stringify(body);
        }
        const response = await fetch(url, {
            method,
            headers,
            body,
            credentials: 'same-origin',
            cache: 'no-store',
            redirect: 'error',
        });
        return readJsonResponse(response);
    }

    function createStateMessage(className, iconName, title, copy, action) {
        const wrapper = document.createElement('div');
        wrapper.className = className;
        wrapper.appendChild(icon(iconName));
        const heading = document.createElement('strong');
        heading.textContent = title;
        wrapper.appendChild(heading);
        if (copy) {
            const paragraph = document.createElement('p');
            paragraph.textContent = copy;
            wrapper.appendChild(paragraph);
        }
        if (action) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'cockpit-text-button';
            button.textContent = action.label;
            button.addEventListener('click', action.handler);
            wrapper.appendChild(button);
        }
        return wrapper;
    }

    function setRepositoryLoading() {
        const list = byId('repositoryList');
        if (!list) return;
        list.replaceChildren(createStateMessage(
            'cockpit-loading-state',
            'loader-circle',
            'Scanning configured roots…',
        ));
        list.setAttribute('aria-busy', 'true');
        setCockpitStatus(byId('repositoryStatus'), 'Loading');
        refreshIcons();
    }

    function renderMetric(id, value) {
        const element = byId(id);
        if (element) element.textContent = String(value);
    }

    function renderOverviewSummary(data) {
        const repositories = state.repositories;
        const roots = state.roots;
        const favorites = repositories.filter(item => item.favorite).length;
        const dirty = repositories.filter(item => item.dirty).length;
        const syncing = repositories.filter(repositoryNeedsSync).length;
        const unavailable = repositories.filter(item => item.available === false).length;
        const availableRoots = roots.filter(root => root.available !== false).length;

        renderMetric('repositoryTotal', repositories.length);
        renderMetric('repositoryFavorites', favorites);
        renderMetric('repositoryDirty', dirty);
        renderMetric('repositorySync', syncing);

        let summary;
        if (data.git_available === false) {
            summary = 'Git is unavailable on this Kasugai host, so repositories cannot be inspected yet.';
        } else if (roots.length === 0) {
            summary = 'Add a repository root to turn this page into your development command center.';
        } else if (availableRoots === 0) {
            summary = 'Your configured repository roots are not available to this Kasugai host.';
        } else if (repositories.length === 0) {
            summary = `No Git repositories were found in ${availableRoots} available ${availableRoots === 1 ? 'root' : 'roots'}.`;
        } else {
            const details = [];
            if (dirty) details.push(`${dirty} with local changes`);
            if (syncing) details.push(`${syncing} needing a sync`);
            summary = `${repositories.length} ${repositories.length === 1 ? 'repository' : 'repositories'} across ${availableRoots} available ${availableRoots === 1 ? 'root' : 'roots'}`;
            summary += details.length ? ` — ${details.join(' and ')}.` : ' — everything looks settled.';
        }
        const summaryElement = byId('cockpitSummary');
        if (summaryElement) summaryElement.textContent = summary;

        if (data.git_available === false || availableRoots < roots.length || unavailable) {
            setCockpitStatus(
                byId('repositoryStatus'),
                unavailable ? `${unavailable} unavailable` : 'Needs attention',
                'warning',
            );
        } else {
            setCockpitStatus(byId('repositoryStatus'), `${repositories.length} ready`, 'ok');
        }
    }

    function createBadge(label, className) {
        const badge = document.createElement('span');
        badge.className = `cockpit-repo-badge${className ? ` ${className}` : ''}`;
        badge.textContent = label;
        return badge;
    }

    function createRepositoryRow(repository) {
        const row = document.createElement('article');
        row.className = 'cockpit-repository';

        const favorite = document.createElement('button');
        favorite.type = 'button';
        favorite.className = `cockpit-favorite-button${repository.favorite ? ' is-favorite' : ''}`;
        favorite.setAttribute('aria-pressed', String(Boolean(repository.favorite)));
        favorite.setAttribute(
            'aria-label',
            `${repository.favorite ? 'Remove' : 'Add'} ${String(repository.name || 'repository')} ${repository.favorite ? 'from' : 'to'} favorites`,
        );
        favorite.title = repository.favorite ? 'Remove from favorites' : 'Add to favorites';
        favorite.appendChild(icon('star'));
        const validId = /^[0-9a-f]{32}$/.test(String(repository.id || ''));
        favorite.disabled = !validId || state.favoriteRequests.has(repository.id);
        if (validId) favorite.addEventListener('click', () => toggleFavorite(repository.id));

        const copy = document.createElement('div');
        copy.className = 'cockpit-repository-copy';
        const titleRow = document.createElement('div');
        titleRow.className = 'cockpit-repository-title-row';
        const title = document.createElement('strong');
        title.textContent = String(repository.name || 'Unnamed repository');
        titleRow.appendChild(title);
        copy.appendChild(titleRow);

        const path = document.createElement('span');
        path.className = 'cockpit-repository-path';
        path.textContent = String(repository.display_path || 'Configured repository');
        copy.appendChild(path);

        if (repository.last_commit?.subject) {
            const commit = document.createElement('span');
            commit.className = 'cockpit-repository-commit';
            const shortHash = String(repository.last_commit.short_hash || '').trim();
            commit.textContent = `${shortHash ? `${shortHash} · ` : ''}${String(repository.last_commit.subject)}`;
            copy.appendChild(commit);
        }

        const badges = document.createElement('div');
        badges.className = 'cockpit-badge-row';
        if (repository.available === false) {
            badges.appendChild(createBadge('Inspection unavailable', 'is-behind'));
        } else {
            if (repository.branch) badges.appendChild(createBadge(String(repository.branch)));
            if (repository.dirty) badges.appendChild(createBadge('Working tree changes', 'is-dirty'));
            if (numeric(repository.ahead)) badges.appendChild(createBadge(`↑ ${numeric(repository.ahead)} ahead`));
            if (numeric(repository.behind)) badges.appendChild(createBadge(`↓ ${numeric(repository.behind)} behind`, 'is-behind'));
        }
        copy.appendChild(badges);

        const actions = document.createElement('div');
        actions.className = 'cockpit-repository-actions';
        const githubUrl = validatedGithubUrl(repository.web_url);
        if (githubUrl) {
            const link = document.createElement('a');
            link.className = 'cockpit-repository-link';
            link.href = githubUrl;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.referrerPolicy = 'no-referrer';
            link.setAttribute('aria-label', `Open ${String(repository.name || 'repository')} on GitHub`);
            link.append(icon('github'));
            const label = document.createElement('span');
            label.textContent = 'GitHub';
            link.appendChild(label);
            actions.appendChild(link);
        }

        row.append(favorite, copy, actions);
        return row;
    }

    function renderRepositories() {
        const list = byId('repositoryList');
        if (!list) return;
        const query = byId('repositorySearch')?.value || '';
        const selectedFilter = byId('repositoryFilter')?.value || 'all';
        const repositories = filterRepositories(state.repositories, query, selectedFilter);
        list.replaceChildren();
        list.setAttribute('aria-busy', 'false');

        if (state.repositories.length === 0) {
            list.appendChild(createStateMessage(
                'cockpit-empty-state',
                'folder-git-2',
                'No repositories yet',
                state.roots.length
                    ? 'No Git repositories were found within the configured scan depth.'
                    : 'Configure a server-visible repository root to start scanning.',
                { label: 'Configure roots', handler: openDeveloperSettings },
            ));
        } else if (repositories.length === 0) {
            list.appendChild(createStateMessage(
                'cockpit-empty-state',
                'search-x',
                'Nothing matches this view',
                'Try another search term or repository filter.',
            ));
        } else {
            repositories.forEach(repository => list.appendChild(createRepositoryRow(repository)));
        }
        refreshIcons();
    }

    function renderOverviewError(error) {
        state.repositories = [];
        state.roots = [];
        ['repositoryTotal', 'repositoryFavorites', 'repositoryDirty', 'repositorySync']
            .forEach(id => renderMetric(id, '—'));
        const summary = byId('cockpitSummary');
        if (summary) summary.textContent = error.message || 'Repositories could not be inspected right now.';
        setCockpitStatus(byId('repositoryStatus'), 'Unavailable', 'error');
        const list = byId('repositoryList');
        if (list) {
            list.setAttribute('aria-busy', 'false');
            list.replaceChildren(createStateMessage(
                'cockpit-error-state',
                'triangle-alert',
                'Repository scan failed',
                error.message || 'Try refreshing the cockpit.',
                { label: 'Try again', handler: refreshCockpit },
            ));
        }
        refreshIcons();
    }

    async function loadOverview() {
        const generation = ++state.overviewGeneration;
        setRepositoryLoading();
        const data = await apiRequest('/api/developer/overview');
        if (generation !== state.overviewGeneration) return;
        if (!data || typeof data !== 'object') throw new Error('Kasugai returned an incomplete repository overview.');
        state.repositories = Array.isArray(data.repositories) ? data.repositories : [];
        state.roots = Array.isArray(data.roots) ? data.roots : [];
        renderOverviewSummary(data);
        renderRepositories();
        document.dispatchEvent(new CustomEvent('kasugai:repositories', {
            detail: state.repositories.map(repository => ({
                id: String(repository.id || ''),
                name: String(repository.name || ''),
                display_path: String(repository.display_path || ''),
                web_url: validatedGithubUrl(repository.web_url) || '',
            })),
        }));
    }

    async function toggleFavorite(repositoryId) {
        if (state.favoriteRequests.has(repositoryId)) return;
        const repository = state.repositories.find(item => item.id === repositoryId);
        if (!repository) return;
        const desired = !repository.favorite;
        state.favoriteRequests.add(repositoryId);
        renderRepositories();
        try {
            await apiRequest(`/api/developer/repositories/${encodeURIComponent(repositoryId)}/favorite`, {
                method: 'PUT',
                body: { favorite: desired },
            });
            repository.favorite = desired;
            state.repositories.sort((left, right) => (
                Number(Boolean(right.favorite)) - Number(Boolean(left.favorite))
                || String(left.name || '').localeCompare(String(right.name || ''))
            ));
            renderOverviewSummary({ git_available: true });
        } catch (error) {
            setCockpitStatus(byId('repositoryStatus'), 'Favorite not saved', 'error');
            const summary = byId('cockpitSummary');
            if (summary) summary.textContent = error.message;
        } finally {
            state.favoriteRequests.delete(repositoryId);
            renderRepositories();
        }
    }

    function setGithubLoading() {
        const activity = byId('githubActivity');
        if (!activity) return;
        activity.setAttribute('aria-busy', 'true');
        activity.replaceChildren(createStateMessage(
            'cockpit-loading-state',
            'loader-circle',
            'Checking GitHub…',
        ));
        setCockpitStatus(byId('githubStatus'), 'Checking');
        refreshIcons();
    }

    function createGithubMessage(title, copy) {
        const item = document.createElement('div');
        item.className = 'cockpit-github-item';
        const heading = document.createElement('strong');
        heading.textContent = title;
        const detail = document.createElement('span');
        detail.textContent = copy;
        item.append(heading, detail);
        return item;
    }

    function formatTimestamp(value) {
        const date = new Date(String(value || ''));
        if (Number.isNaN(date.getTime())) return '';
        return new Intl.DateTimeFormat(undefined, {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
        }).format(date);
    }

    function renderGithubActivity(data) {
        const activity = byId('githubActivity');
        if (!activity) return;
        activity.replaceChildren();
        activity.setAttribute('aria-busy', 'false');
        if (!data?.configured) {
            setCockpitStatus(byId('githubStatus'), 'Not connected');
            activity.appendChild(createGithubMessage(
                'Connect your GitHub account',
                'Notifications will appear here without exposing your token to the browser.',
            ));
            return;
        }

        const notifications = Array.isArray(data.notifications) ? data.notifications : [];
        setCockpitStatus(
            byId('githubStatus'),
            notifications.length ? `${notifications.length} unread` : 'All clear',
            'ok',
        );
        if (notifications.length === 0) {
            activity.appendChild(createGithubMessage(
                'Nothing needs your attention',
                'GitHub has no unread notifications for this account.',
            ));
            return;
        }

        notifications.slice(0, 5).forEach(notification => {
            const item = document.createElement('div');
            item.className = 'cockpit-github-item';
            const title = document.createElement('strong');
            title.textContent = String(notification.title || notification.type || 'GitHub notification');
            item.appendChild(title);

            const repositoryUrl = validatedGithubUrl(notification.repository_url);
            if (repositoryUrl) {
                const link = document.createElement('a');
                link.href = repositoryUrl;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.referrerPolicy = 'no-referrer';
                link.textContent = String(notification.repository || 'Open repository');
                item.appendChild(link);
            } else if (notification.repository) {
                const repository = document.createElement('span');
                repository.textContent = String(notification.repository);
                item.appendChild(repository);
            }

            const metadata = document.createElement('span');
            metadata.textContent = [
                notification.reason ? String(notification.reason).replaceAll('_', ' ') : '',
                formatTimestamp(notification.updated_at),
            ].filter(Boolean).join(' · ');
            item.appendChild(metadata);
            activity.appendChild(item);
        });
        if (notifications.length > 5) {
            activity.appendChild(createGithubMessage(
                `${notifications.length - 5} more notifications`,
                'Open GitHub to review the rest of the queue.',
            ));
        }
    }

    function renderGithubError(error) {
        const activity = byId('githubActivity');
        if (!activity) return;
        activity.setAttribute('aria-busy', 'false');
        activity.replaceChildren(createGithubMessage(
            'GitHub is unavailable',
            error.message || 'The connection could not be checked right now.',
        ));
        setCockpitStatus(byId('githubStatus'), 'Unavailable', 'error');
    }

    async function loadGithubActivity() {
        const generation = ++state.githubGeneration;
        setGithubLoading();
        const data = await apiRequest('/api/developer/github/notifications');
        if (generation !== state.githubGeneration) return;
        if (!data || typeof data !== 'object') throw new Error('Kasugai returned an incomplete GitHub response.');
        renderGithubActivity(data);
    }

    function renderRootList(roots) {
        const list = byId('developerRootList');
        if (!list) return;
        list.replaceChildren();
        list.setAttribute('aria-busy', 'false');
        if (!Array.isArray(roots) || roots.length === 0) {
            const empty = document.createElement('li');
            empty.className = 'settings-empty';
            empty.textContent = 'No repository roots configured.';
            list.appendChild(empty);
            return;
        }

        roots.forEach(root => {
            const item = document.createElement('li');
            item.className = 'settings-list-item';
            const metadata = document.createElement('span');
            metadata.className = 'developer-root-meta';
            const label = document.createElement('strong');
            label.textContent = String(root.label || 'Repository root');
            const detail = document.createElement('small');
            const source = root.source === 'environment' ? 'Deployment root' : 'Personal root';
            const availability = root.available === false ? ' · unavailable' : '';
            detail.textContent = `${String(root.path || root.display_path || source)}${root.path || root.display_path ? ` · ${source}` : ''}${availability}`;
            metadata.append(label, detail);
            item.appendChild(metadata);

            if (root.source === 'user' && Number.isInteger(Number(root.id)) && Number(root.id) > 0) {
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'settings-remove-btn';
                remove.textContent = 'Remove';
                remove.setAttribute('aria-label', `Remove ${String(root.label || 'repository root')}`);
                remove.addEventListener('click', () => removeRoot(Number(root.id), String(root.label || 'this root')));
                item.appendChild(remove);
            }
            list.appendChild(item);
        });
    }

    async function loadRoots() {
        const roots = await apiRequest('/api/developer/roots');
        if (!Array.isArray(roots)) throw new Error('Kasugai returned an invalid repository root list.');
        renderRootList(roots);
    }

    function renderGithubConnection(data) {
        const configured = Boolean(data?.configured);
        const metadata = data && typeof data.metadata === 'object' ? data.metadata : {};
        const login = String(metadata.login || '').trim();
        const copy = byId('githubConnectionCopy');
        if (copy) {
            copy.textContent = configured
                ? `Connected${login ? ` as @${login}` : ''}. Enter a new token to replace this connection.`
                : 'Connect a personal account to show notifications.';
        }
        const disconnect = byId('disconnectGithubBtn');
        if (disconnect) disconnect.hidden = !configured;
        const submit = byId('githubTokenForm')?.querySelector('button[type="submit"]');
        if (submit) submit.textContent = configured ? 'Replace GitHub token' : 'Connect GitHub';
    }

    async function loadGithubSettings() {
        const data = await apiRequest('/api/developer/github/settings');
        if (!data || typeof data !== 'object') throw new Error('Kasugai returned an invalid GitHub connection status.');
        renderGithubConnection(data);
    }

    async function loadDeveloperSettings() {
        const generation = ++state.settingsGeneration;
        const rootList = byId('developerRootList');
        if (rootList) rootList.setAttribute('aria-busy', 'true');
        const results = await Promise.allSettled([loadRoots(), loadGithubSettings()]);
        if (generation !== state.settingsGeneration) return;
        if (results[0].status === 'rejected') {
            renderRootList([]);
            setSettingsFeedback(byId('developerRootStatus'), results[0].reason.message, 'error');
        }
        if (results[1].status === 'rejected') {
            setSettingsFeedback(byId('githubConnectionStatus'), results[1].reason.message, 'error');
        }
    }

    function openDeveloperSettings(opener) {
        if (window.KasugaiSettingsModal?.open) {
            window.KasugaiSettingsModal.open('developer', opener?.currentTarget || opener || null);
        }
        loadDeveloperSettings();
    }

    async function submitRoot(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const submit = form.querySelector('button[type="submit"]');
        const status = byId('developerRootStatus');
        const path = byId('developerRootPath')?.value.trim() || '';
        const label = byId('developerRootLabel')?.value.trim() || '';
        setSettingsFeedback(status, 'Adding repository root…');
        if (submit) submit.disabled = true;
        try {
            await apiRequest('/api/developer/roots', {
                method: 'POST',
                body: { path, label },
            });
            form.reset();
            setSettingsFeedback(status, 'Repository root added.', 'success');
            await loadRoots();
            refreshCockpit();
        } catch (error) {
            setSettingsFeedback(status, error.message, 'error');
        } finally {
            if (submit) submit.disabled = false;
        }
    }

    async function removeRoot(rootId, label) {
        if (!window.confirm(`Remove “${label}” from the Developer Cockpit?`)) return;
        const status = byId('developerRootStatus');
        setSettingsFeedback(status, 'Removing repository root…');
        try {
            await apiRequest(`/api/developer/roots/${encodeURIComponent(rootId)}`, { method: 'DELETE' });
            setSettingsFeedback(status, 'Repository root removed.', 'success');
            await loadRoots();
            refreshCockpit();
        } catch (error) {
            setSettingsFeedback(status, error.message, 'error');
        }
    }

    async function submitGithubToken(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const input = byId('githubToken');
        const submit = form.querySelector('button[type="submit"]');
        const status = byId('githubConnectionStatus');
        const token = input?.value.trim() || '';
        setSettingsFeedback(status, 'Validating the GitHub connection…');
        if (submit) submit.disabled = true;
        try {
            const result = await apiRequest('/api/developer/github/settings', {
                method: 'PUT',
                body: { token },
            });
            renderGithubConnection(result);
            const login = String(result?.metadata?.login || '').trim();
            setSettingsFeedback(status, `GitHub connected${login ? ` as @${login}` : ''}.`, 'success');
            loadGithubActivity().catch(renderGithubError);
        } catch (error) {
            setSettingsFeedback(status, error.message, 'error');
        } finally {
            if (input) input.value = '';
            if (submit) submit.disabled = false;
        }
    }

    async function disconnectGithub() {
        if (!window.confirm('Disconnect GitHub from the Developer Cockpit?')) return;
        const button = byId('disconnectGithubBtn');
        const status = byId('githubConnectionStatus');
        if (button) button.disabled = true;
        setSettingsFeedback(status, 'Disconnecting GitHub…');
        try {
            await apiRequest('/api/developer/github/settings', { method: 'DELETE' });
            renderGithubConnection({ configured: false, metadata: {} });
            renderGithubActivity({ configured: false, notifications: [] });
            setSettingsFeedback(status, 'GitHub disconnected.', 'success');
        } catch (error) {
            setSettingsFeedback(status, error.message, 'error');
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function refreshCockpit() {
        const generation = ++state.refreshGeneration;
        const refresh = byId('refreshDeveloperCockpit');
        if (refresh) {
            refresh.disabled = true;
            refresh.setAttribute('aria-busy', 'true');
        }
        const results = await Promise.allSettled([loadOverview(), loadGithubActivity()]);
        if (generation !== state.refreshGeneration) return;
        if (results[0].status === 'rejected') renderOverviewError(results[0].reason);
        if (results[1].status === 'rejected') renderGithubError(results[1].reason);
        if (refresh) {
            refresh.disabled = false;
            refresh.removeAttribute('aria-busy');
        }
    }

    function initializeDeveloperCockpit() {
        if (!byId('developerCockpit')) return;
        byId('repositorySearch')?.addEventListener('input', renderRepositories);
        byId('repositoryFilter')?.addEventListener('change', renderRepositories);
        byId('refreshDeveloperCockpit')?.addEventListener('click', refreshCockpit);
        byId('developerRootForm')?.addEventListener('submit', submitRoot);
        byId('githubTokenForm')?.addEventListener('submit', submitGithubToken);
        byId('disconnectGithubBtn')?.addEventListener('click', disconnectGithub);
        document.querySelectorAll('[data-open-developer-settings]').forEach(button => {
            button.addEventListener('click', event => openDeveloperSettings(event.currentTarget));
        });
        document.querySelector('.settings-tab[data-tab="developer"]')?.addEventListener('click', loadDeveloperSettings);
        refreshCockpit();
    }

    if (typeof document !== 'undefined') {
        document.addEventListener('DOMContentLoaded', initializeDeveloperCockpit);
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            filterRepositories,
            readJsonResponse,
            repositoryNeedsSync,
            validatedGithubUrl,
        };
    }
})();
