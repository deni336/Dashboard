"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
    byteLength,
    normalizeFull,
    normalizeList,
    normalizeSummary,
    normalizeTags,
    parseTags,
    safeContent,
} = require("../sites/static/js/knowledge.js");

const ITEM_ID = "knowledgeItem_0123456789";

function summary(overrides = {}) {
    return {
        id: ITEM_ID,
        kind: "snippet",
        title: "Parse structured logs",
        preview: "const parsed = JSON.parse(line);",
        language: "javascript",
        tags: ["logging", "reference"],
        pinned: true,
        version: 3,
        created_at: "2026-07-16T10:00:00Z",
        updated_at: "2026-07-16T12:00:00Z",
        ...overrides,
    };
}

test("knowledge summaries enforce opaque IDs, kinds, languages, and versions", () => {
    const normalized = normalizeSummary(summary({
        secret: "must-not-survive", command: "ignored", html: "<b>ignored</b>",
    }));
    assert.equal(normalized.kind, "snippet");
    assert.equal(normalized.language, "javascript");
    assert.equal(normalized.version, 3);
    assert.doesNotMatch(JSON.stringify(normalized), /must-not-survive|command|<b>/);
    assert.equal(normalizeSummary(summary({ id: "../../escape" })), null);
    assert.equal(normalizeSummary(summary({ kind: "bookmark" })), null);
    assert.equal(normalizeSummary(summary({ kind: "note", language: "python" })), null);
    assert.equal(normalizeSummary(summary({ version: 0 })), null);
});

test("knowledge content remains inert plain text and obeys the UTF-8 byte bound", () => {
    const source = "<script>alert('never run')</script>\n# Markdown source\n\tindented";
    const normalized = normalizeFull({ ...summary(), content: source, resource_id: "private" });
    assert.equal(normalized.content, source);
    assert.equal(Object.hasOwn(normalized, "resource_id"), false);
    assert.equal(byteLength("🧠"), 4);
    assert.equal(safeContent("a".repeat(64 * 1024)).length, 64 * 1024);
    assert.equal(safeContent("a".repeat(64 * 1024 + 1)), null);
});

test("knowledge tags are printable, case-insensitively unique, and bounded", () => {
    assert.deepEqual(parseTags("docker, Debugging, docker, personal reference"), [
        "docker", "Debugging", "personal reference",
    ]);
    assert.deepEqual(normalizeTags(["Alpha", "beta"]), ["Alpha", "beta"]);
    assert.equal(normalizeTags(["Alpha", "alpha"]), null);
    assert.throws(() => parseTags("valid, bad\ntag"), /printable text/i);
    assert.throws(() => parseTags(Array.from({ length: 13 }, (_, index) => `tag${index}`).join(",")), /no more than 12/i);
    assert.throws(() => parseTags(`valid,${"x".repeat(33)}`), /32 characters/i);
});

test("knowledge list response is strictly reduced to summaries and filter metadata", () => {
    const payload = normalizeList({
        items: [summary()],
        counts: { total: 4, notes: 2, snippets: 2, pinned: 1, hidden: 99 },
        tags: [{ name: "reference", count: 2, internal: "ignored" }],
        languages: ["javascript", "python", "javascript", "brainfuck"],
    });
    assert.equal(payload.items.length, 1);
    assert.deepEqual(payload.counts, { total: 4, notes: 2, snippets: 2, pinned: 1 });
    assert.deepEqual(payload.languages, ["javascript", "python"]);
    assert.deepEqual(payload.tags, [{ name: "reference", count: 2 }]);
    assert.doesNotMatch(JSON.stringify(payload), /hidden|internal|brainfuck/);
    assert.throws(() => normalizeList({ items: [], counts: {}, tags: [], languages: [] }), /invalid knowledge counts/i);
});

test("knowledge browser uses JSON APIs and never interprets stored content", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "sites", "static", "js", "knowledge.js"), "utf8");
    assert.doesNotMatch(source, /\.innerHTML\s*=/);
    assert.doesNotMatch(source, /eval\s*\(|new Function|child_process/i);
    assert.doesNotMatch(source, /marked\s*\(|markdown-it|highlight\.js|insertAdjacentHTML/);
    assert.match(source, /textContent\s*=\s*detail\.content/);
    assert.match(source, /navigator\.clipboard\.writeText/);
    assert.match(source, /meta\[name="kasugai-csrf-token"\]/);
    assert.match(source, /cache:\s*'no-store'/);
    assert.match(source, /redirect:\s*'error'/);
    assert.match(source, /body:\s*\{ pinned: !detail\.pinned, version: detail\.version \}/);
    assert.match(source, /method:\s*'DELETE', body:\s*\{ version: detail\.version \}/);
});
