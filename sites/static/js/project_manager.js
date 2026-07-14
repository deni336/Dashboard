"use strict";

const state = {
    portfolio: {
        summary: {},
        projects: [],
        connections: [],
    },
    workspace: null,
    selectedProjectId: null,
    activeTab: "overview",
    workFilter: "all",
    projectSearch: "",
};

const providerIcons = {
    github: "github",
    gmail: "mail",
    calendar: "calendar-days",
    drive: "hard-drive",
    teams: "messages-square",
    slack: "message-circle",
    jira: "panels-top-left",
    notion: "notebook",
    other: "external-link",
};

const providerDefaults = {
    github: ["GitHub", "https://github.com/"],
    gmail: ["Gmail", "https://mail.google.com/"],
    calendar: ["Google Calendar", "https://calendar.google.com/"],
    drive: ["Google Drive", "https://drive.google.com/"],
    teams: ["Microsoft Teams", "https://teams.microsoft.com/"],
    slack: ["Slack", "https://app.slack.com/"],
    jira: ["Jira", "https://www.atlassian.com/software/jira"],
    notion: ["Notion", "https://www.notion.so/"],
    other: ["", ""],
};

const raidKinds = ["risk", "assumption", "issue", "dependency", "decision"];
const closedStatuses = new Set(["done", "resolved"]);

const byId = (id) => document.getElementById(id);

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function displayLabel(value) {
    if (!value) {
        return "Not set";
    }
    return String(value)
        .replaceAll("_", " ")
        .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value) {
    if (!value) {
        return "Not set";
    }
    const [year, month, day] = String(value).split("-").map(Number);
    const parsed = new Date(year, month - 1, day);
    if (Number.isNaN(parsed.getTime())) {
        return value;
    }
    return new Intl.DateTimeFormat(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
    }).format(parsed);
}

function formatMoney(value) {
    return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
    }).format(Number(value) || 0);
}

function todayIso() {
    const today = new Date();
    const offset = today.getTimezoneOffset() * 60_000;
    return new Date(today.getTime() - offset).toISOString().slice(0, 10);
}

function isOverdue(record) {
    return Boolean(
        record.due_date
        && record.due_date < todayIso()
        && !closedStatuses.has(record.status),
    );
}

function refreshIcons() {
    if (window.lucide) {
        window.lucide.createIcons({
            attrs: {
                "aria-hidden": "true",
            },
        });
    }
}

async function api(url, options = {}) {
    const requestOptions = {
        credentials: "same-origin",
        ...options,
        headers: {
            Accept: "application/json",
            ...(options.headers || {}),
        },
    };

    if (requestOptions.body && typeof requestOptions.body !== "string") {
        requestOptions.headers["Content-Type"] = "application/json";
        requestOptions.body = JSON.stringify(requestOptions.body);
    }

    const response = await fetch(url, requestOptions);
    if (response.redirected && !response.headers.get("content-type")?.includes("application/json")) {
        window.location.assign(response.url);
        throw new Error("Your session has expired");
    }

    if (response.status === 204) {
        return null;
    }

    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
        ? await response.json()
        : { error: `Request failed (${response.status})` };

    if (!response.ok) {
        throw new Error(payload.error || `Request failed (${response.status})`);
    }
    return payload;
}

let toastTimer;
function showToast(message, isError = false) {
    const toast = byId("toast");
    toast.textContent = message;
    toast.classList.toggle("error", isError);
    toast.classList.add("visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 3200);
}

function emptyRow(columns, message) {
    return `<tr><td class="pm-empty-row" colspan="${columns}">${escapeHtml(message)}</td></tr>`;
}

function iconMarkup(name) {
    return `<i data-lucide="${escapeHtml(name)}"></i>`;
}

function statusMarkup(value) {
    return `<span class="pm-status ${escapeHtml(value)}">${escapeHtml(displayLabel(value))}</span>`;
}

function priorityMarkup(value) {
    return `<span class="pm-priority ${escapeHtml(value)}">${escapeHtml(displayLabel(value))}</span>`;
}

function renderPortfolio() {
    const summary = state.portfolio.summary || {};
    byId("metricActive").textContent = summary.active_projects || 0;
    byId("metricRisk").textContent = (summary.at_risk_projects || 0) + (summary.off_track_projects || 0);
    byId("metricOverdue").textContent = summary.overdue_items || 0;
    byId("metricRaid").textContent = summary.open_raid || 0;

    const query = state.projectSearch.trim().toLowerCase();
    const projects = state.portfolio.projects.filter((project) => {
        if (!query) {
            return true;
        }
        return `${project.name} ${project.code} ${project.manager}`.toLowerCase().includes(query);
    });

    byId("projectList").innerHTML = projects.length
        ? projects.map((project) => `
            <button class="pm-project-item ${project.id === state.selectedProjectId ? "active" : ""}"
                    type="button" data-project-id="${project.id}">
                <span class="pm-health-dot ${escapeHtml(project.health)}"></span>
                <span class="pm-project-item-copy">
                    <strong>${escapeHtml(project.name)}</strong>
                    <span>${escapeHtml(project.code)} · ${escapeHtml(displayLabel(project.status))}</span>
                </span>
                <span class="pm-project-item-progress">${Number(project.progress) || 0}%</span>
            </button>
        `).join("")
        : `<div class="pm-empty-copy">${query ? "No matching projects" : "No projects"}</div>`;

    const connections = state.portfolio.connections.slice(0, 5);
    byId("sidebarConnections").innerHTML = connections.map((connection) => `
        <a href="${escapeHtml(connection.url)}" target="_blank" rel="noopener noreferrer"
           title="${escapeHtml(connection.label)}${connection.account ? ` (${escapeHtml(connection.account)})` : ""}">
            ${iconMarkup(providerIcons[connection.provider] || providerIcons.other)}
        </a>
    `).join("");

    refreshIcons();
}

function renderProjectHeader() {
    const project = state.workspace.project;
    byId("projectCode").textContent = project.code;
    byId("projectName").textContent = project.name;
    byId("projectDescription").textContent = project.description || "No project description recorded.";

    const health = byId("projectHealth");
    health.textContent = displayLabel(project.health);
    health.className = `pm-badge ${project.health}`;

    byId("projectBrief").innerHTML = [
        ["Status", displayLabel(project.status)],
        ["Priority", displayLabel(project.priority)],
        ["Manager", project.manager || "Not set"],
        ["Sponsor", project.sponsor || "Not set"],
        ["Start", formatDate(project.start_date)],
        ["Target", formatDate(project.target_date)],
        ["Budget", formatMoney(project.budget)],
    ].map(([label, value]) => `
        <div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>
    `).join("");

    const progress = Math.max(0, Math.min(100, Number(project.progress) || 0));
    byId("progressValue").textContent = `${progress}%`;
    byId("progressBar").style.width = `${progress}%`;
}

function recordAction(record) {
    return `
        <button class="pm-icon-button pm-row-action" type="button" data-edit-record="${record.id}"
                title="Edit ${escapeHtml(record.kind)}" aria-label="Edit ${escapeHtml(record.title)}">
            ${iconMarkup("pencil")}
        </button>
    `;
}

function renderOverviewWork() {
    const records = state.workspace.records
        .filter((record) => ["task", "milestone"].includes(record.kind) && !closedStatuses.has(record.status))
        .slice(0, 6);

    byId("overviewWork").innerHTML = records.length
        ? records.map((record) => `
            <tr>
                <td>
                    <span class="pm-table-primary">
                        <span class="pm-kind">${escapeHtml(displayLabel(record.kind))}</span>
                        <span class="pm-table-title">${escapeHtml(record.title)}</span>
                    </span>
                </td>
                <td>${escapeHtml(record.owner || "Unassigned")}</td>
                <td class="${isOverdue(record) ? "pm-overdue" : ""}">${escapeHtml(formatDate(record.due_date))}</td>
                <td>${statusMarkup(record.status)}</td>
                <td>${recordAction(record)}</td>
            </tr>
        `).join("")
        : emptyRow(5, "No open work items");
}

function renderWorkPlan() {
    let records = state.workspace.records.filter((record) => ["task", "milestone"].includes(record.kind));
    if (state.workFilter !== "all") {
        records = records.filter((record) => record.kind === state.workFilter);
    }

    byId("workTable").innerHTML = records.length
        ? records.map((record) => `
            <tr>
                <td><span class="pm-kind">${escapeHtml(displayLabel(record.kind))}</span></td>
                <td><span class="pm-table-title">${escapeHtml(record.title)}</span></td>
                <td>${priorityMarkup(record.priority)}</td>
                <td>${escapeHtml(record.owner || "Unassigned")}</td>
                <td class="${isOverdue(record) ? "pm-overdue" : ""}">${escapeHtml(formatDate(record.due_date))}</td>
                <td>${statusMarkup(record.status)}</td>
                <td>${recordAction(record)}</td>
            </tr>
        `).join("")
        : emptyRow(7, state.workFilter === "all" ? "No work items" : `No ${state.workFilter}s`);
}

function meetingMarkup(meeting) {
    const notes = meeting.notes || "No general notes recorded.";
    return `
        <article class="pm-meeting-entry">
            <time class="pm-meeting-date" datetime="${escapeHtml(meeting.held_on)}">${escapeHtml(formatDate(meeting.held_on))}</time>
            <div class="pm-meeting-content">
                <h4>${escapeHtml(meeting.title)}</h4>
                ${meeting.attendees ? `<span class="pm-table-subtle">${escapeHtml(meeting.attendees)}</span>` : ""}
                <p>${escapeHtml(notes)}</p>
                <div class="pm-meeting-meta">
                    <div><strong>Decisions</strong><span>${escapeHtml(meeting.decisions || "None recorded")}</span></div>
                    <div><strong>Actions</strong><span>${escapeHtml(meeting.action_items || "None recorded")}</span></div>
                    <div><strong>Next steps</strong><span>${escapeHtml(meeting.next_steps || "None recorded")}</span></div>
                </div>
            </div>
            <button class="pm-icon-button pm-row-action" type="button" data-edit-meeting="${meeting.id}"
                    title="Edit meeting" aria-label="Edit ${escapeHtml(meeting.title)}">
                ${iconMarkup("pencil")}
            </button>
        </article>
    `;
}

function renderMeetings() {
    const meetings = state.workspace.meetings;
    byId("meetingList").innerHTML = meetings.length
        ? meetings.map(meetingMarkup).join("")
        : '<div class="pm-empty-copy">No meetings recorded</div>';
    byId("latestMeeting").innerHTML = meetings.length
        ? meetingMarkup(meetings[0])
        : '<div class="pm-empty-copy">No meetings recorded</div>';
}

function renderRaid() {
    const groups = raidKinds.map((kind) => {
        const records = state.workspace.records.filter((record) => record.kind === kind);
        const items = records.length
            ? records.map((record) => `
                <button class="pm-raid-item" type="button" data-edit-record="${record.id}">
                    <span>
                        <h5>${escapeHtml(record.title)}</h5>
                        <p>${escapeHtml(record.details || record.resolution || `${displayLabel(record.status)} · ${displayLabel(record.priority)}`)}</p>
                    </span>
                    ${statusMarkup(record.status)}
                </button>
            `).join("")
            : '<div class="pm-empty-copy">No entries</div>';
        return `
            <section class="pm-raid-group ${kind}">
                <div class="pm-raid-heading">
                    <h4>${escapeHtml(displayLabel(kind))}</h4>
                    <span>${records.length}</span>
                </div>
                <div class="pm-raid-list">${items}</div>
            </section>
        `;
    });
    byId("raidGrid").innerHTML = groups.join("");
}

function renderStakeholders() {
    const stakeholders = state.workspace.stakeholders;
    byId("stakeholderTable").innerHTML = stakeholders.length
        ? stakeholders.map((stakeholder) => `
            <tr>
                <td><span class="pm-table-title">${escapeHtml(stakeholder.name)}</span></td>
                <td>${escapeHtml(stakeholder.role || "Not set")}</td>
                <td>${escapeHtml(displayLabel(stakeholder.influence))}</td>
                <td>${escapeHtml(displayLabel(stakeholder.engagement))}</td>
                <td>${stakeholder.email
                    ? `<a class="pm-text-link" href="mailto:${escapeHtml(stakeholder.email)}">${escapeHtml(stakeholder.email)}</a>`
                    : '<span class="pm-table-subtle">Not set</span>'}</td>
                <td>
                    <button class="pm-icon-button pm-row-action" type="button" data-edit-stakeholder="${stakeholder.id}"
                            title="Edit stakeholder" aria-label="Edit ${escapeHtml(stakeholder.name)}">
                        ${iconMarkup("pencil")}
                    </button>
                </td>
            </tr>
        `).join("")
        : emptyRow(6, "No stakeholders recorded");
}

function connectionMarkup(connection) {
    const icon = providerIcons[connection.provider] || providerIcons.other;
    const scope = connection.project_id === null ? "Portfolio" : state.workspace.project.code;
    const detail = [connection.account, scope].filter(Boolean).join(" · ");
    return `
        <article class="pm-connection">
            <span class="pm-connection-icon ${escapeHtml(connection.provider)}">${iconMarkup(icon)}</span>
            <div class="pm-connection-copy">
                <a href="${escapeHtml(connection.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(connection.label)}</a>
                <span>${escapeHtml(detail)}</span>
            </div>
            <button class="pm-icon-button pm-row-action" type="button" data-edit-connection="${connection.id}"
                    title="Edit connection" aria-label="Edit ${escapeHtml(connection.label)}">
                ${iconMarkup("pencil")}
            </button>
        </article>
    `;
}

function renderConnections() {
    const connections = state.workspace.connections;
    byId("connectionGrid").innerHTML = connections.length
        ? connections.map(connectionMarkup).join("")
        : '<div class="pm-empty-copy">No connections configured</div>';
}

function activateTab(tabName) {
    state.activeTab = tabName;
    document.querySelectorAll("[data-tab]").forEach((tab) => {
        const active = tab.dataset.tab === tabName;
        tab.classList.toggle("active", active);
        tab.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll("[data-panel]").forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.panel === tabName);
    });
}

function renderWorkspace() {
    const hasProject = Boolean(state.workspace?.project);
    byId("emptyState").hidden = hasProject;
    byId("projectWorkspace").hidden = !hasProject;
    if (!hasProject) {
        refreshIcons();
        return;
    }

    renderProjectHeader();
    renderOverviewWork();
    renderWorkPlan();
    renderMeetings();
    renderRaid();
    renderStakeholders();
    renderConnections();
    activateTab(state.activeTab);
    refreshIcons();
}

async function loadWorkspace(projectId) {
    const requestedProjectId = Number(projectId);
    state.selectedProjectId = requestedProjectId;
    renderPortfolio();
    const workspace = await api(`/api/projects/${requestedProjectId}`);
    if (state.selectedProjectId !== requestedProjectId) {
        return;
    }
    state.workspace = workspace;
    renderWorkspace();
}

async function loadPortfolio(preferredProjectId = state.selectedProjectId) {
    state.portfolio = await api("/api/projects/portfolio");
    const preferred = Number(preferredProjectId);
    const project = state.portfolio.projects.find((item) => item.id === preferred)
        || state.portfolio.projects[0]
        || null;
    state.selectedProjectId = project?.id || null;
    renderPortfolio();
    if (project) {
        await loadWorkspace(project.id);
    } else {
        state.workspace = null;
        renderWorkspace();
    }
}

async function refreshCurrent() {
    if (!state.selectedProjectId) {
        await loadPortfolio();
        return;
    }
    const [portfolio, workspace] = await Promise.all([
        api("/api/projects/portfolio"),
        api(`/api/projects/${state.selectedProjectId}`),
    ]);
    state.portfolio = portfolio;
    state.workspace = workspace;
    renderPortfolio();
    renderWorkspace();
}

function resetDialog(dialogId, formId) {
    const dialog = byId(dialogId);
    const form = byId(formId);
    form.reset();
    form.elements.id.value = "";
    form.querySelector("[data-form-error]").textContent = "";
    return { dialog, form };
}

function populateForm(form, values) {
    Object.entries(values).forEach(([key, value]) => {
        const field = form.elements.namedItem(key);
        if (field) {
            field.value = value ?? "";
        }
    });
}

function openDialog(dialog) {
    if (!dialog.open) {
        dialog.showModal();
    }
    refreshIcons();
}

function openProjectDialog(project = null) {
    const { dialog, form } = resetDialog("projectDialog", "projectForm");
    byId("projectDialogTitle").textContent = project ? "Edit project" : "New project";
    byId("deleteProjectButton").hidden = !project;
    if (project) {
        populateForm(form, project);
    } else {
        form.elements.status.value = "active";
        form.elements.start_date.value = todayIso();
        form.elements.priority.value = "medium";
        form.elements.health.value = "on_track";
    }
    form.dataset.codeTouched = project ? "true" : "false";
    openDialog(dialog);
    form.elements.name.focus();
}

function openRecordDialog(record = null, kind = "task") {
    const { dialog, form } = resetDialog("recordDialog", "recordForm");
    byId("recordDialogTitle").textContent = record ? "Edit item" : "Add item";
    byId("deleteRecordButton").hidden = !record;
    if (record) {
        populateForm(form, record);
    } else {
        form.elements.kind.value = kind;
        form.elements.status.value = "open";
        form.elements.priority.value = "medium";
    }
    openDialog(dialog);
    form.elements.title.focus();
}

function openMeetingDialog(meeting = null) {
    const { dialog, form } = resetDialog("meetingDialog", "meetingForm");
    byId("meetingDialogTitle").textContent = meeting ? "Edit meeting" : "Log meeting";
    byId("deleteMeetingButton").hidden = !meeting;
    if (meeting) {
        populateForm(form, meeting);
    } else {
        form.elements.held_on.value = todayIso();
    }
    openDialog(dialog);
    form.elements.title.focus();
}

function openStakeholderDialog(stakeholder = null) {
    const { dialog, form } = resetDialog("stakeholderDialog", "stakeholderForm");
    byId("stakeholderDialogTitle").textContent = stakeholder ? "Edit stakeholder" : "Add stakeholder";
    byId("deleteStakeholderButton").hidden = !stakeholder;
    if (stakeholder) {
        populateForm(form, stakeholder);
    } else {
        form.elements.influence.value = "medium";
        form.elements.engagement.value = "neutral";
    }
    openDialog(dialog);
    form.elements.name.focus();
}

function openConnectionDialog(connection = null) {
    const { dialog, form } = resetDialog("connectionDialog", "connectionForm");
    byId("connectionDialogTitle").textContent = connection ? "Edit connection" : "Add connection";
    byId("deleteConnectionButton").hidden = !connection;
    if (connection) {
        populateForm(form, connection);
        form.elements.scope.value = connection.project_id === null ? "global" : "project";
    } else {
        form.elements.scope.value = "project";
        form.elements.provider.value = "github";
        const [label, url] = providerDefaults.github;
        form.elements.label.value = label;
        form.elements.url.value = url;
    }
    openDialog(dialog);
    form.elements.label.focus();
}

function formValues(form) {
    return Object.fromEntries(new FormData(form).entries());
}

async function saveForm(form, callback) {
    const error = form.querySelector("[data-form-error]");
    const submit = form.querySelector('[type="submit"]');
    error.textContent = "";
    submit.disabled = true;
    try {
        await callback();
    } catch (requestError) {
        error.textContent = requestError.message;
    } finally {
        submit.disabled = false;
    }
}

function findWorkspaceItem(collection, id) {
    return state.workspace?.[collection].find((item) => item.id === Number(id));
}

async function deleteItem({ url, dialogId, confirmation, success }) {
    if (!window.confirm(confirmation)) {
        return;
    }
    try {
        await api(url, { method: "DELETE" });
        byId(dialogId).close();
        await refreshCurrent();
        showToast(success);
    } catch (error) {
        showToast(error.message, true);
    }
}

function wireForms() {
    const projectForm = byId("projectForm");
    projectForm.addEventListener("submit", (event) => {
        event.preventDefault();
        saveForm(projectForm, async () => {
            const values = formValues(projectForm);
            const id = values.id;
            delete values.id;
            values.budget = Number(values.budget || 0);
            values.progress = Number(values.progress || 0);
            const project = id
                ? await api(`/api/projects/${id}`, { method: "PATCH", body: values })
                : await api("/api/projects", { method: "POST", body: values });
            byId("projectDialog").close();
            await loadPortfolio(project.id);
            showToast(id ? "Project updated" : "Project created");
        });
    });

    projectForm.elements.name.addEventListener("input", () => {
        if (projectForm.elements.id.value || projectForm.dataset.codeTouched === "true") {
            return;
        }
        let code = projectForm.elements.name.value
            .trim()
            .toUpperCase()
            .replace(/[^A-Z0-9]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .slice(0, 16);
        if (code.length === 1) {
            code += "-1";
        }
        projectForm.elements.code.value = code;
    });
    projectForm.elements.code.addEventListener("input", () => {
        projectForm.dataset.codeTouched = "true";
        projectForm.elements.code.value = projectForm.elements.code.value.toUpperCase();
    });

    const recordForm = byId("recordForm");
    recordForm.addEventListener("submit", (event) => {
        event.preventDefault();
        saveForm(recordForm, async () => {
            const values = formValues(recordForm);
            const id = values.id;
            delete values.id;
            await api(
                id ? `/api/project-records/${id}` : `/api/projects/${state.selectedProjectId}/records`,
                { method: id ? "PATCH" : "POST", body: values },
            );
            byId("recordDialog").close();
            await refreshCurrent();
            showToast(id ? "Item updated" : "Item added");
        });
    });

    const meetingForm = byId("meetingForm");
    meetingForm.addEventListener("submit", (event) => {
        event.preventDefault();
        saveForm(meetingForm, async () => {
            const values = formValues(meetingForm);
            const id = values.id;
            delete values.id;
            await api(
                id ? `/api/project-meetings/${id}` : `/api/projects/${state.selectedProjectId}/meetings`,
                { method: id ? "PATCH" : "POST", body: values },
            );
            byId("meetingDialog").close();
            await refreshCurrent();
            showToast(id ? "Meeting updated" : "Meeting logged");
        });
    });

    const stakeholderForm = byId("stakeholderForm");
    stakeholderForm.addEventListener("submit", (event) => {
        event.preventDefault();
        saveForm(stakeholderForm, async () => {
            const values = formValues(stakeholderForm);
            const id = values.id;
            delete values.id;
            await api(
                id ? `/api/project-stakeholders/${id}` : `/api/projects/${state.selectedProjectId}/stakeholders`,
                { method: id ? "PATCH" : "POST", body: values },
            );
            byId("stakeholderDialog").close();
            await refreshCurrent();
            showToast(id ? "Stakeholder updated" : "Stakeholder added");
        });
    });

    const connectionForm = byId("connectionForm");
    connectionForm.elements.provider.addEventListener("change", () => {
        if (connectionForm.elements.id.value) {
            return;
        }
        const [label, url] = providerDefaults[connectionForm.elements.provider.value]
            || providerDefaults.other;
        connectionForm.elements.label.value = label;
        connectionForm.elements.url.value = url;
    });
    connectionForm.addEventListener("submit", (event) => {
        event.preventDefault();
        saveForm(connectionForm, async () => {
            const values = formValues(connectionForm);
            const id = values.id;
            values.project_id = values.scope === "project" ? state.selectedProjectId : null;
            delete values.scope;
            delete values.id;
            await api(
                id ? `/api/project-connections/${id}` : "/api/project-connections",
                { method: id ? "PATCH" : "POST", body: values },
            );
            byId("connectionDialog").close();
            await refreshCurrent();
            showToast(id ? "Connection updated" : "Connection added");
        });
    });
}

function wireDeletes() {
    byId("deleteProjectButton").addEventListener("click", async () => {
        const project = state.workspace?.project;
        if (!project || !window.confirm(`Delete ${project.name} and all of its project records?`)) {
            return;
        }
        try {
            await api(`/api/projects/${project.id}`, { method: "DELETE" });
            byId("projectDialog").close();
            state.selectedProjectId = null;
            state.workspace = null;
            await loadPortfolio(null);
            showToast("Project deleted");
        } catch (error) {
            showToast(error.message, true);
        }
    });

    byId("deleteRecordButton").addEventListener("click", () => {
        const id = byId("recordForm").elements.id.value;
        deleteItem({
            url: `/api/project-records/${id}`,
            dialogId: "recordDialog",
            confirmation: "Delete this project item?",
            success: "Item deleted",
        });
    });
    byId("deleteMeetingButton").addEventListener("click", () => {
        const id = byId("meetingForm").elements.id.value;
        deleteItem({
            url: `/api/project-meetings/${id}`,
            dialogId: "meetingDialog",
            confirmation: "Delete this meeting record?",
            success: "Meeting deleted",
        });
    });
    byId("deleteStakeholderButton").addEventListener("click", () => {
        const id = byId("stakeholderForm").elements.id.value;
        deleteItem({
            url: `/api/project-stakeholders/${id}`,
            dialogId: "stakeholderDialog",
            confirmation: "Delete this stakeholder?",
            success: "Stakeholder deleted",
        });
    });
    byId("deleteConnectionButton").addEventListener("click", () => {
        const id = byId("connectionForm").elements.id.value;
        deleteItem({
            url: `/api/project-connections/${id}`,
            dialogId: "connectionDialog",
            confirmation: "Delete this connection?",
            success: "Connection deleted",
        });
    });
}

function wireActions() {
    document.addEventListener("click", async (event) => {
        const projectButton = event.target.closest("[data-project-id]");
        if (projectButton) {
            try {
                await loadWorkspace(projectButton.dataset.projectId);
            } catch (error) {
                showToast(error.message, true);
            }
            return;
        }

        const tab = event.target.closest("[data-tab]");
        if (tab) {
            activateTab(tab.dataset.tab);
            return;
        }

        const filter = event.target.closest("[data-work-filter]");
        if (filter) {
            state.workFilter = filter.dataset.workFilter;
            document.querySelectorAll("[data-work-filter]").forEach((button) => {
                button.classList.toggle("active", button === filter);
            });
            renderWorkPlan();
            refreshIcons();
            return;
        }

        const editRecord = event.target.closest("[data-edit-record]");
        if (editRecord) {
            openRecordDialog(findWorkspaceItem("records", editRecord.dataset.editRecord));
            return;
        }
        const editMeeting = event.target.closest("[data-edit-meeting]");
        if (editMeeting) {
            openMeetingDialog(findWorkspaceItem("meetings", editMeeting.dataset.editMeeting));
            return;
        }
        const editStakeholder = event.target.closest("[data-edit-stakeholder]");
        if (editStakeholder) {
            openStakeholderDialog(findWorkspaceItem("stakeholders", editStakeholder.dataset.editStakeholder));
            return;
        }
        const editConnection = event.target.closest("[data-edit-connection]");
        if (editConnection) {
            openConnectionDialog(findWorkspaceItem("connections", editConnection.dataset.editConnection));
            return;
        }

        const action = event.target.closest("[data-action]")?.dataset.action;
        if (!action) {
            return;
        }
        if (action === "new-project") {
            openProjectDialog();
        } else if (action === "edit-project") {
            openProjectDialog(state.workspace.project);
        } else if (action === "add-record") {
            openRecordDialog(null, state.activeTab === "raid" ? "risk" : "task");
        } else if (action === "add-raid") {
            openRecordDialog(null, "risk");
        } else if (action === "add-meeting") {
            openMeetingDialog();
        } else if (action === "add-stakeholder") {
            openStakeholderDialog();
        } else if (action === "add-connection") {
            openConnectionDialog();
        }
    });

    byId("newProjectButton").addEventListener("click", () => openProjectDialog());
    byId("projectSearch").addEventListener("input", (event) => {
        state.projectSearch = event.target.value;
        renderPortfolio();
    });

    document.querySelectorAll("[data-close-dialog]").forEach((button) => {
        button.addEventListener("click", () => button.closest("dialog").close());
    });
    document.querySelectorAll("dialog").forEach((dialog) => {
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) {
                dialog.close();
            }
        });
    });
}

async function initialize() {
    wireForms();
    wireDeletes();
    wireActions();
    refreshIcons();
    byId("projectList").innerHTML = '<div class="pm-empty-copy">Loading portfolio...</div>';
    try {
        await loadPortfolio();
    } catch (error) {
        showToast(error.message, true);
        byId("projectList").innerHTML = '<div class="pm-empty-copy">Portfolio unavailable</div>';
    }
}

document.addEventListener("DOMContentLoaded", initialize);
