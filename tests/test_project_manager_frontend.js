"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
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
} = require("../sites/static/js/project_manager.js");

function fakeDrawer() {
    const attributes = new Map([["aria-hidden", "true"], ["inert", ""]]);
    const classes = new Set();
    return {
        hidden: true,
        classList: {
            contains: (name) => classes.has(name),
            toggle(name, force) {
                if (force) classes.add(name);
                else classes.delete(name);
            },
        },
        getAttribute: (name) => attributes.get(name) ?? null,
        setAttribute: (name, value) => attributes.set(name, String(value)),
        hasAttribute: (name) => attributes.has(name),
        toggleAttribute(name, force) {
            if (force) attributes.set(name, "");
            else attributes.delete(name);
        },
    };
}

test("AI readiness requires both configuration and a positive live check", () => {
    assert.equal(aiIsReady({ configured: true, ready: true }), true);
    assert.equal(aiIsReady({ configured: true, ready: false }), false);
    assert.equal(aiIsReady({ configured: true }), false);
    assert.equal(aiIsReady({ configured: false, ready: true }), false);
});

test("backend readiness messages remain authoritative", () => {
    const message = "Start the private Ollama service, then try again.";
    assert.equal(aiReadinessMessage({ configured: true, ready: false, message }), message);
});

test("readiness fallbacks distinguish a missing model and an unverifiable server", () => {
    assert.match(aiReadinessMessage({
        configured: true,
        ready: false,
        readiness_status: "model_missing",
        model: "gpt-oss:20b",
    }), /gpt-oss:20b is not installed/);
    assert.match(aiReadinessMessage({ configured: true }), /could not verify live model readiness/);
    assert.match(aiReadinessMessage(null), /could not verify live model readiness/);
});

test("new chats and saved sessions use separate readiness boundaries", () => {
    const defaultReady = { configured: true, ready: true, model: "default" };
    const defaultUnavailable = { configured: true, ready: false, model: "default" };
    const pinnedReady = { configured: true, ready: true, model: "pinned" };
    const pinnedUnavailable = { configured: true, ready: false, model: "pinned" };

    assert.equal(selectAssistantReadiness(null, pinnedUnavailable, defaultReady), defaultReady);
    assert.equal(selectAssistantReadiness("session-id", pinnedUnavailable, defaultReady), pinnedUnavailable);
    assert.equal(selectAssistantReadiness("session-id", pinnedReady, defaultUnavailable), pinnedReady);
    assert.equal(
        assistantSessionReadinessUrl(42, "chat/id"),
        "/api/projects/42/assistant/sessions/chat%2Fid?limit=1",
    );
});

test("an unavailable saved session keeps history actions available in its disclosure", () => {
    const disclosure = assistantDisclosureText({
        sessionId: "saved-session",
        readiness: {
            configured: false,
            ready: false,
            readiness_status: "backend_mismatch",
            message: "This conversation uses a different backend.",
        },
        backend: "openai",
        model: "saved-model",
    });
    assert.match(disclosure, /No project data is being sent/);
    assert.match(disclosure, /read or delete this saved conversation/);
    assert.match(disclosure, /different backend/);
});

test("hosted corrupt-key guidance never claims the key is unused", () => {
    assert.equal(aiUsesHostedProvider({ provider: "openai" }), true);
    assert.equal(aiUsesHostedProvider({ provider: "ollama" }), false);
    assert.equal(aiUsesHostedProvider({ provider: "disabled" }), false);
    const hosted = aiCredentialErrorMessage({ provider: "openai" });
    assert.match(hosted, /Replace or remove/);
    assert.doesNotMatch(hosted, /not used/);
});

test("the assistant drawer uses non-modal visibility and accessibility state", () => {
    const drawer = fakeDrawer();

    setAssistantDrawerState(drawer, true);
    assert.equal(drawer.hidden, false);
    assert.equal(drawer.getAttribute("aria-hidden"), "false");
    assert.equal(drawer.classList.contains("is-open"), true);
    assert.equal(drawer.hasAttribute("inert"), false);
    assert.equal(assistantDrawerIsOpen(drawer), true);

    setAssistantDrawerState(drawer, false);
    assert.equal(drawer.getAttribute("aria-hidden"), "true");
    assert.equal(drawer.classList.contains("is-open"), false);
    assert.equal(drawer.hasAttribute("inert"), true);
    assert.equal(assistantDrawerIsOpen(drawer), false);
});

test("the assistant drawer never invokes modal dialog APIs and closing retires active work", () => {
    const source = fs.readFileSync(
        path.join(__dirname, "..", "sites", "static", "js", "project_manager.js"),
        "utf8",
    );
    assert.doesNotMatch(source, /byId\("assistantDialog"\)\.showModal\(/);
    assert.doesNotMatch(source, /byId\("assistantDialog"\)\.close\(/);
    const closeHelper = source.match(/function closeAssistantDrawer[\s\S]*?\n}/)?.[0] || "";
    assert.match(closeHelper, /assistantDrawerGeneration \+= 1/);
    assert.match(closeHelper, /invalidateAssistantPreview\(\)/);
    assert.match(closeHelper, /event\.propertyName === "transform"/);
    assert.match(closeHelper, /pm-ai-session-toolbar/);
    assert.ok(
        closeHelper.indexOf("focusTarget.focus")
        < closeHelper.indexOf("setAssistantDrawerState(drawer, false)"),
    );
});

test("a drawer request cannot commit after close and reopen", async () => {
    let resolveRequest;
    let currentGeneration = 7;
    let drawerOpen = true;
    let committed = null;
    const requestGeneration = currentGeneration;
    const request = new Promise((resolve) => { resolveRequest = resolve; });
    const completion = request.then((value) => {
        if (assistantDrawerRequestMatches(
            requestGeneration,
            currentGeneration,
            drawerOpen,
        )) committed = value;
    });

    drawerOpen = false;
    currentGeneration += 1;
    drawerOpen = true;
    currentGeneration += 1;
    resolveRequest("stale result");
    await completion;

    assert.equal(committed, null);
});

test("the assistant trigger toggles the drawer and Escape defers to native dialogs", () => {
    const source = fs.readFileSync(
        path.join(__dirname, "..", "sites", "static", "js", "project_manager.js"),
        "utf8",
    );
    assert.match(
        source,
        /if \(assistantDrawerIsOpen\(\)\) \{\s*closeAssistantDrawer\(\);\s*return;/,
    );
    assert.match(source, /document\.querySelector\("dialog\[open\]"\)/);
});

test("changing projects retires the project-scoped assistant drawer", () => {
    const source = fs.readFileSync(
        path.join(__dirname, "..", "sites", "static", "js", "project_manager.js"),
        "utf8",
    );
    const scopeGuard = source.match(
        /function closeAssistantDrawerForProjectChange[\s\S]*?\n}/,
    )?.[0] || "";
    assert.match(scopeGuard, /state\.assistantProjectId/);
    assert.match(scopeGuard, /closeAssistantDrawer\(\{ restoreFocus: false }\)/);
    assert.match(
        source,
        /async function loadWorkspace[\s\S]*?closeAssistantDrawerForProjectChange\(requestedProjectId\)/,
    );
    assert.match(
        source,
        /async function loadPortfolio[\s\S]*?closeAssistantDrawerForProjectChange\(project\?\.id \|\| null\)/,
    );
    const wireDeletesStart = source.indexOf("function wireDeletes()");
    const handlerStart = source.indexOf('byId("deleteProjectButton")', wireDeletesStart);
    const handlerEnd = source.indexOf('byId("deleteRecordButton")', handlerStart);
    const closeIndex = source.indexOf("closeAssistantDrawerForProjectChange(null)", handlerStart);
    const deleteIndex = source.indexOf('method: "DELETE"', handlerStart);
    assert.ok(
        handlerStart >= 0
        && closeIndex > handlerStart
        && deleteIndex > closeIndex
        && handlerEnd > deleteIndex,
    );
});

test("drawer history and previews use the drawer body scroll container", () => {
    const source = fs.readFileSync(
        path.join(__dirname, "..", "sites", "static", "js", "project_manager.js"),
        "utf8",
    );
    const renderConversation = source.match(
        /function renderAssistantConversation[\s\S]*?\n}/,
    )?.[0] || "";
    assert.match(renderConversation, /byId\("assistantDrawerBody"\)/);
    assert.doesNotMatch(renderConversation, /conversation\.scrollTop/);
    assert.match(source, /renderAssistantConversation\(\{ scrollToEnd: false }\)/);
    assert.match(source, /result\.scrollIntoView/);
});

test("the unloaded assistant drawer does not claim project data is being processed", () => {
    const template = fs.readFileSync(
        path.join(__dirname, "..", "sites", "templates", "project_manager.html"),
        "utf8",
    );
    const disclosure = template.match(/id="assistantDisclosure"[^>]*>([^<]+)</)?.[1] || "";
    assert.match(disclosure, /No project data is sent/);
    assert.doesNotMatch(disclosure, /are processed/);
    assert.match(template, /id="openAISettingsForm"[^>]*hidden/);
    assert.match(template, /id="openAIKeyInput"[^>]*type="password"/);
    assert.match(template, /autocomplete="new-password"/);
});
