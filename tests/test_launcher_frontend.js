"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
    command,
    normalizeCatalog,
    normalizePairing,
    normalizeRuns,
    normalizeSubmission,
    safeExternalUrl,
    searchCommands,
} = require("../sites/static/js/launcher.js");

test("launcher search prioritizes exact and prefix title matches", () => {
    const commands = [
        command({ id: "one", title: "Docker dashboard", subtitle: "Infrastructure" }),
        command({ id: "two", title: "Dashboard", subtitle: "Home" }),
        command({ id: "three", title: "Open docs", keywords: "docker manual" }),
    ];
    assert.deepEqual(searchCommands(commands, "dashboard").map(item => item.id), ["two", "one"]);
    assert.equal(searchCommands(commands, "docker")[0].id, "one");
});

test("external launcher URLs require credential-free HTTPS", () => {
    assert.equal(safeExternalUrl("https://github.com/openai/codex"), "https://github.com/openai/codex");
    assert.equal(safeExternalUrl("http://example.com"), "");
    assert.equal(safeExternalUrl("https://user:secret@example.com"), "");
    assert.equal(safeExternalUrl("javascript:alert(1)"), "");
});

test("launcher catalog keeps presentation metadata and opaque IDs only", () => {
    const catalog = normalizeCatalog({
        agents: [{
            id: "runner_0123456789", display_name: "Build runner", platform: "Windows",
            agent_version: "1.0", paired_at: "2026-07-16T12:00:00Z",
            last_seen_at: "2026-07-16T12:01:00Z", online: true, task_count: 1,
            token: "must-not-survive", path: "C:\\private",
        }],
        tasks: [{
            id: "a".repeat(32), title: "Run checks", description: "Execute the approved checks",
            category: "Quality", icon: "test-tube-2", requires_confirmation: true,
            agent_id: "runner_0123456789", agent_name: "Build runner", available: true,
            argv: ["danger"], path: "C:\\private", environment: { SECRET: "no" },
        }],
    });
    assert.equal(catalog.agents[0].display_name, "Build runner");
    assert.equal(catalog.tasks[0].icon, "test-tube-2");
    assert.equal(catalog.tasks[0].requires_confirmation, true);
    assert.doesNotMatch(JSON.stringify(catalog), /must-not-survive|danger|private|SECRET/);
});

test("launcher catalog rejects broad shapes and skips unsafe identifiers", () => {
    assert.throws(() => normalizeCatalog({ actions: [] }), /invalid launcher catalog/i);
    const catalog = normalizeCatalog({
        agents: [{ id: "../../runner", display_name: "Bad", online: true }],
        tasks: [{
            id: "task/escape", title: "Bad", agent_id: "runner/escape",
            icon: "<svg onload=alert(1)>", available: true,
        }],
    });
    assert.deepEqual(catalog.agents, []);
    assert.deepEqual(catalog.tasks, []);
});

test("launcher run history is bounded to status summary fields", () => {
    const runs = normalizeRuns({ runs: [{
        id: "run_012345678901", task_id: "a".repeat(32), task_title: "Run checks",
        agent_id: "runner_0123456789", agent_name: "Build runner", state: "succeeded",
        requested_at: "2026-07-16T12:00:00Z", claimed_at: "2026-07-16T12:00:01Z",
        completed_at: "2026-07-16T12:00:02Z", result_status: "ok", result_code: "0",
        summary: "Checks passed", result: { output: "private output", argv: ["no"] },
    }] });
    assert.equal(runs[0].state, "succeeded");
    assert.equal(runs[0].summary, "Checks passed");
    assert.doesNotMatch(JSON.stringify(runs), /private output|argv/);
});

test("launcher pairing and confirmation previews require safe one-use values", () => {
    const pairing = normalizePairing({
        pairing_id: "pairing_012345678", code: "pairingCode_0123456789AB",
        expires_at: "2026-07-16T12:10:00Z", command: "ignored server command",
    });
    assert.equal(pairing.pairing_id, "pairing_012345678");
    assert.equal(Object.hasOwn(pairing, "command"), false);

    const preview = normalizeSubmission({
        queued: false,
        preview: {
            confirmation_token: "abcdefghijklmnopqrstuvwxyz_012345",
            expires_at: "2026-07-16T12:01:00Z",
            title: "Deploy preview",
            description: "Deploy the approved build",
            argv: ["not exposed"],
        },
    });
    assert.equal(preview.queued, false);
    assert.equal(preview.preview.title, "Deploy preview");
    assert.doesNotMatch(JSON.stringify(preview), /argv|not exposed/);
    assert.throws(() => normalizeSubmission({ queued: false, preview: { confirmation_token: "bad" } }), /invalid confirmation/i);
});

test("launcher rendering has no HTML or arbitrary execution sink", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "sites", "static", "js", "launcher.js"), "utf8");
    assert.doesNotMatch(source, /\.innerHTML\s*=/);
    assert.doesNotMatch(source, /eval\s*\(|new Function|child_process|shell/i);
    assert.match(source, /textContent/);
    assert.match(source, /ctrlKey/);
    assert.match(source, /meta\[name="kasugai-csrf-token"\]/);
    assert.match(source, /cache:\s*'no-store'/);
    assert.match(source, /redirect:\s*'error'/);
    assert.match(source, /body:\s*\{ confirmation_token:/);
    assert.doesNotMatch(source, /body:\s*\{[^}]*argv|body:\s*\{[^}]*path/);
});
