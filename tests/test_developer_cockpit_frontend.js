"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
    filterRepositories,
    readJsonResponse,
    repositoryNeedsSync,
    validatedGithubUrl,
} = require("../sites/static/js/developer_cockpit.js");


test("repository filters combine state and case-insensitive search", () => {
    const repositories = [
        { name: "Kasugai", display_path: "Work/Kasugai", favorite: true, dirty: false, ahead: 0, behind: 0 },
        { name: "Website", display_path: "Personal/site", favorite: false, dirty: true, ahead: 0, behind: 2 },
        { name: "Toolbox", display_path: "Lab/tools", favorite: false, dirty: false, ahead: 1, behind: 0 },
    ];

    assert.deepEqual(filterRepositories(repositories, "KAS", "all"), [repositories[0]]);
    assert.deepEqual(filterRepositories(repositories, "personal", "dirty"), [repositories[1]]);
    assert.deepEqual(filterRepositories(repositories, "", "favorites"), [repositories[0]]);
    assert.deepEqual(filterRepositories(repositories, "", "sync"), [repositories[1], repositories[2]]);
});


test("sync state requires a positive ahead or behind count", () => {
    assert.equal(repositoryNeedsSync({ ahead: 1, behind: 0 }), true);
    assert.equal(repositoryNeedsSync({ ahead: 0, behind: "2" }), true);
    assert.equal(repositoryNeedsSync({ ahead: 0, behind: 0 }), false);
    assert.equal(repositoryNeedsSync({ ahead: -1, behind: "invalid" }), false);
});


test("outbound links are restricted to simple HTTPS GitHub repository URLs", () => {
    assert.equal(
        validatedGithubUrl("https://github.com/openai/codex/"),
        "https://github.com/openai/codex",
    );
    assert.equal(validatedGithubUrl("http://github.com/openai/codex"), null);
    assert.equal(validatedGithubUrl("https://github.example/openai/codex"), null);
    assert.equal(validatedGithubUrl("https://github.com.evil.example/openai/codex"), null);
    assert.equal(validatedGithubUrl("https://user@github.com/openai/codex"), null);
    assert.equal(validatedGithubUrl("https://github.com/openai/codex/issues"), null);
    assert.equal(validatedGithubUrl("https://github.com/openai/codex?tab=readme"), null);
    assert.equal(validatedGithubUrl("javascript:alert(1)"), null);
});


test("API responses reject redirects, malformed payloads, and backend errors", async () => {
    await assert.rejects(readJsonResponse({ redirected: true, status: 200 }), /session expired/);
    await assert.rejects(readJsonResponse({
        redirected: false,
        status: 200,
        ok: true,
        json: async () => { throw new SyntaxError("bad json"); },
    }), /invalid dashboard response/);
    await assert.rejects(readJsonResponse({
        redirected: false,
        status: 400,
        ok: false,
        json: async () => ({ error: "Root is not allowed" }),
    }), /Root is not allowed/);
});


test("API-controlled content is rendered without HTML string sinks", () => {
    const source = fs.readFileSync(
        path.join(__dirname, "..", "sites", "static", "js", "developer_cockpit.js"),
        "utf8",
    );
    assert.doesNotMatch(source, /\.innerHTML\s*=/);
    assert.match(source, /textContent/);
    assert.match(source, /X-Kasugai-CSRF/);
    assert.match(source, /rel = 'noopener noreferrer'/);
});
