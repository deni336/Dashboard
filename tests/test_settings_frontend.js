"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
    initializeSettings,
    readBackgroundUploadResponse,
    safeShortcutUrl,
    updateBackgroundImage,
} = require("../sites/static/js/settings.js");


function fakeStyle(initialValue = "old-background") {
    const values = new Map([["--kasugai-background-image", initialValue]]);
    return {
        getPropertyValue: (name) => values.get(name) || "",
        removeProperty: (name) => values.delete(name),
        setProperty: (name, value) => values.set(name, value),
    };
}


test("quick shortcuts accept only credential-free HTTPS URLs", () => {
    assert.equal(safeShortcutUrl("https://example.com/tools"), "https://example.com/tools");
    assert.equal(safeShortcutUrl("http://example.com"), "");
    assert.equal(safeShortcutUrl("https://user:secret@example.com"), "");
    assert.equal(safeShortcutUrl("C:\\Windows\\System32\\notepad.exe"), "");
});


test("a verified background image is applied with a cache-busting URL", async () => {
    const previous = {
        document: global.document,
        Image: global.Image,
        window: global.window,
    };
    const style = fakeStyle();
    let requestedUrl = "";
    global.document = { body: { style } };
    global.window = { location: { origin: "http://kasugai.test" } };
    global.Image = class {
        set src(value) {
            requestedUrl = value;
            queueMicrotask(() => this.onload());
        }
    };

    try {
        const appliedUrl = await updateBackgroundImage("/resources/background");
        assert.match(requestedUrl, /^http:\/\/kasugai\.test\/resources\/background\?v=\d+$/);
        assert.equal(appliedUrl, requestedUrl);
        assert.equal(
            style.getPropertyValue("--kasugai-background-image"),
            `url('${requestedUrl}')`,
        );
    } finally {
        global.document = previous.document;
        global.Image = previous.Image;
        global.window = previous.window;
    }
});


test("a background that fails to load does not replace the current image", async () => {
    const previous = {
        document: global.document,
        Image: global.Image,
        window: global.window,
    };
    const style = fakeStyle();
    global.document = { body: { style } };
    global.window = { location: { origin: "http://kasugai.test" } };
    global.Image = class {
        set src(_value) {
            queueMicrotask(() => this.onerror());
        }
    };

    try {
        await assert.rejects(
            updateBackgroundImage("/resources/background"),
            /could not be loaded/,
        );
        assert.equal(
            style.getPropertyValue("--kasugai-background-image"),
            "old-background",
        );
    } finally {
        global.document = previous.document;
        global.Image = previous.Image;
        global.window = previous.window;
    }
});


test("redirected and malformed upload responses cannot report success", async () => {
    await assert.rejects(
        readBackgroundUploadResponse({ redirected: true }),
        /session expired/,
    );
    await assert.rejects(
        readBackgroundUploadResponse({
            redirected: false,
            ok: true,
            json: async () => { throw new SyntaxError("not JSON"); },
        }),
        /invalid background upload response/,
    );
    await assert.rejects(
        readBackgroundUploadResponse({
            redirected: false,
            ok: true,
            json: async () => ({ ok: true }),
        }),
        /incomplete background upload response/,
    );
});


test("a successful upload response returns its verified resource URL", async () => {
    const result = await readBackgroundUploadResponse({
        redirected: false,
        ok: true,
        json: async () => ({ ok: true, url: "/resources/background" }),
    });

    assert.deepEqual(result, { ok: true, url: "/resources/background" });
});


test("the Projects page can load the background without Settings form controls", async () => {
    const previous = {
        document: global.document,
        fetch: global.fetch,
        Image: global.Image,
        window: global.window,
    };
    const style = fakeStyle("");
    global.document = {
        body: { style },
        getElementById: () => null,
    };
    global.window = { location: { origin: "http://kasugai.test" } };
    global.fetch = () => { throw new Error("Settings APIs must not load on Projects"); };
    global.Image = class {
        set src(_value) {
            queueMicrotask(() => this.onload());
        }
    };

    try {
        initializeSettings();
        await new Promise((resolve) => setImmediate(resolve));
        assert.match(
            style.getPropertyValue("--kasugai-background-image"),
            /^url\('http:\/\/kasugai\.test\/resources\/background\?v=\d+'\)$/,
        );
    } finally {
        global.document = previous.document;
        global.fetch = previous.fetch;
        global.Image = previous.Image;
        global.window = previous.window;
    }
});
