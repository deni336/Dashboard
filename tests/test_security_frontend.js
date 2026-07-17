"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
    formatRate,
    normalizeCheck,
    normalizeOverview,
    normalizeSources,
} = require("../sites/static/js/security.js");

function overview(overrides = {}) {
    return {
        generated_at: "2026-07-17T01:00:00Z",
        score: 86,
        grade: "A-",
        checks: [{
            id: "server.csrf", status: "good", title: "Browser mutations require CSRF",
            detail: "State-changing requests are session-bound.", recommendation: "No action needed.",
            private_value: "must-not-survive",
        }],
        sources: {
            workstation: {
                status: "available",
                agents: { total: 3, online: 2, stale: 1, offline: 0 },
                network: { received_bps: 1536, sent_bps: 512 },
                resource_warnings: { cpu: 1, memory: 0, gpu: 0, disk: 0 },
            },
            homelab: {
                status: "available",
                agents: { total: 1, online: 1, stale: 0, offline: 0 },
                engines_unavailable: 0,
                containers: { total: 8, running: 7, unhealthy: 1 },
                health_checks_down: 0,
                updates_available: 2,
            },
            launcher: {
                status: "available",
                agents: { total: 1, online: 1, stale: 0, offline: 0 },
            },
            private: { endpoint: "must-not-survive" },
        },
        ...overrides,
    };
}

test("security overview normalizes the exact passive posture payload", () => {
    const normalized = normalizeOverview(overview({
        raw_devices: ["private-device"], open_ports: [22], command: "ignored",
    }));
    assert.equal(normalized.score, 86);
    assert.equal(normalized.status, "good");
    assert.equal(normalized.checks[0].title, "Browser mutations require CSRF");
    assert.equal(normalized.workstations.total, 3);
    assert.equal(normalized.workstations.total_network_received_bps, 1536);
    assert.equal(normalized.homelab.containers_unhealthy, 1);
    assert.equal(normalized.homelab.engines_unavailable, 0);
    assert.deepEqual(normalized.sources, [
        { id: "workstation", label: "Workstations", status: "good" },
        { id: "homelab", label: "Docker & Homelab", status: "good" },
        { id: "launcher", label: "Task runners", status: "good" },
    ]);
    assert.deepEqual(normalized.errors, []);
    assert.doesNotMatch(JSON.stringify(normalized), /private-device|open_ports|command|must-not-survive|endpoint/);
});

test("security overview remains useful when optional sections are absent", () => {
    const normalized = normalizeOverview({ generated_at: "2026-07-17T01:00:00Z", score: 52 });
    assert.equal(normalized.status, "critical");
    assert.deepEqual(normalized.checks, []);
    assert.deepEqual(normalized.sources.map(source => source.status), ["unavailable", "unavailable", "unavailable"]);
    assert.deepEqual(normalized.errors.map(error => error.source), ["workstation", "homelab", "launcher"]);
    assert.equal(normalized.workstations.online, null);
    assert.equal(normalized.homelab.containers_total, null);
    assert.equal(normalized.launcher.offline, null);
    assert.throws(() => normalizeOverview(null), /invalid security overview/i);
});

test("checks and exact nested source coverage use fixed safe shapes", () => {
    assert.deepEqual(normalizeCheck({
        id: "docker.socket", status: "critical", title: "Docker socket exposed",
        detail: "Remove the direct mount.", recommendation: "Use the outbound agent.",
        html: "<img onerror=alert(1)>",
    }), {
        id: "docker.socket", status: "critical", title: "Docker socket exposed",
        detail: "Remove the direct mount.", recommendation: "Use the outbound agent.",
    });
    assert.equal(normalizeCheck({ id: "bad/id", status: "good", title: "Bad" }), null);
    assert.equal(normalizeCheck({ id: "valid", status: "unknown", title: "Bad" }), null);

    const sources = normalizeSources({
        workstation: {
            status: "available",
            agents: { total: 2, online: 1, stale: 1, offline: 0 },
            network: { received_bps: 2048, sent_bps: 1024 },
            resource_warnings: { cpu: 1, memory: 2, gpu: 0, disk: 0 },
        },
        homelab: {
            status: "unavailable",
            agents: { total: 0, online: 0, stale: 0, offline: 0 },
            engines_unavailable: 1,
            containers: { total: 0, running: 0, unhealthy: 0 },
            health_checks_down: 0,
            updates_available: 0,
        },
        ignored: { endpoint: "private" },
    });
    assert.deepEqual(sources.coverage, [
        { id: "workstation", label: "Workstations", status: "good" },
        { id: "homelab", label: "Docker & Homelab", status: "unavailable" },
        { id: "launcher", label: "Task runners", status: "unavailable" },
    ]);
    assert.deepEqual(sources.errors, [
        { source: "homelab", message: "Docker & Homelab posture data is currently unavailable." },
        { source: "launcher", message: "Task runners posture data is currently unavailable." },
    ]);
    assert.equal(sources.workstations.resource_warnings, 3);
    assert.deepEqual(sources.workstations.warning_breakdown, { cpu: 1, memory: 2, gpu: 0, disk: 0 });
    assert.equal(sources.workstations.total_network_received_bps, 2048);
    assert.equal(sources.homelab.engines_unavailable, 1);
    assert.equal(sources.launcher.source_status, "unavailable");
});

test("security throughput formatting is bounded and human readable", () => {
    assert.equal(formatRate(0), "0 B/s");
    assert.equal(formatRate(1536), "1.5 KB/s");
    assert.equal(formatRate(5 * 1024 * 1024), "5.0 MB/s");
    assert.equal(formatRate(-1), "\u2014");
    assert.equal(formatRate(Number.NaN), "\u2014");
});

test("security browser code is read-only and uses safe DOM rendering", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "sites", "static", "js", "security.js"), "utf8");
    assert.doesNotMatch(source, /\.innerHTML\s*=/);
    assert.doesNotMatch(source, /eval\s*\(|new Function|child_process|WebSocket|EventSource/i);
    assert.doesNotMatch(source, /method:\s*['"](?:POST|PATCH|PUT|DELETE)['"]/);
    assert.doesNotMatch(source, /\/scan|portscan|nmap|masscan/i);
    assert.match(source, /textContent/);
    assert.match(source, /replaceChildren/);
    assert.match(source, /\/api\/security\/overview/);
    assert.match(source, /cache:\s*'no-store'/);
    assert.match(source, /redirect:\s*'error'/);
});

test("security module is included in the numbered dashboard flow", () => {
    const template = fs.readFileSync(path.join(__dirname, "..", "sites", "templates", "index.html"), "utf8");
    assert.match(template, /id="securityModule"/);
    assert.match(template, /cockpit-module-number">08</);
    assert.match(template, /id="securityScoreRing"/);
    assert.match(template, /id="securityCheckGrid"/);
    assert.match(template, /id="securityWorkstationDetails"/);
    assert.match(template, /id="securityErrorDisclosure"/);
    assert.match(template, /css\/security\.css/);
    assert.match(template, /js\/security\.js/);
    assert.match(template, /does not scan networks, enumerate ports, probe devices/);
});
