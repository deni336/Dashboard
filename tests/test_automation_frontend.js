"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
    normalizeAction,
    normalizeAutomations,
    normalizeCatalog,
    normalizeRule,
    normalizeRun,
    normalizeTrigger,
} = require("../sites/static/js/automation.js");

const RULE_ID = "automationRule_0123456789";
const RUN_ID = "automationRun_01234567890";
const TASK_ID = "a".repeat(32);

test("automation normalizers accept only fixed trigger variants", () => {
    assert.deepEqual(normalizeTrigger({ type: "interval", minutes: 15, ignored: true }), { type: "interval", minutes: 15 });
    assert.deepEqual(normalizeTrigger({ type: "daily", time: "09:30" }), { type: "daily", time: "09:30" });
    assert.deepEqual(normalizeTrigger({ type: "event", source: "homelab", severity: "warning" }), {
        type: "event", source: "homelab", severity: "warning",
    });
    assert.deepEqual(normalizeTrigger({
        type: "metric", metric: "workstation.memory_percent", operator: "gte", threshold: 85,
    }), { type: "metric", metric: "workstation.memory_percent", operator: "gte", threshold: 85 });

    assert.equal(normalizeTrigger({ type: "cron", expression: "* * * * *" }), null);
    assert.equal(normalizeTrigger({ type: "event", source: "custom", severity: "warning" }), null);
    assert.equal(normalizeTrigger({ type: "metric", metric: "../../private", operator: "gt", threshold: 1 }), null);
});

test("automation actions are notifications or opaque approved task IDs", () => {
    assert.deepEqual(normalizeAction({
        type: "notify", title: "Disk pressure", body: "Usage crossed the threshold", severity: "error",
        html: "<b>unsafe</b>", url: "https://example.com",
    }), { type: "notify", title: "Disk pressure", body: "Usage crossed the threshold", severity: "error" });
    assert.deepEqual(normalizeAction({
        type: "launcher_task", task_id: TASK_ID, argv: ["unsafe"], environment: { TOKEN: "hidden" },
    }), { type: "launcher_task", task_id: TASK_ID });
    assert.equal(normalizeAction({ type: "launcher_task", task_id: "not-opaque" }), null);
    assert.equal(normalizeAction({ type: "webhook", url: "https://example.com" }), null);
});

test("public automation rules and outcomes are bounded to their display contract", () => {
    const rule = normalizeRule({
        id: RULE_ID,
        name: "Memory alert",
        enabled: true,
        trigger: { type: "metric", metric: "workstation.memory_percent", operator: "gt", threshold: 90 },
        action: { type: "notify", title: "High memory", body: "Memory is high", severity: "warning" },
        cooldown_minutes: 30,
        last_run_at: "2026-07-16T12:00:00Z",
        next_run_at: "2026-07-16T12:30:00Z",
        created_at: "2026-07-16T10:00:00Z",
        updated_at: "2026-07-16T11:00:00Z",
        secret: "must-not-survive",
    });
    assert.equal(rule.name, "Memory alert");
    assert.equal(rule.cooldown_minutes, 30);
    assert.doesNotMatch(JSON.stringify(rule), /must-not-survive|secret/);

    const run = normalizeRun({
        id: RUN_ID, rule_id: RULE_ID, rule_name: "Memory alert", status: "succeeded",
        triggered_at: "2026-07-16T12:00:00Z", completed_at: "2026-07-16T12:00:01Z",
        summary: "Notification created", result: { output: "hidden" },
    });
    assert.equal(run.status, "succeeded");
    assert.doesNotMatch(JSON.stringify(run), /output|hidden/);
    assert.equal(normalizeRun({ ...run, status: "running" }).status, "running");
    assert.equal(normalizeRun({ ...run, status: "queued" }), null);
});

test("automation response and catalog require exact arrays and fixed operators", () => {
    const response = normalizeAutomations({
        rules: [{
            id: RULE_ID, name: "Daily check", enabled: false,
            trigger: { type: "daily", time: "08:00" },
            action: { type: "launcher_task", task_id: TASK_ID }, cooldown_minutes: 5,
        }],
        runs: [],
    });
    assert.equal(response.rules.length, 1);
    assert.throws(() => normalizeAutomations({ automations: [] }), /invalid automation response/i);

    const catalog = normalizeCatalog({
        metrics: [{
            id: "homelab.cpu_percent", label: "Homelab CPU", unit: "%",
            operators: ["gt", "gte", "custom", "gt"], private_value: 99,
        }],
        launcher_tasks: [{
            id: TASK_ID, title: "Refresh indexes", agent_name: "Utility runner",
            requires_confirmation: false, argv: ["ignored"],
        }],
    });
    assert.deepEqual(catalog.metrics[0].operators, ["gt", "gte"]);
    assert.equal(catalog.launcher_tasks[0].title, "Refresh indexes");
    assert.doesNotMatch(JSON.stringify(catalog), /private_value|argv|ignored/);
    assert.throws(() => normalizeCatalog({ metrics: [], tasks: [] }), /invalid automation catalog/i);
});

test("automation browser code uses guarded JSON APIs and safe DOM sinks", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "sites", "static", "js", "automation.js"), "utf8");
    assert.doesNotMatch(source, /\.innerHTML\s*=/);
    assert.doesNotMatch(source, /eval\s*\(|new Function|child_process|shell/i);
    assert.doesNotMatch(source, /window\.location|window\.open/);
    assert.match(source, /textContent/);
    assert.match(source, /replaceChildren/);
    assert.match(source, /meta\[name="kasugai-csrf-token"\]/);
    assert.match(source, /cache:\s*'no-store'/);
    assert.match(source, /redirect:\s*'error'/);
    assert.match(source, /\/api\/automations\/catalog/);
    assert.match(source, /cooldown_minutes/);
    assert.match(source, /method:\s*'DELETE'\s*\}/);
    assert.doesNotMatch(source, /method:\s*'DELETE'\s*,\s*body/);
});
