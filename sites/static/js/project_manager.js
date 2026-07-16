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
    assistantPreview: null,
    assistantHistory: [],
    assistantSessions: [],
    assistantSessionId: null,
    assistantSessionLoadGeneration: 0,
    assistantSessionsLoadGeneration: 0,
    assistantMessagesHaveMore: false,
    assistantMessagesBeforeId: null,
    assistantProjectId: null,
    assistantRequestGeneration: 0,
    assistantAbortController: null,
    assistantPendingRequest: null,
    assistantApplying: false,
    assistantReadiness: null,
    assistantDrawerGeneration: 0,
    aiSettings: null,
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

const assistantDrawerCloseDelayMs = 240;
let assistantDrawerReturnFocus = null;
let assistantDrawerHideTimer = null;
let assistantDrawerTransitionHandler = null;

function setAssistantDrawerState(drawer, open) {
    if (!drawer) return;
    if (open) {
        drawer.hidden = false;
    }
    drawer.setAttribute("aria-hidden", open ? "false" : "true");
    drawer.classList.toggle("is-open", open);
    drawer.toggleAttribute("inert", !open);
}

function assistantDrawerIsOpen(drawer = byId("assistantDialog")) {
    return Boolean(
        drawer
        && !drawer.hidden
        && drawer.getAttribute("aria-hidden") === "false",
    );
}

function cancelAssistantDrawerHide(drawer) {
    if (assistantDrawerHideTimer !== null) {
        window.clearTimeout(assistantDrawerHideTimer);
        assistantDrawerHideTimer = null;
    }
    if (assistantDrawerTransitionHandler) {
        drawer.removeEventListener("transitionend", assistantDrawerTransitionHandler);
        assistantDrawerTransitionHandler = null;
    }
}

function setAssistantTriggerExpanded(expanded) {
    document.querySelectorAll('[data-action="open-assistant"]').forEach((trigger) => {
        trigger.setAttribute("aria-expanded", expanded ? "true" : "false");
    });
}

function openAssistantDrawer(opener = document.activeElement) {
    const drawer = byId("assistantDialog");
    cancelAssistantDrawerHide(drawer);
    if (opener && !drawer.contains(opener)) {
        assistantDrawerReturnFocus = opener;
    }
    setAssistantDrawerState(drawer, true);
    setAssistantTriggerExpanded(true);
    document.body.classList.add("pm-ai-drawer-open");
    // Flush the drawer's off-screen base state so adding .is-open animates it in.
    drawer.classList.remove("is-open");
    void drawer.offsetWidth;
    drawer.classList.add("is-open");
    const generation = ++state.assistantDrawerGeneration;
    window.requestAnimationFrame(() => {
        if (!assistantDrawerIsOpen(drawer) || generation !== state.assistantDrawerGeneration) return;
        if (document.activeElement !== opener && !drawer.contains(document.activeElement)) return;
        const closeButton = drawer.querySelector("[data-close-dialog]");
        closeButton?.focus({ preventScroll: true });
    });
    return generation;
}

function closeAssistantDrawer({ restoreFocus } = {}) {
    const drawer = byId("assistantDialog");
    if (!assistantDrawerIsOpen(drawer)) return true;
    if (state.assistantApplying) {
        showToast("Selected changes are still being applied", true);
        return false;
    }

    const focusWasInDrawer = drawer.contains(document.activeElement);
    const shouldRestoreFocus = restoreFocus ?? focusWasInDrawer;
    const preferredFocusTarget = (
        assistantDrawerReturnFocus?.isConnected
        && !assistantDrawerReturnFocus.disabled
        && !drawer.contains(assistantDrawerReturnFocus)
    ) ? assistantDrawerReturnFocus : null;
    const fallbackFocusTarget = document.querySelector(
        '[data-action="open-assistant"]:not([hidden]):not(:disabled)',
    );
    if (shouldRestoreFocus) {
        const focusTarget = preferredFocusTarget || fallbackFocusTarget;
        if (focusTarget) {
            focusTarget.focus({ preventScroll: true });
        } else if (focusWasInDrawer && typeof document.activeElement?.blur === "function") {
            document.activeElement.blur();
        }
    }
    state.assistantDrawerGeneration += 1;
    invalidateAssistantPreview();
    drawer.querySelectorAll(
        ".pm-ai-session-toolbar button, .pm-ai-session-toolbar select, #loadOlderAssistantMessagesButton",
    ).forEach((control) => { control.disabled = false; });
    setAssistantDrawerState(drawer, false);
    setAssistantTriggerExpanded(false);
    document.body.classList.remove("pm-ai-drawer-open");

    const finishClose = () => {
        if (drawer.getAttribute("aria-hidden") !== "true") return;
        drawer.hidden = true;
        cancelAssistantDrawerHide(drawer);
    };
    assistantDrawerTransitionHandler = (event) => {
        if (event.target === drawer && event.propertyName === "transform") {
            finishClose();
        }
    };
    drawer.addEventListener("transitionend", assistantDrawerTransitionHandler);
    assistantDrawerHideTimer = window.setTimeout(finishClose, assistantDrawerCloseDelayMs);

    return true;
}

function assistantDrawerRequestMatches(generation, currentGeneration, drawerOpen) {
    return generation === currentGeneration && Boolean(drawerOpen);
}

function assistantDrawerRequestIsCurrent(generation) {
    return assistantDrawerRequestMatches(
        generation,
        state.assistantDrawerGeneration,
        assistantDrawerIsOpen(),
    );
}

function closeAssistantDrawerForProjectChange(nextProjectId) {
    if (!assistantDrawerIsOpen()) return true;
    const currentProjectId = state.assistantProjectId == null
        ? null
        : Number(state.assistantProjectId);
    const normalizedNextProjectId = nextProjectId == null
        ? null
        : Number(nextProjectId);
    if (currentProjectId === normalizedNextProjectId) return true;
    if (state.assistantApplying) {
        showToast("Wait for the selected project changes to finish applying.", true);
        return false;
    }
    return closeAssistantDrawer({ restoreFocus: false });
}

function requestUUID() {
    if (typeof window.crypto?.randomUUID === "function") {
        return window.crypto.randomUUID();
    }
    const bytes = window.crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0"));
    return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

function permissions() {
    return state.workspace?.permissions || {
        role: "viewer",
        can_edit: false,
        can_share: false,
        can_delete: false,
    };
}

function canEdit() {
    return Boolean(permissions().can_edit);
}

function canShare() {
    return Boolean(permissions().can_share);
}

function canUseAssistantSources() {
    return Boolean(canShare() && state.workspace?.capabilities?.ai_sources);
}

function hasRequiredAccess(required) {
    return required === "owner" ? canShare() : canEdit();
}

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
        const error = new Error(payload.error || `Request failed (${response.status})`);
        error.status = response.status;
        error.payload = payload;
        throw error;
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
                    ${project.access_role !== "owner" ? `<span class="pm-project-shared">Shared / ${escapeHtml(displayLabel(project.access_role))}</span>` : ""}
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

    const access = byId("projectAccess");
    access.hidden = project.access_role === "owner";
    access.textContent = `Shared ${displayLabel(project.access_role)}`;
    access.className = `pm-badge pm-access-badge ${project.access_role}`;

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
    if (!canEdit()) {
        return "";
    }
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
    const editAction = canEdit() ? `
        <button class="pm-icon-button pm-row-action" type="button" data-edit-meeting="${meeting.id}"
                title="Edit meeting" aria-label="Edit ${escapeHtml(meeting.title)}">
            ${iconMarkup("pencil")}
        </button>
    ` : "";
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
            ${editAction}
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
            ? records.map((record) => {
                const tag = canEdit() ? "button" : "div";
                const editAttributes = canEdit() ? `type="button" data-edit-record="${record.id}"` : "";
                return `
                    <${tag} class="pm-raid-item${canEdit() ? "" : " pm-raid-item-readonly"}" ${editAttributes}>
                        <span>
                            <h5>${escapeHtml(record.title)}</h5>
                            <p>${escapeHtml(record.details || record.resolution || `${displayLabel(record.status)} / ${displayLabel(record.priority)}`)}</p>
                        </span>
                        ${statusMarkup(record.status)}
                    </${tag}>
                `;
            }).join("")
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
                <td>${canEdit() ? `
                    <button class="pm-icon-button pm-row-action" type="button" data-edit-stakeholder="${stakeholder.id}"
                            title="Edit stakeholder" aria-label="Edit ${escapeHtml(stakeholder.name)}">
                        ${iconMarkup("pencil")}
                    </button>
                ` : ""}</td>
            </tr>
        `).join("")
        : emptyRow(6, "No stakeholders recorded");
}

function connectionMarkup(connection) {
    const icon = providerIcons[connection.provider] || providerIcons.other;
    const scope = connection.project_id === null ? "Portfolio" : state.workspace.project.code;
    const detail = [connection.account, scope].filter(Boolean).join(" / ");
    return `
        <article class="pm-connection">
            <span class="pm-connection-icon ${escapeHtml(connection.provider)}">${iconMarkup(icon)}</span>
            <div class="pm-connection-copy">
                <a href="${escapeHtml(connection.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(connection.label)}</a>
                <span>${escapeHtml(detail)}</span>
            </div>
            ${canShare() ? `<button class="pm-icon-button pm-row-action" type="button" data-edit-connection="${connection.id}"
                    title="Edit connection" aria-label="Edit ${escapeHtml(connection.label)}">
                ${iconMarkup("pencil")}
            </button>` : ""}
        </article>
    `;
}

function renderConnections() {
    const connections = state.workspace.connections;
    byId("connectionGrid").innerHTML = connections.length
        ? connections.map(connectionMarkup).join("")
        : '<div class="pm-empty-copy">No connections configured</div>';
}

function renderShares() {
    const shares = state.workspace?.shares || [];
    byId("shareList").innerHTML = shares.length
        ? shares.map((share) => `
            <tr>
                <td><span class="pm-table-title">${escapeHtml(share.invited_email)}</span></td>
                <td>
                    <select class="pm-share-role" data-share-role="${share.id}" aria-label="Access for ${escapeHtml(share.invited_email)}">
                        <option value="viewer"${share.role === "viewer" ? " selected" : ""}>Viewer</option>
                        <option value="editor"${share.role === "editor" ? " selected" : ""}>Editor</option>
                    </select>
                </td>
                <td>${statusMarkup(share.status)}</td>
                <td>${share.status === "pending" ? escapeHtml(formatDate(share.expires_at?.slice(0, 10))) : "Accepted"}</td>
                <td>
                    <span class="pm-share-actions">
                        ${share.status === "pending" ? `
                            <button class="pm-icon-button pm-row-action" type="button" data-resend-share="${share.id}"
                                    title="Create a new invitation link" aria-label="Create a new invitation link for ${escapeHtml(share.invited_email)}">
                                ${iconMarkup("refresh-cw")}
                            </button>
                        ` : ""}
                        <button class="pm-icon-button pm-row-action pm-share-revoke" type="button" data-delete-share="${share.id}"
                                title="Revoke access" aria-label="Revoke access for ${escapeHtml(share.invited_email)}">
                            ${iconMarkup("user-round-x")}
                        </button>
                    </span>
                </td>
            </tr>
        `).join("")
        : emptyRow(5, "Only you have access");
}

function applyPermissions() {
    document.querySelectorAll("[data-requires]").forEach((element) => {
        const lacksAccess = !hasRequiredAccess(element.dataset.requires);
        element.hidden = lacksAccess;
    });
    byId("projectWorkspace").classList.toggle("pm-readonly", !canEdit());
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
    renderShares();
    applyPermissions();
    activateTab(state.activeTab);
    refreshIcons();
}

async function loadWorkspace(projectId) {
    const requestedProjectId = Number(projectId);
    if (!closeAssistantDrawerForProjectChange(requestedProjectId)) return;
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
    if (!closeAssistantDrawerForProjectChange(project?.id || null)) return;
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

function aiIsReady(settings = state.aiSettings) {
    return Boolean(settings?.configured && settings?.ready === true);
}

function aiReadinessMessage(settings = state.aiSettings) {
    if (typeof settings?.message === "string" && settings.message.trim()) {
        return settings.message.trim();
    }
    if (!settings || !Object.prototype.hasOwnProperty.call(settings, "ready")) {
        return "Kasugai could not verify live model readiness. Update or restart the Kasugai dashboard, then check the model status again.";
    }
    if (!settings.configured) {
        return "The AI model is not configured. Start the private model service before using Ask Kasugai.";
    }
    if (settings.readiness_status === "model_missing") {
        return `The model runner is online, but ${settings.model || "the configured model"} is not installed. Pull the model, then check again.`;
    }
    if (settings.readiness_status === "unavailable") {
        return "The AI model runner cannot be reached. Start the private model service, then check again.";
    }
    return "The AI model is not ready. Check the model service and try again.";
}

function selectAssistantReadiness(sessionId, sessionReadiness, defaultSettings) {
    return sessionId ? sessionReadiness : defaultSettings;
}

function effectiveAssistantReadiness() {
    return selectAssistantReadiness(
        state.assistantSessionId,
        state.assistantReadiness,
        state.aiSettings,
    );
}

function aiCredentialErrorMessage(settings = state.aiSettings) {
    if (settings?.provider === "openai") {
        return "Your saved personal OpenAI API key cannot be read. Replace or remove it before using the hosted assistant.";
    }
    if (settings?.provider === "disabled") {
        return "A previously saved OpenAI API key cannot be read. It is not used while AI is disabled and can be removed here.";
    }
    return "A previously saved OpenAI API key cannot be read. It is not used by the local model and can be removed here.";
}

function aiUsesHostedProvider(settings = state.aiSettings) {
    return settings?.provider === "openai";
}

function assistantDisclosureText({ sessionId, readiness, backend, model }) {
    if (!aiIsReady(readiness)) {
        const historyNotice = sessionId
            ? "You can still read or delete this saved conversation."
            : "You can still browse or delete saved conversations.";
        return `No project data is being sent to an AI model. ${aiReadinessMessage(readiness)} ${historyNotice}`;
    }
    const processing = backend === "openai"
        ? `the hosted OpenAI ${model} model`
        : `the private local ${model} model`;
    return `When you generate a preview, this project's brief, work items, meetings, and stakeholders are processed by ${processing}. Selected GitHub and email evidence is included when enabled. Your conversation is isolated from other users. Changes are only applied after you review and confirm them.`;
}

function assistantSessionReadinessUrl(projectId, sessionId) {
    return `/api/projects/${projectId}/assistant/sessions/${encodeURIComponent(sessionId)}?limit=1`;
}

function renderAISettings() {
    const settings = state.aiSettings || {};
    const status = byId("aiModelStatus");
    const help = byId("aiModelHelp");
    const removeLegacyKey = byId("removeLegacyOpenAIKeyButton");
    const hostedKeyForm = byId("openAISettingsForm");
    const removeHostedKey = byId("removeOpenAIKeyButton");
    const isHostedOpenAI = aiUsesHostedProvider(settings);
    const isDisabled = settings.provider === "disabled";
    const ready = aiIsReady(settings);
    const readinessError = new Set(["unauthorized", "credential_error", "needs_api_key"])
        .has(settings.readiness_status);
    status.classList.toggle("configured", ready);
    status.classList.toggle(
        "error",
        Boolean(settings.credential_error) || !settings.configured || readinessError,
    );
    status.classList.toggle(
        "unavailable",
        Boolean(settings.configured) && !ready && !settings.credential_error && !readinessError,
    );
    hostedKeyForm.hidden = !isHostedOpenAI;
    byId("localAISettingsActions").hidden = isHostedOpenAI;
    removeHostedKey.hidden = !isHostedOpenAI || !settings.personal_key_configured;
    removeLegacyKey.hidden = isHostedOpenAI || !settings.personal_key_configured;
    byId("openAIKeyLabel").textContent = settings.personal_key_configured
        ? "Replacement personal OpenAI API key"
        : "Personal OpenAI API key";
    byId("openAIKeyInput").placeholder = settings.personal_key_configured
        ? "Enter a new key to replace your saved key"
        : "Enter your OpenAI API key";
    byId("saveOpenAIKeyLabel").textContent = settings.personal_key_configured
        ? "Replace key"
        : "Save key";
    help.textContent = isDisabled
        ? "The core Kasugai services are running without an AI model service. Start the private Ollama overlay to enable Ask Kasugai."
        : isHostedOpenAI
            ? "Kasugai uses the hosted OpenAI API with your encrypted personal key or the server-provided fallback. Conversation history remains isolated by authenticated Kasugai user."
            : "Kasugai can use a downloaded OpenAI open-weight model through its private local runner. Each authenticated user has separate project chat sessions; no personal API key is required.";
    if (settings.credential_error) {
        status.textContent = aiCredentialErrorMessage(settings);
    } else if (ready) {
        const provider = settings.provider_label || settings.provider || "Local model runner";
        const legacyNotice = !isHostedOpenAI && settings.personal_key_configured
            ? " A previously saved hosted-API key remains encrypted but is not used; you may remove it below."
            : "";
        const credentialNotice = isHostedOpenAI
            ? settings.credential_source === "personal"
                ? " Your personal API key is active."
                : " The server-provided API key is active; saving a personal key overrides it for your account."
            : "";
        status.textContent = `${provider} is ready with ${settings.model || "gpt-oss"}.${credentialNotice} Conversation history is stored privately for your authenticated Kasugai account.${legacyNotice}`;
    } else {
        status.textContent = aiReadinessMessage(settings);
    }
}

function setAISettings(settings) {
    state.aiSettings = settings;
    if (!state.assistantSessionId) {
        state.assistantReadiness = settings;
    }
    renderAISettings();
    renderAssistantDisclosure();
}

async function loadAISettings({ drawerGeneration } = {}) {
    const settings = await api("/api/project-ai/settings");
    if (
        drawerGeneration !== undefined
        && !assistantDrawerRequestIsCurrent(drawerGeneration)
    ) return null;
    setAISettings(settings);
    return settings;
}

async function openAISettingsDialog() {
    const dialog = byId("aiSettingsDialog");
    const hostedKeyForm = byId("openAISettingsForm");
    hostedKeyForm.reset();
    hostedKeyForm.querySelector("[data-ai-key-error]").textContent = "";
    hostedKeyForm.hidden = true;
    byId("localAISettingsActions").hidden = true;
    byId("aiModelStatus").textContent = "Loading model status...";
    byId("aiModelStatus").className = "pm-ai-model-status";
    openDialog(dialog);
    try {
        await loadAISettings();
        if (state.aiSettings?.provider === "openai") {
            byId("openAIKeyInput").focus();
        }
    } catch (error) {
        byId("aiModelStatus").textContent = error.message;
        byId("aiModelStatus").classList.add("error");
    }
}

function renderAssistantDisclosure() {
    const selectedSession = state.assistantSessions.find(
        (chat) => chat.id === state.assistantSessionId,
    );
    const readiness = effectiveAssistantReadiness();
    const backend = readiness?.provider
        || selectedSession?.backend
        || state.aiSettings?.provider
        || "ollama";
    const model = readiness?.model
        || selectedSession?.model
        || state.aiSettings?.model
        || "gpt-oss";
    const disclosure = byId("assistantDisclosure");
    const ready = aiIsReady(readiness);
    disclosure.classList.toggle("unavailable", !ready);
    disclosure.dataset.readinessStatus = readiness?.readiness_status || "unknown";
    disclosure.textContent = assistantDisclosureText({
        sessionId: state.assistantSessionId,
        readiness,
        backend,
        model,
    });
}

function wireAISettings() {
    const dialog = byId("aiSettingsDialog");
    const hostedForm = byId("openAISettingsForm");
    const hostedInput = byId("openAIKeyInput");
    const hostedRemove = byId("removeOpenAIKeyButton");
    const hostedError = hostedForm.querySelector("[data-ai-key-error]");

    function setHostedBusy(busy) {
        hostedForm.toggleAttribute("aria-busy", busy);
        hostedForm.querySelectorAll("button, input").forEach((control) => {
            control.disabled = busy;
        });
    }

    function finishCredentialChange(settings, message) {
        setAISettings(settings);
        hostedInput.value = "";
        showToast(message);
    }

    hostedForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const apiKey = hostedInput.value;
        hostedInput.value = "";
        hostedError.textContent = "";
        setHostedBusy(true);
        try {
            const settings = await api("/api/project-ai/settings", {
                method: "PUT",
                body: { api_key: apiKey },
            });
            finishCredentialChange(settings, "Personal OpenAI API key saved");
        } catch (requestError) {
            hostedError.textContent = requestError.message;
        } finally {
            hostedInput.value = "";
            setHostedBusy(false);
            hostedInput.focus();
        }
    });

    hostedRemove.addEventListener("click", async () => {
        if (!window.confirm("Remove your personal OpenAI API key from Kasugai?")) return;
        hostedInput.value = "";
        hostedError.textContent = "";
        setHostedBusy(true);
        try {
            const settings = await api("/api/project-ai/settings", { method: "DELETE" });
            const message = settings.credential_source === "deployment"
                ? "Personal key removed; the server-provided key is now active"
                : "Personal OpenAI API key removed";
            finishCredentialChange(settings, message);
        } catch (requestError) {
            hostedError.textContent = requestError.message;
        } finally {
            hostedInput.value = "";
            setHostedBusy(false);
        }
    });

    byId("removeLegacyOpenAIKeyButton").addEventListener("click", async () => {
        if (!window.confirm("Permanently remove the saved personal OpenAI API key?")) return;
        const button = byId("removeLegacyOpenAIKeyButton");
        button.disabled = true;
        try {
            setAISettings(await api("/api/project-ai/settings", { method: "DELETE" }));
            showToast("Saved OpenAI API key removed");
        } catch (error) {
            showToast(error.message, true);
        } finally {
            button.disabled = false;
        }
    });

    dialog.addEventListener("close", () => {
        hostedInput.value = "";
        hostedError.textContent = "";
    });
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
    byId("deleteProjectButton").hidden = !project || !permissions().can_delete;
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
    form.elements.scope.disabled = Boolean(connection);
    form.elements.scope.querySelector('option[value="global"]').disabled = !canShare();
    if (!canShare() && !connection) {
        form.elements.scope.value = "project";
    }
    openDialog(dialog);
    form.elements.label.focus();
}

function showInvitation(payload) {
    const result = byId("inviteResult");
    if (!payload.invitationUrl) {
        result.hidden = true;
        return;
    }
    const project = state.workspace.project;
    const email = payload.share.invited_email;
    const subject = `Invitation to collaborate on ${project.name}`;
    const body = [
        `You have been invited as a ${payload.share.role} on ${project.name} (${project.code}).`,
        "",
        payload.invitationUrl,
        "",
        `Sign in to Kasugai with ${email} to accept. The invitation expires in seven days.`,
    ].join("\n");
    byId("invitationUrl").value = payload.invitationUrl;
    byId("emailInvitationLink").href = `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    result.hidden = false;
    refreshIcons();
}

function openShareDialog() {
    if (!canShare()) {
        showToast("Owner access is required", true);
        return;
    }
    const form = byId("shareForm");
    form.reset();
    form.elements.role.value = "viewer";
    form.querySelector("[data-form-error]").textContent = "";
    byId("inviteResult").hidden = true;
    renderShares();
    openDialog(byId("shareDialog"));
    form.elements.email.focus();
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
            values.project_id = connectionForm.elements.scope.value === "project" ? state.selectedProjectId : null;
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

    const shareForm = byId("shareForm");
    shareForm.addEventListener("submit", (event) => {
        event.preventDefault();
        saveForm(shareForm, async () => {
            const payload = await api(`/api/projects/${state.selectedProjectId}/shares`, {
                method: "POST",
                body: formValues(shareForm),
            });
            await refreshCurrent();
            showInvitation(payload);
            shareForm.elements.email.value = "";
            showToast(payload.invitationUrl ? "Invitation link created" : "Access updated");
        });
    });
}

function wireDeletes() {
    byId("deleteProjectButton").addEventListener("click", async () => {
        const project = state.workspace?.project;
        if (!project || !window.confirm(`Delete ${project.name} and all of its project records?`)) {
            return;
        }
        if (!closeAssistantDrawerForProjectChange(null)) return;
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
        if (!canShare()) return;
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
            if (!canEdit()) {
                return;
            }
            openRecordDialog(findWorkspaceItem("records", editRecord.dataset.editRecord));
            return;
        }
        const editMeeting = event.target.closest("[data-edit-meeting]");
        if (editMeeting) {
            if (!canEdit()) {
                return;
            }
            openMeetingDialog(findWorkspaceItem("meetings", editMeeting.dataset.editMeeting));
            return;
        }
        const editStakeholder = event.target.closest("[data-edit-stakeholder]");
        if (editStakeholder) {
            if (!canEdit()) {
                return;
            }
            openStakeholderDialog(findWorkspaceItem("stakeholders", editStakeholder.dataset.editStakeholder));
            return;
        }
        const editConnection = event.target.closest("[data-edit-connection]");
        if (editConnection) {
            if (!canShare()) {
                return;
            }
            openConnectionDialog(findWorkspaceItem("connections", editConnection.dataset.editConnection));
            return;
        }

        const resendShare = event.target.closest("[data-resend-share]");
        if (resendShare) {
            const share = state.workspace?.shares.find((item) => item.id === Number(resendShare.dataset.resendShare));
            if (!share || !canShare()) {
                return;
            }
            resendShare.disabled = true;
            try {
                const payload = await api(`/api/projects/${state.selectedProjectId}/shares`, {
                    method: "POST",
                    body: { email: share.invited_email, role: share.role },
                });
                await refreshCurrent();
                showInvitation(payload);
                showToast("New invitation link created");
            } catch (error) {
                showToast(error.message, true);
                resendShare.disabled = false;
            }
            return;
        }

        const deleteShare = event.target.closest("[data-delete-share]");
        if (deleteShare) {
            const share = state.workspace?.shares.find((item) => item.id === Number(deleteShare.dataset.deleteShare));
            if (!share || !canShare() || !window.confirm(`Revoke project access for ${share.invited_email}?`)) {
                return;
            }
            try {
                await api(`/api/project-shares/${share.id}`, { method: "DELETE" });
                await refreshCurrent();
                byId("inviteResult").hidden = true;
                showToast("Project access revoked");
            } catch (error) {
                showToast(error.message, true);
            }
            return;
        }

        const actionElement = event.target.closest("[data-action]");
        const action = actionElement?.dataset.action;
        if (!action) {
            return;
        }
        if (action === "open-ai-settings") {
            await openAISettingsDialog();
        } else if (action === "new-project") {
            openProjectDialog();
        } else if (action === "share-project") {
            openShareDialog();
        } else if (action === "edit-project") {
            if (canEdit()) {
                openProjectDialog(state.workspace.project);
            }
        } else if (action === "add-record") {
            if (canEdit()) {
                openRecordDialog(null, state.activeTab === "raid" ? "risk" : "task");
            }
        } else if (action === "add-raid") {
            if (canEdit()) {
                openRecordDialog(null, "risk");
            }
        } else if (action === "add-meeting") {
            if (canEdit()) {
                openMeetingDialog();
            }
        } else if (action === "add-stakeholder") {
            if (canEdit()) {
                openStakeholderDialog();
            }
        } else if (action === "add-connection") {
            if (canShare()) {
                openConnectionDialog();
            }
        } else if (action === "open-assistant") {
            if (canEdit()) {
                if (assistantDrawerIsOpen()) {
                    closeAssistantDrawer();
                    return;
                }
                window.KasugaiTeamRoom?.close({ restoreFocus: false });
                if (state.assistantProjectId !== state.selectedProjectId) {
                    state.assistantHistory = [];
                    state.assistantSessions = [];
                    state.assistantSessionId = null;
                    state.assistantMessagesHaveMore = false;
                    state.assistantMessagesBeforeId = null;
                    state.assistantPendingRequest = null;
                    state.assistantReadiness = null;
                    state.assistantProjectId = state.selectedProjectId;
                }
                invalidateAssistantPreview();
                const assistantForm = byId("assistantForm");
                assistantForm.reset();
                assistantForm.querySelector("[data-form-error]").textContent = "";
                byId("assistantSourceOptions").hidden = !canUseAssistantSources();
                renderAssistantSessions();
                renderAssistantConversation();
                renderAssistantDisclosure();
                const drawerGeneration = openAssistantDrawer(actionElement);
                try {
                    await loadAISettings({ drawerGeneration });
                } catch (error) {
                    if (!assistantDrawerRequestIsCurrent(drawerGeneration)) return;
                    setAISettings({
                        ...(state.aiSettings || {}),
                        configured: false,
                        ready: false,
                        readiness_status: "unavailable",
                        message: `Could not load the current AI model status: ${error.message}`,
                    });
                    showToast(error.message, true);
                }
                if (!assistantDrawerRequestIsCurrent(drawerGeneration)) return;
                try {
                    await loadAssistantSessions({ drawerGeneration });
                } catch (error) {
                    if (!assistantDrawerRequestIsCurrent(drawerGeneration)) return;
                    startNewAssistantSession();
                    assistantForm.querySelector("[data-form-error]").textContent = `Could not load saved conversations: ${error.message}`;
                    showToast(error.message, true);
                }
                if (!assistantDrawerRequestIsCurrent(drawerGeneration)) return;
                renderAssistantDisclosure();
                const drawer = byId("assistantDialog");
                const closeButton = drawer.querySelector("[data-close-dialog]");
                if (
                    document.activeElement === drawer
                    || document.activeElement === closeButton
                ) {
                    assistantForm.elements.message.focus({ preventScroll: true });
                }
            }
        }
    });

    document.addEventListener("change", async (event) => {
        const roleSelect = event.target.closest("[data-share-role]");
        if (!roleSelect || !canShare()) {
            return;
        }
        roleSelect.disabled = true;
        try {
            await api(`/api/project-shares/${roleSelect.dataset.shareRole}`, {
                method: "PATCH",
                body: { role: roleSelect.value },
            });
            await refreshCurrent();
            showToast("Project access updated");
        } catch (error) {
            await refreshCurrent();
            showToast(error.message, true);
        }
    });

    byId("newProjectButton").addEventListener("click", () => openProjectDialog());
    byId("projectSearch").addEventListener("input", (event) => {
        state.projectSearch = event.target.value;
        renderPortfolio();
    });

    byId("copyInvitationButton").addEventListener("click", async () => {
        const input = byId("invitationUrl");
        try {
            await navigator.clipboard.writeText(input.value);
        } catch (error) {
            input.select();
            document.execCommand("copy");
        }
        showToast("Invitation link copied");
    });

    document.querySelectorAll("[data-close-dialog]").forEach((button) => {
        button.addEventListener("click", () => {
            if (button.closest("#assistantDialog")) {
                closeAssistantDrawer();
                return;
            }
            const dialog = button.closest("dialog");
            dialog?.close();
        });
    });
    document.querySelectorAll("dialog").forEach((dialog) => {
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) {
                dialog.close();
            }
        });
    });
}

function renderAssistantPreview(proposal) {
    const evidenceById = new Map((proposal.evidence || []).map((source) => [
        source.evidence_id,
        source.label || source.source || source.evidence_id,
    ]));
    byId("assistantAnswer").innerHTML = `
        <h3>${escapeHtml(proposal.summary || "Kasugai review")}</h3>
        <p>${escapeHtml(proposal.answer || "")}</p>
        <small>Model: ${escapeHtml(proposal.model || "Local AI")}</small>`;
    byId("assistantActions").innerHTML = proposal.actions.length
        ? proposal.actions.map((action, index) => {
            const target = action.record_id
                ? state.workspace?.records?.find((record) => record.id === action.record_id)?.title || `Record #${action.record_id}`
                : "";
            const sourceLabels = (action.evidence_refs || [])
                .map((reference) => evidenceById.get(reference) || reference);
            return `
            <article class="pm-ai-action">
                <label class="pm-ai-action-select">
                    <input type="checkbox" data-ai-action-index="${index}" checked>
                    <strong>${escapeHtml(displayLabel(action.type))}</strong>
                </label>
                ${target ? `<span>Target: ${escapeHtml(target)}</span>` : ""}
                <span>${escapeHtml(action.reason || "Proposed by Ask Kasugai")}</span>
                <span class="pm-ai-action-sources">Basis: ${escapeHtml(
                    sourceLabels.length ? sourceLabels.join(", ") : "your request",
                )}</span>
                <code>${escapeHtml(JSON.stringify(action.fields, null, 2))}</code>
            </article>`;
        }).join("")
        : '<div class="pm-empty-copy">No project changes proposed.</div>';
    const evidenceItems = (proposal.evidence || []).flatMap((source) => (source.items || []).map((item) => ({
        source: source.label || source.source,
        label: item.title || item.subject || item.message || item.repository || item.sha || item.type || "Source item",
        url: item.url || source.url,
    })));
    byId("assistantEvidence").innerHTML = evidenceItems.length
        ? `<strong>Evidence reviewed</strong><ul>${evidenceItems.slice(0, 20).map((item) => `
            <li>${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.label)}</a>` : escapeHtml(item.label)} <span class="pm-table-subtle">${escapeHtml(item.source)}</span></li>`).join("")}</ul>`
        : "";
    byId("assistantWarnings").innerHTML = (proposal.warnings || []).map((warning) => `<div>${escapeHtml(warning)}</div>`).join("");
    byId("applyAssistantButton").hidden = !proposal.actions.length;
    byId("applyAssistantButton").disabled = false;
    const result = byId("assistantResult");
    result.hidden = false;
    refreshIcons();
    window.requestAnimationFrame(() => {
        if (!assistantDrawerIsOpen()) return;
        result.scrollIntoView({
            block: "start",
            behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
                ? "auto"
                : "smooth",
        });
    });
}

function selectedAssistantActions() {
    return [...document.querySelectorAll("[data-ai-action-index]:checked")]
        .map((input) => Number(input.dataset.aiActionIndex));
}

function invalidateAssistantPreview() {
    if (state.assistantApplying) return;
    state.assistantRequestGeneration += 1;
    state.assistantAbortController?.abort();
    state.assistantAbortController = null;
    state.assistantPreview = null;
    const form = byId("assistantForm");
    if (form) {
        [...form.elements].forEach((control) => { control.disabled = false; });
        form.classList.remove("pm-ai-form-busy");
        form.removeAttribute("aria-busy");
    }
    byId("assistantResult").hidden = true;
    byId("applyAssistantButton").disabled = true;
}

function setAssistantApplying(applying) {
    state.assistantApplying = applying;
    const dialog = byId("assistantDialog");
    dialog.classList.toggle("pm-ai-applying", applying);
    dialog.toggleAttribute("aria-busy", applying);
    dialog.querySelectorAll("button, input, textarea, select").forEach((control) => {
        control.disabled = applying;
    });
    byId("assistantApplyStatus").textContent = applying
        ? "Applying selected changes. This write cannot be canceled after submission."
        : "";
    if (!applying) {
        byId("applyAssistantButton").disabled = selectedAssistantActions().length === 0;
    }
}

function renderAssistantSessions() {
    const select = byId("assistantSessionSelect");
    select.innerHTML = [
        '<option value="">New chat</option>',
        ...state.assistantSessions.map((chat) => (
            `<option value="${escapeHtml(chat.id)}">${escapeHtml(chat.title || "Untitled chat")}</option>`
        )),
    ].join("");
    select.value = state.assistantSessionId || "";
    byId("deleteAssistantSessionButton").hidden = !state.assistantSessionId;
}

function setAssistantMessagePage(result, prefix = false) {
    const incoming = (result.messages || []).map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
    }));
    if (prefix) {
        const existingIds = new Set(state.assistantHistory.map((message) => message.id));
        state.assistantHistory = [
            ...incoming.filter((message) => !existingIds.has(message.id)),
            ...state.assistantHistory,
        ];
    } else {
        state.assistantHistory = incoming;
    }
    state.assistantMessagesHaveMore = Boolean(
        result.has_more ?? result.messages_has_more,
    );
    state.assistantMessagesBeforeId = (
        result.next_before_id ?? result.messages_before_id ?? null
    );
}

async function loadAssistantSession(sessionId, { drawerGeneration } = {}) {
    const loadGeneration = ++state.assistantSessionLoadGeneration;
    const drawerRequestIsCurrent = () => (
        drawerGeneration === undefined
        || assistantDrawerRequestIsCurrent(drawerGeneration)
    );
    if (!sessionId) {
        if (!drawerRequestIsCurrent()) return false;
        state.assistantSessionId = null;
        state.assistantReadiness = state.aiSettings;
        state.assistantHistory = [];
        state.assistantMessagesHaveMore = false;
        state.assistantMessagesBeforeId = null;
        renderAssistantSessions();
        renderAssistantConversation();
        renderAssistantDisclosure();
        return true;
    }
    const projectId = state.selectedProjectId;
    const result = await api(`/api/projects/${projectId}/assistant/sessions/${encodeURIComponent(sessionId)}`);
    if (
        projectId !== state.selectedProjectId
        || loadGeneration !== state.assistantSessionLoadGeneration
        || !drawerRequestIsCurrent()
    ) return false;
    state.assistantSessionId = result.session.id;
    state.assistantReadiness = result.readiness || null;
    setAssistantMessagePage(result);
    renderAssistantSessions();
    renderAssistantConversation();
    renderAssistantDisclosure();
    return true;
}

async function loadAssistantSessions({ drawerGeneration } = {}) {
    const loadGeneration = ++state.assistantSessionsLoadGeneration;
    const projectId = state.selectedProjectId;
    const result = await api(`/api/projects/${projectId}/assistant/sessions`);
    if (
        projectId !== state.selectedProjectId
        || loadGeneration !== state.assistantSessionsLoadGeneration
        || (
            drawerGeneration !== undefined
            && !assistantDrawerRequestIsCurrent(drawerGeneration)
        )
    ) return false;
    state.assistantSessions = result.sessions || [];
    const selectedStillExists = state.assistantSessions.some(
        (chat) => chat.id === state.assistantSessionId,
    );
    const nextSessionId = selectedStillExists
        ? state.assistantSessionId
        : state.assistantSessions[0]?.id || null;
    renderAssistantSessions();
    return loadAssistantSession(nextSessionId, { drawerGeneration });
}

function startNewAssistantSession() {
    invalidateAssistantPreview();
    state.assistantPendingRequest = null;
    state.assistantSessionLoadGeneration += 1;
    state.assistantSessionId = null;
    state.assistantReadiness = state.aiSettings;
    state.assistantHistory = [];
    state.assistantMessagesHaveMore = false;
    state.assistantMessagesBeforeId = null;
    byId("assistantForm").querySelector("[data-form-error]").textContent = "";
    renderAssistantSessions();
    renderAssistantConversation();
    renderAssistantDisclosure();
    const drawer = byId("assistantDialog");
    if (assistantDrawerIsOpen(drawer) && drawer.contains(document.activeElement)) {
        byId("assistantForm").elements.message.focus({ preventScroll: true });
    }
}

function renderAssistantConversation({ scrollToEnd = true } = {}) {
    const conversation = byId("assistantConversation");
    conversation.innerHTML = state.assistantHistory.map((message) => `
        <div class="pm-ai-message ${escapeHtml(message.role)}">${escapeHtml(message.content)}</div>`).join("");
    if (scrollToEnd) {
        const drawerBody = byId("assistantDrawerBody");
        drawerBody.scrollTop = drawerBody.scrollHeight;
    }
    const loadOlder = byId("loadOlderAssistantMessagesButton");
    loadOlder.hidden = !state.assistantSessionId || !state.assistantMessagesHaveMore;
}

async function reloadAssistantReadiness({ drawerGeneration } = {}) {
    const projectId = state.selectedProjectId;
    const sessionId = state.assistantSessionId;
    if (!sessionId) {
        await loadAISettings({ drawerGeneration });
        return drawerGeneration === undefined || assistantDrawerRequestIsCurrent(drawerGeneration)
            ? effectiveAssistantReadiness()
            : null;
    }
    const result = await api(assistantSessionReadinessUrl(projectId, sessionId));
    if (
        projectId !== state.selectedProjectId
        || sessionId !== state.assistantSessionId
        || (
            drawerGeneration !== undefined
            && !assistantDrawerRequestIsCurrent(drawerGeneration)
        )
    ) {
        return null;
    }
    state.assistantReadiness = result.readiness || null;
    renderAssistantDisclosure();
    return state.assistantReadiness;
}

function markAssistantReadinessUnavailable(message) {
    const unavailable = {
        ...(effectiveAssistantReadiness() || {}),
        ready: false,
        readiness_status: "unavailable",
        message,
    };
    if (state.assistantSessionId) {
        state.assistantReadiness = unavailable;
    } else {
        state.aiSettings = unavailable;
        state.assistantReadiness = unavailable;
    }
    renderAssistantDisclosure();
}

function wireAssistant() {
    const form = byId("assistantForm");
    byId("assistantSessionSelect").addEventListener("change", async (event) => {
        const drawerGeneration = state.assistantDrawerGeneration;
        invalidateAssistantPreview();
        state.assistantPendingRequest = null;
        form.querySelector("[data-form-error]").textContent = "";
        const selectionControls = [
            ...form.elements,
            ...byId("assistantDialog").querySelectorAll(
                ".pm-ai-session-toolbar button, .pm-ai-session-toolbar select, #loadOlderAssistantMessagesButton",
            ),
        ];
        selectionControls.forEach((control) => { control.disabled = true; });
        form.setAttribute("aria-busy", "true");
        try {
            await loadAssistantSession(event.target.value || null, { drawerGeneration });
        } catch (error) {
            if (!assistantDrawerRequestIsCurrent(drawerGeneration)) return;
            showToast(error.message, true);
            renderAssistantSessions();
        } finally {
            if (assistantDrawerRequestIsCurrent(drawerGeneration)) {
                selectionControls.forEach((control) => { control.disabled = false; });
                form.removeAttribute("aria-busy");
            }
        }
    });
    byId("newAssistantSessionButton").addEventListener("click", startNewAssistantSession);
    byId("loadOlderAssistantMessagesButton").addEventListener("click", async () => {
        const button = byId("loadOlderAssistantMessagesButton");
        const projectId = state.selectedProjectId;
        const sessionId = state.assistantSessionId;
        const beforeId = state.assistantMessagesBeforeId;
        const drawerGeneration = state.assistantDrawerGeneration;
        if (!sessionId || !beforeId || button.disabled) return;
        button.disabled = true;
        const drawerBody = byId("assistantDrawerBody");
        const previousHeight = drawerBody.scrollHeight;
        const previousTop = drawerBody.scrollTop;
        try {
            const result = await api(
                `/api/projects/${projectId}/assistant/sessions/${encodeURIComponent(sessionId)}?limit=100&before_id=${encodeURIComponent(beforeId)}`,
            );
            if (
                projectId !== state.selectedProjectId
                || sessionId !== state.assistantSessionId
                || !assistantDrawerRequestIsCurrent(drawerGeneration)
            ) return;
            state.assistantReadiness = result.readiness || null;
            setAssistantMessagePage(result, true);
            renderAssistantConversation({ scrollToEnd: false });
            drawerBody.scrollTop = previousTop + drawerBody.scrollHeight - previousHeight;
        } catch (error) {
            if (assistantDrawerRequestIsCurrent(drawerGeneration)) {
                showToast(error.message, true);
            }
        } finally {
            if (assistantDrawerRequestIsCurrent(drawerGeneration)) {
                button.disabled = false;
            }
        }
    });
    byId("deleteAssistantSessionButton").addEventListener("click", async () => {
        const sessionId = state.assistantSessionId;
        if (!sessionId || !window.confirm("Delete this private Ask Kasugai conversation?")) return;
        const projectId = state.selectedProjectId;
        const drawerGeneration = state.assistantDrawerGeneration;
        invalidateAssistantPreview();
        state.assistantPendingRequest = null;
        const deletionControls = [
            ...form.elements,
            ...byId("assistantDialog").querySelectorAll(
                ".pm-ai-session-toolbar button, .pm-ai-session-toolbar select, #loadOlderAssistantMessagesButton",
            ),
        ];
        deletionControls.forEach((control) => { control.disabled = true; });
        form.setAttribute("aria-busy", "true");
        try {
            await api(
                `/api/projects/${projectId}/assistant/sessions/${encodeURIComponent(sessionId)}`,
                { method: "DELETE" },
            );
            if (projectId !== state.selectedProjectId) return;
            if (!assistantDrawerRequestIsCurrent(drawerGeneration)) {
                if (assistantDrawerIsOpen() && state.assistantProjectId === projectId) {
                    await loadAssistantSessions({
                        drawerGeneration: state.assistantDrawerGeneration,
                    });
                }
                return;
            }
            state.assistantSessionId = null;
            state.assistantHistory = [];
            state.assistantMessagesHaveMore = false;
            state.assistantMessagesBeforeId = null;
            await loadAssistantSessions({ drawerGeneration });
            showToast("Ask Kasugai conversation deleted");
        } catch (error) {
            if (assistantDrawerRequestIsCurrent(drawerGeneration)) {
                showToast(error.message, true);
            }
        } finally {
            if (assistantDrawerRequestIsCurrent(drawerGeneration)) {
                deletionControls.forEach((control) => { control.disabled = false; });
                form.removeAttribute("aria-busy");
            }
        }
    });
    form.addEventListener("input", () => {
        state.assistantPendingRequest = null;
        invalidateAssistantPreview();
    });
    form.addEventListener("change", () => {
        state.assistantPendingRequest = null;
        invalidateAssistantPreview();
    });
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submit = form.querySelector('button[type="submit"]');
        const error = form.querySelector("[data-form-error]");
        const message = form.elements.message.value.trim();
        if (submit.disabled) return;
        invalidateAssistantPreview();
        const requestGeneration = state.assistantRequestGeneration;
        const drawerGeneration = state.assistantDrawerGeneration;
        const requestProjectId = state.selectedProjectId;
        const readinessProjectId = state.selectedProjectId;
        const readinessSessionId = state.assistantSessionId;
        const controls = [
            ...form.elements,
            ...byId("assistantDialog").querySelectorAll(
                ".pm-ai-session-toolbar button, .pm-ai-session-toolbar select, #loadOlderAssistantMessagesButton",
            ),
        ];
        const setRequestBusy = (busy) => {
            controls.forEach((control) => { control.disabled = busy; });
            form.classList.toggle("pm-ai-form-busy", busy);
            form.toggleAttribute("aria-busy", busy);
        };
        setRequestBusy(true);
        error.textContent = "Checking AI model readiness...";
        try {
            await reloadAssistantReadiness({ drawerGeneration });
        } catch (settingsError) {
            if (
                requestGeneration !== state.assistantRequestGeneration
                || !assistantDrawerRequestIsCurrent(drawerGeneration)
            ) return;
            const readinessError = `Could not check AI model readiness: ${settingsError.message}`;
            markAssistantReadinessUnavailable(readinessError);
            error.textContent = readinessError;
            setRequestBusy(false);
            return;
        }
        if (
            requestGeneration !== state.assistantRequestGeneration
            || !assistantDrawerRequestIsCurrent(drawerGeneration)
        ) return;
        if (
            readinessProjectId !== state.selectedProjectId
            || readinessSessionId !== state.assistantSessionId
        ) {
            error.textContent = "The selected conversation changed. Try again.";
            setRequestBusy(false);
            return;
        }
        const readiness = effectiveAssistantReadiness();
        if (!aiIsReady(readiness)) {
            renderAssistantDisclosure();
            error.textContent = aiReadinessMessage(readiness);
            setRequestBusy(false);
            return;
        }
        const requestKey = JSON.stringify({
            project_id: requestProjectId,
            session_id: state.assistantSessionId,
            message,
            include_github: form.elements.include_github.checked,
            include_email: form.elements.include_email.checked,
        });
        if (state.assistantPendingRequest?.key !== requestKey) {
            state.assistantPendingRequest = {
                key: requestKey,
                requestId: requestUUID(),
                newSessionId: state.assistantSessionId
                    ? null
                    : requestUUID(),
            };
        }
        const pendingRequest = state.assistantPendingRequest;
        const controller = new AbortController();
        state.assistantAbortController = controller;
        error.textContent = "";
        try {
            const result = await api(`/api/projects/${requestProjectId}/assistant/preview`, {
                method: "POST",
                body: {
                    message,
                    include_github: form.elements.include_github.checked,
                    include_email: form.elements.include_email.checked,
                    session_id: state.assistantSessionId,
                    new_session_id: pendingRequest.newSessionId,
                    request_id: pendingRequest.requestId,
                },
                signal: controller.signal,
            });
            if (
                requestGeneration !== state.assistantRequestGeneration
                || !assistantDrawerRequestIsCurrent(drawerGeneration)
                || requestProjectId !== state.selectedProjectId
            ) {
                return;
            }
            state.assistantPreview = {
                proposal: result.proposal,
                signature: result.signature,
            };
            const assistantReply = String(
                result.proposal.answer
                || result.proposal.summary
                || "No narrative response was returned.",
            ).slice(0, 5000);
            if (result.session) {
                state.assistantSessionId = result.session.id;
                state.assistantReadiness = {
                    ...(state.assistantReadiness || state.aiSettings || {}),
                    provider: result.session.backend || state.aiSettings?.provider,
                    model: result.session.model || state.aiSettings?.model,
                    current_provider: state.aiSettings?.provider,
                };
                state.assistantSessions = [
                    result.session,
                    ...state.assistantSessions.filter((chat) => chat.id !== result.session.id),
                ];
            }
            if (Array.isArray(result.messages)) {
                setAssistantMessagePage(result);
            } else {
                state.assistantHistory = [
                    ...state.assistantHistory,
                    { role: "user", content: message },
                    { role: "assistant", content: assistantReply },
                ].slice(-100);
                state.assistantMessagesHaveMore = false;
                state.assistantMessagesBeforeId = null;
            }
            renderAssistantSessions();
            renderAssistantConversation();
            renderAssistantDisclosure();
            renderAssistantPreview(result.proposal);
            state.assistantPendingRequest = null;
            form.elements.message.value = "";
        } catch (requestError) {
            if (
                requestError.name !== "AbortError"
                && requestGeneration === state.assistantRequestGeneration
                && assistantDrawerRequestIsCurrent(drawerGeneration)
            ) {
                if (requestError.status === 409) {
                    try {
                        await loadAssistantSessions({ drawerGeneration });
                    } catch (reloadError) {
                        if (assistantDrawerRequestIsCurrent(drawerGeneration)) {
                            showToast(reloadError.message, true);
                        }
                    }
                    if (!assistantDrawerRequestIsCurrent(drawerGeneration)) return;
                    state.assistantPendingRequest = null;
                }
                error.textContent = requestError.message;
            }
        } finally {
            if (
                requestGeneration === state.assistantRequestGeneration
                && assistantDrawerRequestIsCurrent(drawerGeneration)
            ) {
                state.assistantAbortController = null;
                setRequestBusy(false);
            }
        }
    });
    byId("assistantActions").addEventListener("change", (event) => {
        if (event.target.matches("[data-ai-action-index]")) {
            byId("applyAssistantButton").disabled = selectedAssistantActions().length === 0;
        }
    });
    byId("applyAssistantButton").addEventListener("click", async () => {
        if (!state.assistantPreview) return;
        const selectedActions = selectedAssistantActions();
        if (!selectedActions.length) return;
        setAssistantApplying(true);
        try {
            const result = await api(`/api/projects/${state.selectedProjectId}/assistant/apply`, {
                method: "POST",
                body: { ...state.assistantPreview, selected_actions: selectedActions },
            });
            setAssistantApplying(false);
            closeAssistantDrawer();
            try {
                await refreshCurrent();
                showToast(`${result.applied} Ask Kasugai change${result.applied === 1 ? "" : "s"} applied`);
            } catch (refreshError) {
                showToast(`Changes were applied, but the workspace could not refresh: ${refreshError.message}`, true);
            }
        } catch (error) {
            showToast(error.message, true);
        } finally {
            setAssistantApplying(false);
        }
    });
    document.addEventListener("keydown", (event) => {
        if (
            event.key !== "Escape"
            || event.defaultPrevented
            || event.isComposing
            || !assistantDrawerIsOpen()
            || document.querySelector("dialog[open]")
        ) return;
        event.preventDefault();
        closeAssistantDrawer();
    });
}

async function initialize() {
    wireForms();
    wireDeletes();
    wireAISettings();
    wireActions();
    wireAssistant();
    refreshIcons();
    byId("projectList").innerHTML = '<div class="pm-empty-copy">Loading portfolio...</div>';
    try {
        const requestedProject = new URLSearchParams(window.location.search).get("project");
        await Promise.all([
            loadPortfolio(requestedProject || undefined),
            loadAISettings().catch(() => null),
        ]);
    } catch (error) {
        showToast(error.message, true);
        byId("projectList").innerHTML = '<div class="pm-empty-copy">Portfolio unavailable</div>';
    }
}

if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", initialize);
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        aiCredentialErrorMessage,
        aiIsReady,
        aiReadinessMessage,
        aiUsesHostedProvider,
        assistantDisclosureText,
        assistantDrawerIsOpen,
        assistantDrawerRequestMatches,
        assistantSessionReadinessUrl,
        selectAssistantReadiness,
        setAssistantDrawerState,
    };
}
