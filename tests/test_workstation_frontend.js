"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
    clampPercent,
    formatBytes,
    formatDuration,
    snapshotFrom,
} = require("../sites/static/js/workstation_monitor.js");

test("workstation values are bounded and human readable", () => {
    assert.equal(clampPercent(-4), 0);
    assert.equal(clampPercent(122), 100);
    assert.equal(formatBytes(0), "0 B");
    assert.equal(formatBytes(1024), "1.0 KB");
    assert.equal(formatBytes(null), "—");
    assert.equal(formatDuration(90061), "1d 1h");
});

test("latest telemetry accepts the versioned response envelope", () => {
    const snapshot = { schema_version: 1, cpu: { percent: 20 } };
    assert.equal(snapshotFrom({ snapshot }), snapshot);
    assert.equal(snapshotFrom({ latest: snapshot }), snapshot);
    assert.equal(snapshotFrom(snapshot), snapshot);
    assert.equal(snapshotFrom(null), null);
});

test("workstation frontend keeps server content out of HTML sinks", () => {
    const source = fs.readFileSync(
        path.join(__dirname, "..", "sites", "static", "js", "workstation_monitor.js"),
        "utf8",
    );
    assert.doesNotMatch(source, /\.innerHTML\s*=/);
    assert.match(source, /textContent/);
    assert.match(source, /X-Kasugai-CSRF/);
    assert.match(source, /document\.hidden/);
});
