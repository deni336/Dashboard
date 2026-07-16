"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
    activityIndicatorState,
    deepLinkState,
    getScaledDimensions,
    parseIncomingEvent,
} = require("../sites/static/js/team_room.js");


test("ordinary room messages retain sender and content", () => {
    assert.deepEqual(
        parseIncomingEvent({ sender: "Aiko", content: "Status is green" }, "user-1"),
        { kind: "message", sender: "Aiko", content: "Status is green" },
    );
});


test("file offers appear only for their intended recipient", () => {
    const offer = {
        type: "file_offer",
        fileId: "file-7",
        name: "plan.pdf",
        recipientId: "user-1",
    };

    assert.deepEqual(
        parseIncomingEvent({ content: JSON.stringify(offer) }, "user-1"),
        { kind: "file_offer", offer },
    );
    assert.deepEqual(
        parseIncomingEvent({ content: JSON.stringify(offer) }, "user-2"),
        { kind: "ignore" },
    );
});


test("screen frames are bounded without enlarging smaller captures", () => {
    assert.deepEqual(getScaledDimensions(1920, 1080), { width: 1280, height: 720 });
    assert.deepEqual(getScaledDimensions(2560, 1600), { width: 1152, height: 720 });
    assert.deepEqual(getScaledDimensions(800, 600), { width: 800, height: 600 });
});


test("legacy screen-share links open Team Room and expand screen sharing", () => {
    assert.deepEqual(deepLinkState("?team_room=open"), {
        open: true,
        expandScreen: false,
    });
    assert.deepEqual(deepLinkState("?team_room=open&screen=expanded"), {
        open: true,
        expandScreen: true,
    });
    assert.deepEqual(deepLinkState("?screen=expanded"), {
        open: false,
        expandScreen: true,
    });
});


test("Team Room activity favors live sharing and caps unread counts", () => {
    assert.deepEqual(activityIndicatorState(false, false, 0), {
        visible: false,
        live: false,
        label: "",
    });
    assert.deepEqual(activityIndicatorState(false, false, 7), {
        visible: true,
        live: false,
        label: "7",
    });
    assert.deepEqual(activityIndicatorState(false, false, 140), {
        visible: true,
        live: false,
        label: "99+",
    });
    assert.deepEqual(activityIndicatorState(false, true, 7), {
        visible: true,
        live: true,
        label: "Live",
    });
    assert.deepEqual(activityIndicatorState(true, true, 7), {
        visible: true,
        live: true,
        label: "Sharing",
    });
});
