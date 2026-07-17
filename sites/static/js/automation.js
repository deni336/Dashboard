(function () {
    'use strict';

    const EVENT_SOURCES = new Set(['developer', 'workstation', 'homelab', 'launcher', 'automation']);
    const SEVERITIES = new Set(['info', 'success', 'warning', 'error']);
    const METRIC_OPERATORS = new Set(['gt', 'gte', 'lt', 'lte', 'eq']);
    const RUN_STATUSES = new Set(['running', 'succeeded', 'failed', 'skipped']);
    const OPERATOR_LABELS = Object.freeze({ gt: 'Greater than', gte: 'At least', lt: 'Less than', lte: 'At most', eq: 'Equal to' });
    const OPERATOR_SYMBOLS = Object.freeze({ gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=' });
    const state = {
        rules: [],
        runs: [],
        metrics: [],
        launcherTasks: [],
        editingId: '',
        busyIds: new Set(),
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

    function taskId(value) {
        return typeof value === 'string' && /^[a-f0-9]{32}$/.test(value) ? value : '';
    }

    function metricId(value) {
        return typeof value === 'string' && /^[a-z][a-z0-9._-]{1,95}$/.test(value) ? value : '';
    }

    function safeDate(value) {
        if (typeof value !== 'string') return '';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? '' : date.toISOString();
    }

    function integer(value, minimum, maximum) {
        return Number.isSafeInteger(value) && value >= minimum && value <= maximum ? value : null;
    }

    function finite(value) {
        return typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= 1e9 ? value : null;
    }

    function normalizeTrigger(value) {
        const source = object(value);
        if (!source || typeof source.type !== 'string') return null;
        if (source.type === 'interval') {
            const minutes = integer(source.minutes, 1, 10080);
            return minutes === null ? null : Object.freeze({ type: 'interval', minutes });
        }
        if (source.type === 'daily') {
            const time = typeof source.time === 'string' && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(source.time)
                ? source.time
                : '';
            return time ? Object.freeze({ type: 'daily', time }) : null;
        }
        if (source.type === 'event') {
            if (!EVENT_SOURCES.has(source.source) || !SEVERITIES.has(source.severity)) return null;
            return Object.freeze({ type: 'event', source: source.source, severity: source.severity });
        }
        if (source.type === 'metric') {
            const metric = metricId(source.metric);
            const threshold = finite(source.threshold);
            if (!metric || !METRIC_OPERATORS.has(source.operator) || threshold === null) return null;
            return Object.freeze({ type: 'metric', metric, operator: source.operator, threshold });
        }
        return null;
    }

    function normalizeAction(value) {
        const source = object(value);
        if (!source || typeof source.type !== 'string') return null;
        if (source.type === 'notify') {
            const title = plain(source.title, 120);
            const body = plain(source.body, 1000);
            if (!title || !SEVERITIES.has(source.severity)) return null;
            return Object.freeze({ type: 'notify', title, body, severity: source.severity });
        }
        if (source.type === 'launcher_task') {
            const id = taskId(source.task_id);
            return id ? Object.freeze({ type: 'launcher_task', task_id: id }) : null;
        }
        return null;
    }

    function normalizeRule(value) {
        const source = object(value);
        if (!source) return null;
        const id = opaqueId(source.id);
        const name = plain(source.name, 100);
        const trigger = normalizeTrigger(source.trigger);
        const action = normalizeAction(source.action);
        const cooldown = integer(source.cooldown_minutes, 0, 10080);
        if (!id || !name || !trigger || !action || cooldown === null) return null;
        return Object.freeze({
            id,
            name,
            enabled: source.enabled === true,
            trigger,
            action,
            cooldown_minutes: cooldown,
            last_run_at: safeDate(source.last_run_at),
            next_run_at: safeDate(source.next_run_at),
            created_at: safeDate(source.created_at),
            updated_at: safeDate(source.updated_at),
        });
    }

    function normalizeRun(value) {
        const source = object(value);
        if (!source) return null;
        const id = opaqueId(source.id);
        const ruleId = opaqueId(source.rule_id);
        if (!id || !ruleId || !RUN_STATUSES.has(source.status)) return null;
        return Object.freeze({
            id,
            rule_id: ruleId,
            rule_name: plain(source.rule_name, 100) || 'Automation rule',
            status: source.status,
            triggered_at: safeDate(source.triggered_at),
            completed_at: safeDate(source.completed_at),
            summary: plain(source.summary, 500),
        });
    }

    function normalizeAutomations(payload) {
        const source = object(payload);
        if (!source || !Array.isArray(source.rules) || !Array.isArray(source.runs)) {
            throw new Error('Kasugai returned an invalid automation response.');
        }
        return Object.freeze({
            rules: Object.freeze(source.rules.slice(0, 256).map(normalizeRule).filter(Boolean)),
            runs: Object.freeze(source.runs.slice(0, 100).map(normalizeRun).filter(Boolean)),
        });
    }

    function normalizeMetric(value) {
        const source = object(value);
        if (!source) return null;
        const id = metricId(source.id);
        const label = plain(source.label, 100);
        const unit = plain(source.unit, 32);
        if (!id || !label || !Array.isArray(source.operators)) return null;
        const operators = [...new Set(source.operators.filter(operator => METRIC_OPERATORS.has(operator)))];
        if (!operators.length) return null;
        return Object.freeze({ id, label, unit, operators: Object.freeze(operators) });
    }

    function normalizeLauncherTask(value) {
        const source = object(value);
        if (!source) return null;
        const id = taskId(source.id);
        const title = plain(source.title, 120);
        if (!id || !title) return null;
        return Object.freeze({ id, title, agent_name: plain(source.agent_name, 100) || 'Task runner' });
    }

    function normalizeCatalog(payload) {
        const source = object(payload);
        if (!source || !Array.isArray(source.metrics) || !Array.isArray(source.launcher_tasks)) {
            throw new Error('Kasugai returned an invalid automation catalog.');
        }
        return Object.freeze({
            metrics: Object.freeze(source.metrics.slice(0, 128).map(normalizeMetric).filter(Boolean)),
            launcher_tasks: Object.freeze(source.launcher_tasks.slice(0, 128).map(normalizeLauncherTask).filter(Boolean)),
        });
    }

    function formatTime(value) {
        const date = new Date(String(value || ''));
        if (Number.isNaN(date.getTime())) return 'Never';
        return new Intl.DateTimeFormat(undefined, {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
        }).format(date);
    }

    function capitalize(value) {
        const text = plain(value, 40);
        return text ? `${text.charAt(0).toLocaleUpperCase()}${text.slice(1)}` : '';
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
            if (!response.ok) throw new Error('Kasugai could not complete that automation request.');
            return null;
        }
        let payload;
        try { payload = await response.json(); }
        catch (_error) { throw new Error('Kasugai returned an invalid automation response.'); }
        if (!response.ok) throw new Error(plain(payload?.error, 240) || 'Kasugai could not complete that automation request.');
        return payload;
    }

    async function api(url, options = {}) {
        const method = String(options.method || 'GET').toUpperCase();
        const headers = { Accept: 'application/json' };
        let body;
        if (!['GET', 'HEAD'].includes(method)) {
            const token = csrfToken();
            if (!token) throw new Error('Reload this page before changing automation rules.');
            headers['X-Kasugai-CSRF'] = token;
            if (options.body !== undefined) {
                headers['Content-Type'] = 'application/json';
                body = JSON.stringify(object(options.body) || {});
            }
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
        const element = byId('automationFeedback');
        if (!element) return;
        element.textContent = message || '';
        element.classList.remove('success', 'error');
        if (kind) element.classList.add(kind);
        element.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    }

    function setBuilderFeedback(message, kind) {
        const element = byId('automationBuilderStatus');
        if (!element) return;
        element.textContent = message || '';
        element.classList.remove('success', 'error');
        if (kind) element.classList.add(kind);
        element.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    }

    function metricById(id) { return state.metrics.find(metric => metric.id === id) || null; }
    function launcherTaskById(id) { return state.launcherTasks.find(task => task.id === id) || null; }

    function triggerSummary(trigger) {
        if (trigger.type === 'interval') return `Every ${trigger.minutes} minute${trigger.minutes === 1 ? '' : 's'}`;
        if (trigger.type === 'daily') return `Daily at ${trigger.time}`;
        if (trigger.type === 'event') return `${capitalize(trigger.source)} events - ${capitalize(trigger.severity)} or higher`;
        const metric = metricById(trigger.metric);
        const name = metric?.label || 'Published metric';
        const unit = metric?.unit ? ` ${metric.unit}` : '';
        return `${name} ${OPERATOR_SYMBOLS[trigger.operator]} ${trigger.threshold}${unit}`;
    }

    function actionSummary(action) {
        if (action.type === 'notify') return `${capitalize(action.severity)} notification - ${action.title}`;
        const task = launcherTaskById(action.task_id);
        return task ? `${task.title} - ${task.agent_name}` : 'Approved launcher task';
    }

    function setSummary() {
        const enabled = state.rules.filter(rule => rule.enabled);
        const next = enabled.map(rule => rule.next_run_at).filter(Boolean).sort()[0] || '';
        const completed = state.runs.filter(run => ['succeeded', 'failed'].includes(run.status));
        const succeeded = completed.filter(run => run.status === 'succeeded').length;
        byId('automationRuleCount').textContent = String(state.rules.length);
        byId('automationActiveCount').textContent = String(enabled.length);
        byId('automationNextRun').textContent = next ? formatTime(next) : '—';
        byId('automationSuccessRate').textContent = completed.length ? `${Math.round((succeeded / completed.length) * 100)}%` : '—';
        const status = byId('automationStatus');
        status.textContent = !state.rules.length ? 'No rules' : enabled.length ? `${enabled.length} active` : 'All paused';
        status.classList.remove('is-ok', 'is-warning', 'is-error');
        if (enabled.length) status.classList.add('is-ok');
        else if (state.rules.length) status.classList.add('is-warning');
    }

    function createFlowBlock(label, value) {
        const block = document.createElement('div');
        const caption = document.createElement('span');
        caption.textContent = label;
        const text = document.createElement('strong');
        text.textContent = value;
        block.append(caption, text);
        return block;
    }

    function ruleCard(rule) {
        const card = document.createElement('article');
        card.className = `automation-rule-card${rule.enabled ? '' : ' is-disabled'}`;
        const stateBox = document.createElement('div');
        stateBox.className = 'automation-rule-state';
        const toggle = document.createElement('label');
        toggle.className = 'automation-switch';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = rule.enabled;
        checkbox.disabled = state.busyIds.has(rule.id);
        checkbox.setAttribute('aria-label', `${rule.enabled ? 'Disable' : 'Enable'} ${rule.name}`);
        const track = document.createElement('span');
        track.setAttribute('aria-hidden', 'true');
        toggle.append(checkbox, track);
        stateBox.appendChild(toggle);

        const copy = document.createElement('div');
        copy.className = 'automation-rule-copy';
        const titleRow = document.createElement('div');
        titleRow.className = 'automation-rule-title';
        const title = document.createElement('strong');
        title.textContent = rule.name;
        const kind = document.createElement('span');
        kind.textContent = `${capitalize(rule.trigger.type)} / ${rule.action.type === 'notify' ? 'Notify' : 'Launcher'}`;
        titleRow.append(title, kind);
        const flow = document.createElement('div');
        flow.className = 'automation-rule-flow';
        flow.append(createFlowBlock('Trigger', triggerSummary(rule.trigger)), icon('arrow-right'), createFlowBlock('Action', actionSummary(rule.action)));
        const timing = document.createElement('div');
        timing.className = 'automation-rule-timing';
        const next = document.createElement('span');
        next.append(icon('clock-3'));
        const nextText = document.createElement('span');
        nextText.textContent = `Next ${formatTime(rule.next_run_at)}`;
        next.appendChild(nextText);
        const last = document.createElement('span');
        last.append(icon('history'));
        const lastText = document.createElement('span');
        lastText.textContent = `Last ${formatTime(rule.last_run_at)}`;
        last.appendChild(lastText);
        const cooldown = document.createElement('span');
        cooldown.append(icon('timer-reset'));
        const cooldownText = document.createElement('span');
        cooldownText.textContent = `${rule.cooldown_minutes}m cooldown`;
        cooldown.appendChild(cooldownText);
        timing.append(next, last, cooldown);
        copy.append(titleRow, flow, timing);

        const actions = document.createElement('div');
        actions.className = 'automation-rule-actions';
        const run = document.createElement('button');
        run.type = 'button';
        run.className = 'app-button app-button-primary';
        run.textContent = state.busyIds.has(rule.id) ? 'Running' : 'Run now';
        run.disabled = state.busyIds.has(rule.id);
        run.addEventListener('click', () => runRule(rule));
        const edit = document.createElement('button');
        edit.type = 'button';
        edit.className = 'app-button app-button-secondary';
        edit.textContent = 'Edit';
        edit.addEventListener('click', event => openBuilder(rule, event.currentTarget));
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'app-button app-button-secondary automation-delete';
        remove.textContent = 'Delete';
        remove.addEventListener('click', () => deleteRule(rule));
        actions.append(run, edit, remove);
        checkbox.addEventListener('change', () => toggleRule(rule, checkbox));
        card.append(stateBox, copy, actions);
        return card;
    }

    function renderRules() {
        const container = byId('automationRuleList');
        if (!container) return;
        container.replaceChildren();
        container.setAttribute('aria-busy', 'false');
        if (!state.rules.length) {
            const empty = document.createElement('div');
            empty.className = 'automation-empty-state';
            empty.appendChild(icon('workflow'));
            const title = document.createElement('strong');
            title.textContent = 'Build your first automation';
            const copy = document.createElement('p');
            copy.textContent = 'Schedule a notification, react to a published event, or connect a metric to an eligible local task.';
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'app-button app-button-primary';
            button.textContent = 'Create a rule';
            button.addEventListener('click', event => openBuilder(null, event.currentTarget));
            empty.append(title, copy, button);
            container.appendChild(empty);
        } else state.rules.forEach(rule => container.appendChild(ruleCard(rule)));
        setSummary();
        refreshIcons();
    }

    function renderRuns() {
        const container = byId('automationRunList');
        if (!container) return;
        container.replaceChildren();
        container.setAttribute('aria-busy', 'false');
        if (!state.runs.length) {
            const empty = document.createElement('p');
            empty.className = 'home-empty-copy';
            empty.textContent = 'No automation outcomes yet.';
            container.appendChild(empty);
            return;
        }
        state.runs.slice(0, 12).forEach(run => {
            const row = document.createElement('div');
            row.className = 'automation-run-row';
            row.title = run.summary || run.rule_name;
            const dot = document.createElement('span');
            dot.className = `automation-run-dot is-${run.status}`;
            const copy = document.createElement('span');
            const name = document.createElement('strong');
            name.textContent = run.rule_name;
            const detail = document.createElement('small');
            detail.textContent = run.summary || formatTime(run.completed_at || run.triggered_at);
            copy.append(name, detail);
            const status = document.createElement('span');
            status.textContent = capitalize(run.status);
            row.append(dot, copy, status);
            container.appendChild(row);
        });
        setSummary();
    }

    function renderMetricOptions(selectedId = '') {
        const select = byId('automationMetric');
        if (!select) return;
        const desired = selectedId || select.value;
        select.replaceChildren();
        if (!state.metrics.length) {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = desired ? 'Previously used metric is unavailable' : 'No metrics available';
            select.appendChild(option);
        } else state.metrics.forEach(metric => {
            const option = document.createElement('option');
            option.value = metric.id;
            option.textContent = metric.unit ? `${metric.label} (${metric.unit})` : metric.label;
            select.appendChild(option);
        });
        if (desired && state.metrics.length && !state.metrics.some(metric => metric.id === desired)) {
            const unavailable = document.createElement('option');
            unavailable.value = '';
            unavailable.textContent = 'Previously used metric is unavailable';
            select.prepend(unavailable);
            select.value = '';
        } else select.value = state.metrics.some(metric => metric.id === desired) ? desired : state.metrics[0]?.id || '';
        renderOperatorOptions();
    }

    function renderOperatorOptions(selectedOperator = '') {
        const metric = metricById(byId('automationMetric')?.value || '');
        const select = byId('automationMetricOperator');
        if (!select) return;
        const desired = selectedOperator || select.value;
        select.replaceChildren();
        const operators = metric?.operators || [];
        operators.forEach(operator => {
            const option = document.createElement('option');
            option.value = operator;
            option.textContent = OPERATOR_LABELS[operator];
            select.appendChild(option);
        });
        select.value = operators.includes(desired) ? desired : operators[0] || '';
        byId('automationMetricUnit').textContent = metric?.unit || 'value';
    }

    function renderLauncherTaskOptions(selectedId = '') {
        const select = byId('automationLauncherTask');
        if (!select) return;
        const desired = selectedId || select.value;
        select.replaceChildren();
        if (!state.launcherTasks.length) {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = desired ? 'Previously approved task is no longer eligible' : 'No eligible launcher tasks';
            select.appendChild(option);
        } else state.launcherTasks.forEach(task => {
            const option = document.createElement('option');
            option.value = task.id;
            option.textContent = `${task.title} - ${task.agent_name}`;
            select.appendChild(option);
        });
        if (desired && state.launcherTasks.length && !state.launcherTasks.some(task => task.id === desired)) {
            const unavailable = document.createElement('option');
            unavailable.value = '';
            unavailable.textContent = 'Previously approved task is no longer eligible';
            select.prepend(unavailable);
            select.value = '';
        } else select.value = state.launcherTasks.some(task => task.id === desired) ? desired : state.launcherTasks[0]?.id || '';
    }

    function showGroup(selector, value) {
        document.querySelectorAll(selector).forEach(group => {
            const active = group.getAttribute(selector.includes('trigger') ? 'data-automation-trigger' : 'data-automation-action') === value;
            group.hidden = !active;
            group.querySelectorAll('input, select, textarea').forEach(control => { control.disabled = !active; });
        });
    }

    function updateBuilderGroups() {
        showGroup('[data-automation-trigger]', byId('automationTriggerType').value);
        showGroup('[data-automation-action]', byId('automationActionType').value);
    }

    function resetBuilder() {
        state.editingId = '';
        byId('automationRuleForm')?.reset();
        byId('automationEnabled').checked = true;
        byId('automationIntervalMinutes').value = '60';
        byId('automationDailyTime').value = '09:00';
        byId('automationMetricThreshold').value = '80';
        byId('automationNotifyTitle').value = 'Automation alert';
        byId('automationCooldown').value = '15';
        byId('automationFormMode').textContent = 'New automation';
        byId('automationSaveLabel').textContent = 'Create rule';
        byId('cancelAutomationEdit').hidden = true;
        renderMetricOptions();
        renderLauncherTaskOptions();
        updateBuilderGroups();
        setBuilderFeedback('');
    }

    function fillBuilder(rule) {
        state.editingId = rule.id;
        byId('automationName').value = rule.name;
        byId('automationEnabled').checked = rule.enabled;
        byId('automationTriggerType').value = rule.trigger.type;
        if (rule.trigger.type === 'interval') byId('automationIntervalMinutes').value = String(rule.trigger.minutes);
        else if (rule.trigger.type === 'daily') byId('automationDailyTime').value = rule.trigger.time;
        else if (rule.trigger.type === 'event') {
            byId('automationEventSource').value = rule.trigger.source;
            byId('automationEventSeverity').value = rule.trigger.severity;
        } else {
            renderMetricOptions(rule.trigger.metric);
            renderOperatorOptions(rule.trigger.operator);
            byId('automationMetricThreshold').value = String(rule.trigger.threshold);
        }
        byId('automationActionType').value = rule.action.type;
        if (rule.action.type === 'notify') {
            byId('automationNotifyTitle').value = rule.action.title;
            byId('automationNotifyBody').value = rule.action.body;
            byId('automationNotifySeverity').value = rule.action.severity;
        } else renderLauncherTaskOptions(rule.action.task_id);
        byId('automationCooldown').value = String(rule.cooldown_minutes);
        byId('automationFormMode').textContent = 'Editing automation';
        byId('automationSaveLabel').textContent = 'Save changes';
        byId('cancelAutomationEdit').hidden = false;
        updateBuilderGroups();
        setBuilderFeedback('');
    }

    function openBuilder(rule, trigger) {
        if (rule) fillBuilder(rule);
        else resetBuilder();
        window.KasugaiSettingsModal?.open?.('automation', trigger || null);
        Promise.all([loadCatalog(), loadAutomations()])
            .then(() => {
                if (rule) fillBuilder(state.rules.find(item => item.id === rule.id) || rule);
            })
            .catch(error => setBuilderFeedback(error.message, 'error'));
    }

    function numericInput(id, minimum, maximum, label) {
        const raw = String(byId(id).value || '').trim();
        const value = Number(raw);
        if (!raw) throw new Error(`${label} is required.`);
        if (!Number.isInteger(value) || value < minimum || value > maximum) throw new Error(`${label} must be a whole number from ${minimum} to ${maximum}.`);
        return value;
    }

    function ruleBodyFromForm() {
        const name = plain(byId('automationName').value, 100);
        if (!name) throw new Error('Enter a rule name.');
        const triggerType = byId('automationTriggerType').value;
        let trigger;
        if (triggerType === 'interval') trigger = { type: 'interval', minutes: numericInput('automationIntervalMinutes', 1, 10080, 'Interval') };
        else if (triggerType === 'daily') {
            const time = byId('automationDailyTime').value;
            if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time)) throw new Error('Choose a valid daily time.');
            trigger = { type: 'daily', time };
        } else if (triggerType === 'event') {
            const source = byId('automationEventSource').value;
            const severity = byId('automationEventSeverity').value;
            if (!EVENT_SOURCES.has(source) || !SEVERITIES.has(severity)) throw new Error('Choose a valid event trigger.');
            trigger = { type: 'event', source, severity };
        } else if (triggerType === 'metric') {
            const metric = metricById(byId('automationMetric').value);
            const operator = byId('automationMetricOperator').value;
            const thresholdText = String(byId('automationMetricThreshold').value || '').trim();
            const threshold = Number(thresholdText);
            if (!metric || !metric.operators.includes(operator) || !thresholdText || !Number.isFinite(threshold) || Math.abs(threshold) > 1e9) throw new Error('Choose a valid metric, comparison, and threshold.');
            trigger = { type: 'metric', metric: metric.id, operator, threshold };
        } else throw new Error('Choose a valid trigger type.');

        const actionType = byId('automationActionType').value;
        let action;
        if (actionType === 'notify') {
            const title = plain(byId('automationNotifyTitle').value, 120);
            const body = plain(byId('automationNotifyBody').value, 1000);
            const severity = byId('automationNotifySeverity').value;
            if (!title || !SEVERITIES.has(severity)) throw new Error('Complete the fixed notification fields.');
            action = { type: 'notify', title, body, severity };
        } else if (actionType === 'launcher_task') {
            const task = launcherTaskById(byId('automationLauncherTask').value);
            if (!task) throw new Error('Choose an eligible, non-confirming launcher task.');
            action = { type: 'launcher_task', task_id: task.id };
        } else throw new Error('Choose a valid action type.');

        return {
            name,
            enabled: byId('automationEnabled').checked === true,
            trigger,
            action,
            cooldown_minutes: numericInput('automationCooldown', 0, 10080, 'Cooldown'),
        };
    }

    async function loadAutomations() {
        const payload = normalizeAutomations(await api('/api/automations'));
        state.rules = [...payload.rules];
        state.runs = [...payload.runs];
        renderRules();
        renderRuns();
    }

    async function loadCatalog() {
        const payload = normalizeCatalog(await api('/api/automations/catalog'));
        state.metrics = [...payload.metrics];
        state.launcherTasks = [...payload.launcher_tasks];
        renderMetricOptions();
        renderLauncherTaskOptions();
        renderRules();
    }

    async function refreshAll() {
        byId('automationRuleList')?.setAttribute('aria-busy', 'true');
        byId('automationRunList')?.setAttribute('aria-busy', 'true');
        const results = await Promise.allSettled([loadCatalog(), loadAutomations()]);
        const failure = results.find(result => result.status === 'rejected');
        if (failure) {
            byId('automationRuleList')?.setAttribute('aria-busy', 'false');
            byId('automationRunList')?.setAttribute('aria-busy', 'false');
            const status = byId('automationStatus');
            status.textContent = 'Unavailable';
            status.classList.remove('is-ok', 'is-warning');
            status.classList.add('is-error');
            setFeedback(failure.reason?.message || 'Automation data is unavailable.', 'error');
        } else setFeedback('');
    }

    async function saveRule(event) {
        event.preventDefault();
        const button = byId('saveAutomationRule');
        if (button) button.disabled = true;
        try {
            const body = ruleBodyFromForm();
            const editing = state.rules.find(rule => rule.id === state.editingId);
            if (editing) await api(`/api/automations/${encodeURIComponent(editing.id)}`, { method: 'PATCH', body });
            else await api('/api/automations', { method: 'POST', body });
            setBuilderFeedback(editing ? 'Automation rule updated.' : 'Automation rule created.', 'success');
            state.editingId = '';
            await loadAutomations();
            resetBuilder();
            setBuilderFeedback(editing ? 'Automation rule updated.' : 'Automation rule created.', 'success');
        } catch (error) { setBuilderFeedback(error.message, 'error'); }
        finally { if (button) button.disabled = false; }
    }

    async function toggleRule(rule, checkbox) {
        checkbox.disabled = true;
        state.busyIds.add(rule.id);
        try {
            await api(`/api/automations/${encodeURIComponent(rule.id)}`, { method: 'PATCH', body: { enabled: checkbox.checked } });
            setFeedback(`${rule.name} ${checkbox.checked ? 'enabled' : 'paused'}.`, 'success');
            await loadAutomations();
        } catch (error) {
            checkbox.checked = rule.enabled;
            setFeedback(error.message, 'error');
        } finally {
            state.busyIds.delete(rule.id);
            checkbox.disabled = false;
        }
    }

    async function runRule(rule) {
        if (state.busyIds.has(rule.id)) return;
        state.busyIds.add(rule.id);
        renderRules();
        setFeedback(`Running ${rule.name}...`);
        try {
            await api(`/api/automations/${encodeURIComponent(rule.id)}/run`, { method: 'POST', body: {} });
            setFeedback(`${rule.name} completed.`, 'success');
            await loadAutomations();
        } catch (error) { setFeedback(error.message, 'error'); }
        finally { state.busyIds.delete(rule.id); renderRules(); }
    }

    async function deleteRule(rule) {
        if (!window.confirm(`Delete "${rule.name}" and its schedule? Existing outcome history may be retained.`)) return;
        state.busyIds.add(rule.id);
        renderRules();
        try {
            await api(`/api/automations/${encodeURIComponent(rule.id)}`, { method: 'DELETE' });
            setFeedback(`${rule.name} deleted.`, 'success');
            if (state.editingId === rule.id) resetBuilder();
            await loadAutomations();
        } catch (error) { setFeedback(error.message, 'error'); }
        finally { state.busyIds.delete(rule.id); renderRules(); }
    }

    function initialize() {
        if (!byId('automationModule')) return;
        document.querySelectorAll('[data-open-automation-settings]').forEach(button => button.addEventListener('click', event => openBuilder(null, event.currentTarget)));
        document.querySelector('.settings-tab[data-tab="automation"]')?.addEventListener('click', () => Promise.all([loadCatalog(), loadAutomations()]).catch(error => setBuilderFeedback(error.message, 'error')));
        byId('automationRuleForm')?.addEventListener('submit', saveRule);
        byId('automationTriggerType')?.addEventListener('change', updateBuilderGroups);
        byId('automationActionType')?.addEventListener('change', updateBuilderGroups);
        byId('automationMetric')?.addEventListener('change', () => renderOperatorOptions());
        byId('cancelAutomationEdit')?.addEventListener('click', resetBuilder);
        byId('refreshAutomations')?.addEventListener('click', refreshAll);
        byId('refreshAutomationRuns')?.addEventListener('click', () => loadAutomations().catch(error => setFeedback(error.message, 'error')));
        document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshAll(); });
        state.pollTimer = window.setInterval(() => { if (!document.hidden) loadAutomations().catch(() => {}); }, 30000);
        resetBuilder();
        refreshAll();
    }

    if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initialize);
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            normalizeAction,
            normalizeAutomations,
            normalizeCatalog,
            normalizeLauncherTask,
            normalizeMetric,
            normalizeRule,
            normalizeRun,
            normalizeTrigger,
        };
    }
})();
