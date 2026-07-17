"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
    REQUIRED_DOM_IDS,
    createTimerState,
    formatCountdown,
    formatTimer,
    isoToLocalDateTime,
    localDateTimeToIso,
    normalizeDetail,
    normalizeList,
    normalizeSummary,
    pauseTimer,
    resetTimer,
    safeBookmarkUrl,
    safeCheckins,
    startTimer,
    timerRemaining,
} = require("../sites/static/js/personal_hub.js");

const ITEM_ID = "0123456789abcdef0123456789abcdef";

function common(overrides = {}) {
    return {
        id: ITEM_ID,
        kind: "reminder",
        title: "Rotate the signing key",
        version: 3,
        created_at: "2026-07-17T10:00:00Z",
        updated_at: "2026-07-17T12:00:00Z",
        due_at: "2026-07-18T14:30:00Z",
        completed: false,
        ...overrides,
    };
}

test("Personal Hub normalizers strictly reduce all four summary shapes", () => {
    const reminder = normalizeSummary(common({ secret: "drop-me", note: "not-a-summary" }));
    const countdown = normalizeSummary(common({
        kind: "countdown", target_at: "2026-08-01T12:00:00Z",
        due_at: undefined, completed: undefined, command: "ignored",
    }));
    const habit = normalizeSummary(common({
        kind: "habit", cadence: "weekdays", checkins: ["2026-07-16", "2026-07-17"],
        due_at: undefined, completed: undefined,
    }));
    const bookmark = normalizeSummary(common({
        kind: "bookmark", url: "https://docs.example.test/runbook?q=safe#deploy",
        due_at: undefined, completed: undefined,
    }));
    assert.deepEqual(Object.keys(reminder), [
        "id", "kind", "title", "version", "created_at", "updated_at", "due_at", "completed",
    ]);
    assert.equal(countdown.kind, "countdown");
    assert.equal(habit.cadence, "weekdays");
    assert.deepEqual(habit.checkins, ["2026-07-16", "2026-07-17"]);
    assert.equal(bookmark.url, "https://docs.example.test/runbook?q=safe#deploy");
    assert.doesNotMatch(JSON.stringify([reminder, countdown]), /drop-me|not-a-summary|command/);
    assert.equal(normalizeSummary(common({ id: "../../escape" })), null);
    assert.equal(normalizeSummary(common({ kind: "note" })), null);
    assert.equal(normalizeSummary(common({ version: 0 })), null);
    assert.equal(normalizeSummary(common({ created_at: `2026-07-17T10:00:00${"0".repeat(40)}Z` })), null);
});

test("details add only bounded inert notes and lists enforce exact counts", () => {
    const detail = normalizeDetail({ ...common(), note: "Private, inert context", html: "<script>" });
    assert.equal(detail.note, "Private, inert context");
    assert.equal(Object.hasOwn(detail, "html"), false);
    assert.equal(normalizeDetail({ ...common(), note: "bad\ncontrol" }), null);
    const result = normalizeList({
        generated_at: "2026-07-17T12:30:00Z",
        counts: { total: 4, reminders: 1, countdowns: 1, habits: 1, bookmarks: 1, hidden: 9 },
        items: [
            common(),
            common({ id: "1".repeat(32), kind: "countdown", target_at: "2026-08-01T12:00:00Z" }),
            common({ id: "2".repeat(32), kind: "habit", cadence: "daily", checkins: [] }),
            common({ id: "3".repeat(32), kind: "bookmark", url: "https://example.test" }),
        ],
    });
    assert.deepEqual(result.counts, {
        total: 4, reminders: 1, countdowns: 1, habits: 1, bookmarks: 1,
    });
    assert.equal(result.items.length, 4);
    assert.throws(() => normalizeList({
        generated_at: "2026-07-17T12:30:00Z",
        counts: { total: 2, reminders: 1, countdowns: 0, habits: 0, bookmarks: 0 },
        items: [common()],
    }), /counts/i);
});

test("habit dates and bookmark URLs enforce the browser safety boundary", () => {
    assert.deepEqual(safeCheckins(["2026-07-16", "2026-07-17"]), ["2026-07-16", "2026-07-17"]);
    assert.equal(safeCheckins(["2026-07-17", "2026-07-16"]), null);
    assert.equal(safeCheckins(["2026-07-17", "2026-07-17"]), null);
    assert.equal(safeCheckins(["2026-02-30"]), null);
    assert.equal(safeBookmarkUrl("https://example.test/path?q=1#part"), "https://example.test/path?q=1#part");
    for (const url of [
        "http://example.test", "javascript:alert(1)", "https://user@example.test/",
        "https://user:secret@example.test/", "https://example.test\\@evil.test/",
        "https://example.test/\nheader",
    ]) assert.equal(safeBookmarkUrl(url), "");
});

test("datetime-local conversion validates components and round-trips local time", () => {
    const local = "2026-07-17T12:34";
    const iso = localDateTimeToIso(local);
    assert.match(iso, /^2026-07-17T/);
    assert.equal(isoToLocalDateTime(iso), local);
    assert.equal(localDateTimeToIso("2026-02-30T12:00"), "");
    assert.equal(localDateTimeToIso("2026-07-17"), "");
    assert.equal(isoToLocalDateTime("not-a-date"), "");
});

test("focus timer uses absolute deadlines so delayed ticks do not accumulate drift", () => {
    const initial = createTimerState(25);
    assert.equal(formatTimer(timerRemaining(initial, 1_000)), "25:00");
    const running = startTimer(initial, 1_000);
    assert.equal(running.deadline_ms, 1_501_000);
    assert.equal(formatTimer(timerRemaining(running, 61_000)), "24:00");
    assert.equal(formatTimer(timerRemaining(running, 1_500_250)), "00:01");
    const paused = pauseTimer(running, 301_000);
    assert.equal(formatTimer(paused.remaining_ms), "20:00");
    const resumed = startTimer(paused, 900_000);
    assert.equal(resumed.deadline_ms, 2_100_000);
    assert.equal(formatTimer(timerRemaining(resumed, 2_100_001)), "00:00");
    assert.equal(formatTimer(resetTimer(resumed, 5).remaining_ms), "05:00");
    assert.equal(formatCountdown("2026-07-18T00:00:00Z", Date.parse("2026-07-17T23:58:30Z")), "1m 30s");
    assert.equal(formatCountdown("2026-07-17T00:00:00Z", Date.parse("2026-07-18T00:00:00Z")), "Reached");
});

test("the exported DOM contract is unique, reusable, and fully integrated", () => {
    assert.ok(REQUIRED_DOM_IDS.length >= 40);
    assert.equal(new Set(REQUIRED_DOM_IDS).size, REQUIRED_DOM_IDS.length);
    const template = fs.readFileSync(path.join(__dirname, "..", "sites", "templates", "index.html"), "utf8");
    for (const id of REQUIRED_DOM_IDS) {
        assert.match(template, new RegExp(`id=["']${id}["']`), `missing #${id}`);
    }
    assert.match(template, /css\/personal_hub\.css/);
    assert.match(template, /js\/personal_hub\.js/);
    assert.match(template, /cockpit-module-number">10</);
});

test("Personal Hub source uses safe DOM and exact mutation APIs only", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "sites", "static", "js", "personal_hub.js"), "utf8");
    assert.doesNotMatch(source, /\.innerHTML\s*=|insertAdjacentHTML|eval\s*\(|new Function/);
    assert.doesNotMatch(source, /localStorage|sessionStorage|Notification|new Audio|navigator\.permissions|navigator\.geolocation/);
    assert.match(source, /textContent\s*=\s*item\.title/);
    assert.match(source, /anchor\.target\s*=\s*'_blank'/);
    assert.match(source, /anchor\.rel\s*=\s*'noopener noreferrer'/);
    assert.match(source, /anchor\.referrerPolicy\s*=\s*'no-referrer'/);
    assert.match(source, /safeBookmarkUrl\(source\.url\)/);
    assert.match(source, /cache:\s*'no-store'/);
    assert.match(source, /redirect:\s*'error'/);
    assert.match(source, /method:\s*'PATCH', body:\s*\{ version: item\.version/);
    assert.match(source, /\/check-in`[\s\S]*method:\s*'POST', body:\s*\{ version: item\.version, date \}/);
    assert.match(source, /method:\s*'DELETE', body:\s*\{ version: item\.version \}/);
    assert.match(source, /state\.editor\.detail[\s\S]*\? byId\('personalHubCompleted'\)\.checked[\s\S]*: false/);
    assert.match(source, /deadline_ms:\s*now \+ remaining/);
    assert.match(source, /refreshAfterConflict/);
});
