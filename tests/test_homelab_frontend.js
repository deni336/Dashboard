"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const { normalizedAgents, publicContainer } = require("../sites/static/js/homelab_dashboard.js");

test("homelab list accepts only explicit response arrays", () => {
    const agents = [{ id: "agent-1" }];
    assert.equal(normalizedAgents({ homelabs: agents }), agents);
    assert.equal(normalizedAgents({ agents }), agents);
    assert.deepEqual(normalizedAgents({ homelabs: "bad" }), []);
});

test("container grants are reduced to logs and restart", () => {
    const container = publicContainer({
        key: "opaque", name: "<img src=x>", state: "RUNNING",
        grants: { logs: true, actions: ["restart", "exec", "delete"] },
    });
    assert.equal(container.name, "<img src=x>");
    assert.equal(container.state, "running");
    assert.equal(container.grants.logs, true);
    assert.deepEqual(container.grants.actions, ["restart"]);
});

test("remote inventory is never assigned to HTML", () => {
    const source = fs.readFileSync(
        path.join(__dirname, "..", "sites", "static", "js", "homelab_dashboard.js"), "utf8",
    );
    assert.doesNotMatch(source, /\.innerHTML\s*=/);
    assert.match(source, /textContent/);
    assert.match(source, /X-Kasugai-CSRF/);
    assert.doesNotMatch(source, /docker\.sock|docker_engine/);
    assert.doesNotMatch(source, /operation:\s*['"](?:exec|stop|delete|pull|prune)/);
    assert.match(source, /\\scripts\\\\install-homelab-agent\.ps1/);
});
