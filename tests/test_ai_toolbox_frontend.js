"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
    MAX_ASSISTANT_BYTES,
    MAX_USER_BYTES,
    MODES,
    byteLength,
    normalizeDetail,
    normalizeIndex,
    normalizeMessage,
    normalizeModes,
    normalizeStatus,
    normalizeSummary,
    safeContent,
    sessionId,
} = require("../sites/static/js/ai_toolbox.js");

const SESSION_ID = "a".repeat(32);

function summary(overrides = {}) {
    return {
        id: SESSION_ID,
        title: "Review the request handler",
        mode: "review",
        version: 3,
        message_count: 2,
        created_at: "2026-07-17T10:00:00Z",
        updated_at: "2026-07-17T10:05:00Z",
        ...overrides,
    };
}

function detail(overrides = {}) {
    return {
        id: SESSION_ID,
        title: "Review the request handler",
        mode: "review",
        version: 3,
        messages: [
            { role: "user", content: "Review this function." },
            { role: "assistant", content: "Validate the input before using it." },
        ],
        created_at: "2026-07-17T10:00:00Z",
        updated_at: "2026-07-17T10:05:00Z",
        ...overrides,
    };
}

test("Local AI status and modes accept only deployment-controlled variants", () => {
    assert.deepEqual(normalizeStatus({
        configured: true, provider: "ollama", model: "gpt-oss:20b",
        endpoint: "http://private", token: "must-not-survive",
    }), { configured: true, provider: "ollama", model: "gpt-oss:20b" });
    assert.deepEqual(normalizeStatus({ configured: false, provider: "ollama", model: "" }), {
        configured: false, provider: "ollama", model: "",
    });
    assert.equal(normalizeStatus({ configured: true, provider: "openai", model: "remote" }), null);
    assert.equal(normalizeStatus({ configured: true, provider: "ollama", model: "" }), null);
    assert.deepEqual(normalizeModes([...MODES]), [...MODES]);
    assert.equal(normalizeModes(["assistant", "shell"]), null);
    assert.equal(normalizeModes(["assistant", "assistant"]), null);
});

test("AI session summaries enforce fixed IDs, modes, counts, and versions", () => {
    const normalized = normalizeSummary(summary({
        system_prompt: "ignored", source_path: "C:\\private", endpoint: "private",
    }));
    assert.equal(normalized.id, SESSION_ID);
    assert.equal(normalized.mode, "review");
    assert.equal(normalized.message_count, 2);
    assert.doesNotMatch(JSON.stringify(normalized), /system_prompt|source_path|endpoint|private/);
    assert.equal(sessionId("f".repeat(32)), "f".repeat(32));
    assert.equal(sessionId("../../escape"), "");
    assert.equal(normalizeSummary(summary({ mode: "execute" })), null);
    assert.equal(normalizeSummary(summary({ version: 0 })), null);
    assert.equal(normalizeSummary(summary({ message_count: 25 })), null);
    assert.equal(normalizeSummary(summary({ title: "x".repeat(101) })), null);
});

test("conversation messages remain inert plain text within UTF-8 bounds", () => {
    const activeLookingText = "<script>alert('never')</script>\n[docs](https://example.com)\nSELECT * FROM users;";
    const normalized = normalizeDetail(detail({
        messages: [{ role: "assistant", content: activeLookingText, html: "ignored" }],
        tool_calls: [{ command: "ignored" }],
    }));
    assert.equal(normalized.messages[0].content, activeLookingText);
    assert.equal(Object.hasOwn(normalized.messages[0], "html"), false);
    assert.equal(Object.hasOwn(normalized, "tool_calls"), false);
    assert.equal(byteLength("\u{1F9E0}"), 4);
    assert.equal(safeContent("a".repeat(MAX_USER_BYTES), MAX_USER_BYTES).length, MAX_USER_BYTES);
    assert.equal(safeContent("a".repeat(MAX_USER_BYTES + 1), MAX_USER_BYTES), null);
    assert.equal(normalizeMessage({ role: "assistant", content: "a".repeat(MAX_ASSISTANT_BYTES + 1) }), null);
    assert.equal(normalizeMessage({ role: "tool", content: "not allowed" }), null);
    assert.equal(normalizeDetail(detail({ messages: Array.from({ length: 25 }, () => ({ role: "user", content: "x" })) })), null);
});

test("AI Toolbox index reduces the exact contract and bounds session arrays", () => {
    const sessions = Array.from({ length: 35 }, (_, index) => summary({
        id: index.toString(16).padStart(32, "0"),
        title: `Session ${index}`,
    }));
    const normalized = normalizeIndex({
        status: { configured: true, provider: "ollama", model: "qwen3-coder" },
        modes: [...MODES],
        sessions,
        base_url: "http://private", system_prompt: "ignored", temperature: 1,
    });
    assert.equal(normalized.sessions.length, 30);
    assert.deepEqual(normalized.status, { configured: true, provider: "ollama", model: "qwen3-coder" });
    assert.deepEqual(normalized.modes, [...MODES]);
    assert.doesNotMatch(JSON.stringify(normalized), /base_url|system_prompt|temperature|private/);
    assert.throws(() => normalizeIndex({ status: {}, modes: [], sessions: [] }), /invalid Local AI response/i);
    assert.throws(() => normalizeIndex({ status: { configured: false, provider: "ollama", model: "" }, modes: MODES }), /invalid Local AI response/i);
});

test("AI browser client uses exact JSON mutations and inert DOM sinks", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "sites", "static", "js", "ai_toolbox.js"), "utf8");
    assert.doesNotMatch(source, /\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML/);
    assert.doesNotMatch(source, /eval\s*\(|new Function|child_process|WebSocket|EventSource|ReadableStream|Worker\s*\(/i);
    assert.doesNotMatch(source, /marked\s*\(|markdown-it|highlight\.js|linkify/i);
    assert.match(source, /content\.textContent = message\.content/);
    assert.match(source, /navigator\.clipboard\.writeText\(content\)/);
    assert.match(source, /meta\[name="kasugai-csrf-token"\]/);
    assert.match(source, /cache:\s*'no-store'/);
    assert.match(source, /redirect:\s*'error'/);
    assert.match(source, /api\('\/api\/ai-toolbox'\)/);
    assert.match(source, /method:\s*'POST', body:\s*\{ title, mode \}/);
    assert.match(source, /method:\s*'POST', body:\s*\{ version: detail\.version, message \}/);
    assert.match(source, /method:\s*'DELETE', body:\s*\{ version: detail\.version \}/);
    assert.doesNotMatch(source, /body:\s*\{[^}]*model|body:\s*\{[^}]*endpoint|body:\s*\{[^}]*temperature|body:\s*\{[^}]*system/i);
});

test("AI client exposes busy and optimistic-conflict recovery without losing drafts", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "sites", "static", "js", "ai_toolbox.js"), "utf8");
    assert.match(source, /error\.conflict = response\.status === 409/);
    assert.match(source, /error\.busy = response\.status === 429/);
    assert.match(source, /await recoverConflict\(detail\.id\)/);
    assert.match(source, /Your draft was kept/);
    assert.match(source, /state\.status\?\.configured/);
    assert.match(source, /MAX_USER_BYTES = 16 \* 1024/);
    assert.match(source, /ctrlKey \|\| event\.metaKey/);
});

test("Local AI Toolbox is included as numbered module 09 with accessible controls", () => {
    const template = fs.readFileSync(path.join(__dirname, "..", "sites", "templates", "index.html"), "utf8");
    assert.match(template, /id="aiToolboxModule"/);
    assert.match(template, /cockpit-module-number">09</);
    assert.match(template, /id="aiReadinessState"/);
    assert.match(template, /id="aiSessionList"[^>]*role="listbox"/);
    assert.match(template, /id="aiMessageList"[^>]*role="log"/);
    assert.match(template, /id="aiMessageInput"[^>]*maxlength="16384"/);
    assert.match(template, /id="aiSessionDialog"[^>]*aria-labelledby="aiSessionDialogTitle"/);
    assert.match(template, /Responses are displayed as inert plain text/);
    assert.match(template, /cannot browse, inspect files, execute code, call tools, or follow links/);
    assert.match(template, /css\/ai_toolbox\.css/);
    assert.match(template, /js\/ai_toolbox\.js/);
});
