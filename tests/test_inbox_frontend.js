"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
    normalizeConnectorError,
    normalizeInbox,
    normalizeItem,
    normalizeItemState,
    normalizeSource,
    safeOpenTarget,
} = require("../sites/static/js/inbox.js");

const ITEM_ID = "a".repeat(32);

function item(overrides = {}) {
    return {
        id: ITEM_ID,
        source: "automation",
        kind: "rule_failure",
        severity: "error",
        title: "Nightly rule failed",
        body: "The notification action could not complete.",
        url: "#automationModule",
        occurred_at: "2026-07-16T12:00:00Z",
        state: "unread",
        pinned: true,
        snoozed_until: null,
        live: true,
        ...overrides,
    };
}

test("inbox open targets allow only bounded fragments and canonical GitHub pages", () => {
    assert.deepEqual(safeOpenTarget("#automationModule"), { kind: "internal", value: "#automationModule" });
    assert.deepEqual(safeOpenTarget("https://github.com/openai/codex/pull/123"), {
        kind: "github", value: "https://github.com/openai/codex/pull/123",
    });
    for (const value of [
        "http://github.com/openai/codex",
        "https://user:secret@github.com/openai/codex",
        "https://github.com.evil.example/openai/codex",
        "https://gist.github.com/user/id",
        "https://github.com/openai/codex?token=secret",
        "https://github.com/openai/codex#fragment",
        "javascript:alert(1)",
        "../../private",
    ]) assert.equal(safeOpenTarget(value), null, value);
});

test("inbox item normalization keeps only bounded presentation state", () => {
    const normalized = normalizeItem(item({
        private_resource_id: "server-secret",
        html: "<img src=x onerror=alert(1)>",
        command: "not permitted",
    }));
    assert.equal(normalized.title, "Nightly rule failed");
    assert.equal(normalized.open_target.kind, "internal");
    assert.equal(normalized.pinned, true);
    assert.doesNotMatch(JSON.stringify(normalized), /server-secret|onerror|command/);
    assert.equal(normalizeItem(item({ id: "../../escape" })), null);
    assert.equal(normalizeItem(item({ kind: "custom_kind" })), null);
    assert.equal(normalizeItem(item({ severity: "critical" })), null);
    assert.equal(normalizeItem(item({ state: "active" })), null);
    assert.equal(normalizeItem(item({ occurred_at: "not-a-date" })), null);
});

test("inbox payload validates counts, sources, and connector disclosures", () => {
    const payload = normalizeInbox({
        items: [item()],
        counts: { unread: 1, total: 4, pinned: 1, ignored: 999 },
        sources: [
            { id: "automation", label: "Automation", count: 2, token: "hidden" },
            { id: "custom", label: "Custom", count: 1 },
        ],
        refreshed_at: "2026-07-16T12:01:00Z",
        connector_errors: [
            { source: "github", message: "GitHub is temporarily unavailable.", details: "private" },
            { source: "unknown", message: "Ignored" },
        ],
    });
    assert.equal(payload.items.length, 1);
    assert.deepEqual(payload.counts, { unread: 1, total: 4, pinned: 1 });
    assert.equal(payload.sources.length, 1);
    assert.deepEqual(payload.connector_errors, [{ source: "github", message: "GitHub is temporarily unavailable." }]);
    assert.doesNotMatch(JSON.stringify(payload), /hidden|private/);
    assert.throws(() => normalizeInbox({ items: [], counts: {}, sources: [], connector_errors: [] }), /invalid inbox counts/i);
    assert.throws(() => normalizeInbox({ items: [], counts: { unread: 0, total: 0, pinned: 0 }, sources: [], connector_errors: [], refreshed_at: "bad" }), /refresh time/i);
});

test("inbox mutation state is an exact public overlay", () => {
    assert.deepEqual(normalizeItemState({
        id: ITEM_ID, state: "snoozed", pinned: false,
        snoozed_until: "2026-07-16T13:00:00Z", private: "ignored",
    }), {
        id: ITEM_ID, state: "snoozed", pinned: false,
        snoozed_until: "2026-07-16T13:00:00.000Z",
    });
    assert.throws(() => normalizeItemState({ id: ITEM_ID, state: "snoozed", pinned: false, snoozed_until: null }), /invalid inbox item state/i);
    assert.equal(normalizeSource({ id: "github", label: "GitHub", count: 3 }).id, "github");
    assert.equal(normalizeSource({ id: "other", label: "Other", count: 3 }), null);
    assert.equal(normalizeConnectorError({ source: "system", message: "Unavailable" }).source, "system");
});

test("inbox browser code uses safe rendering and guarded internal mutations", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "sites", "static", "js", "inbox.js"), "utf8");
    assert.doesNotMatch(source, /\.innerHTML\s*=/);
    assert.doesNotMatch(source, /eval\s*\(|new Function|child_process|shell/i);
    assert.match(source, /textContent/);
    assert.match(source, /replaceChildren/);
    assert.match(source, /meta\[name="kasugai-csrf-token"\]/);
    assert.match(source, /cache:\s*'no-store'/);
    assert.match(source, /redirect:\s*'error'/);
    assert.match(source, /\/api\/inbox\/mark-all-read/);
    assert.match(source, /noopener,noreferrer/);
    assert.doesNotMatch(source, /textContent\s*=\s*item\.id|textContent\s*=\s*item\.url/);
});
