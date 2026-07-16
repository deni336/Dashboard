// One shared Team Room controller for chat, file offers, and screen sharing.
// It is intentionally page-agnostic so Home and Projects use one interaction
// model and exactly one Socket.IO polling connection per page.

(function (root) {
    'use strict';

    const FRAME_INTERVAL_MS = 500;
    const JPEG_QUALITY = 0.55;
    const MAX_FRAME_WIDTH = 1280;
    const MAX_FRAME_HEIGHT = 720;
    const DRAWER_CLOSE_DELAY_MS = 240;

    const state = {
        socket: null,
        currentRoom: '',
        screenStream: null,
        captureIntervalId: null,
        captureCanvas: null,
        frameInFlight: false,
        returnFocus: null,
        hideTimer: null,
        remoteScreenActive: false,
        unreadCount: 0,
    };

    function byId(id) {
        return document.getElementById(id);
    }

    function currentUserId() {
        return String(
            byId('teamRoomDrawer')?.dataset.currentUserId
            || root.CURRENT_USER_ID
            || '',
        );
    }

    function parseIncomingEvent(data, currentUserId) {
        const content = data && typeof data.content === 'string' ? data.content : '';
        try {
            const parsed = JSON.parse(content);
            if (parsed && parsed.type === 'file_offer') {
                return parsed.recipientId === currentUserId
                    ? { kind: 'file_offer', offer: parsed }
                    : { kind: 'ignore' };
            }
        } catch (_error) {
            // Ordinary chat messages are not JSON.
        }
        return {
            kind: 'message',
            sender: String((data && data.sender) || 'Room member'),
            content,
        };
    }

    function getScaledDimensions(width, height) {
        const safeWidth = Math.max(1, Number(width) || 1);
        const safeHeight = Math.max(1, Number(height) || 1);
        const scale = Math.min(
            1,
            MAX_FRAME_WIDTH / safeWidth,
            MAX_FRAME_HEIGHT / safeHeight,
        );
        return {
            width: Math.max(1, Math.round(safeWidth * scale)),
            height: Math.max(1, Math.round(safeHeight * scale)),
        };
    }

    function deepLinkState(search) {
        const params = new URLSearchParams(search || '');
        return {
            open: params.get('team_room') === 'open',
            expandScreen: params.get('screen') === 'expanded',
        };
    }

    async function readJsonResponse(response, fallbackMessage) {
        if (response.redirected) {
            throw new Error('Your session expired. Sign in again to use Team Room.');
        }
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.error || fallbackMessage);
        }
        return payload;
    }

    function setText(id, message, isError) {
        const element = byId(id);
        if (!element) return;
        element.textContent = message || '';
        element.classList.toggle('is-error', Boolean(isError));
    }

    function setRoomControls(active) {
        const gatedControls = [
            byId('chatInput'),
            byId('sendChat'),
            byId('toggleFileComposerBtn'),
        ];
        gatedControls.forEach(control => {
            if (control) control.disabled = !active;
        });
        const startScreenShare = byId('startScreenShareBtn');
        if (startScreenShare) {
            startScreenShare.disabled = !active
                || Boolean(state.screenStream)
                || state.remoteScreenActive;
        }
        const drawer = byId('teamRoomDrawer');
        if (drawer) drawer.dataset.roomActive = active ? 'true' : 'false';
        const input = byId('chatInput');
        if (input) {
            input.placeholder = active
                ? 'Message the room…'
                : 'Join or create a room to start collaborating';
        }
        const connectionBadge = byId('roomConnectionBadge');
        const connectionText = byId('roomConnectionText');
        const selectedRoom = byId('roomSelect')?.selectedOptions?.[0]?.textContent;
        connectionBadge?.classList.toggle('is-connected', active);
        if (connectionText) {
            connectionText.textContent = active && selectedRoom
                ? selectedRoom
                : 'Not connected';
        }
    }

    function activityIndicatorState(isSharing, remoteScreenActive, unreadCount) {
        if (isSharing) return { visible: true, live: true, label: 'Sharing' };
        if (remoteScreenActive) return { visible: true, live: true, label: 'Live' };
        if (unreadCount > 0) {
            return {
                visible: true,
                live: false,
                label: unreadCount > 99 ? '99+' : String(unreadCount),
            };
        }
        return { visible: false, live: false, label: '' };
    }

    function updateActivityBadges() {
        const indicator = activityIndicatorState(
            Boolean(state.screenStream),
            state.remoteScreenActive,
            state.unreadCount,
        );
        document.querySelectorAll('[data-team-room-activity]').forEach(badge => {
            badge.hidden = !indicator.visible;
            badge.textContent = indicator.label;
            badge.classList.toggle('is-live', indicator.live);
        });
        const accessibleStatus = indicator.label === 'Sharing'
            ? 'sharing your screen'
            : indicator.label === 'Live'
                ? 'live screen share'
                : indicator.visible
                    ? `${indicator.label} unread`
                    : '';
        document.querySelectorAll('[data-team-room-trigger]').forEach(trigger => {
            trigger.setAttribute(
                'aria-label',
                accessibleStatus ? `Team Room, ${accessibleStatus}` : 'Team Room',
            );
        });
    }

    function markUnreadActivity() {
        if (drawerIsOpen()) return;
        state.unreadCount += 1;
        updateActivityBadges();
    }

    function resetConversation(roomName) {
        const timeline = byId('chatMessages');
        if (!timeline) return;
        timeline.innerHTML = '';
        const empty = document.createElement('div');
        empty.className = 'team-room-empty-state';
        empty.id = 'chatEmptyState';
        const icon = document.createElement('i');
        icon.setAttribute('data-lucide', 'message-circle');
        icon.setAttribute('aria-hidden', 'true');
        const title = document.createElement('strong');
        title.textContent = roomName ? `Welcome to ${roomName}` : 'Start the conversation';
        const copy = document.createElement('span');
        copy.textContent = 'Messages and shared files will appear here.';
        empty.append(icon, title, copy);
        timeline.appendChild(empty);
        root.lucide?.createIcons();
    }

    function renderRooms(payload, preferredRoom) {
        const select = byId('roomSelect');
        if (!select) return;
        const rooms = Array.isArray(payload && payload.rooms) ? payload.rooms : [];
        const activeRoom = preferredRoom || (payload && payload.current_room) || '';
        const previousRoom = state.currentRoom;
        select.innerHTML = '';

        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = rooms.length ? 'Choose a room' : 'No rooms yet';
        select.appendChild(placeholder);

        rooms.forEach(room => {
            if (!room || typeof room.id !== 'string') return;
            const option = document.createElement('option');
            option.value = room.id;
            option.textContent = room.name || room.id;
            select.appendChild(option);
        });

        if (activeRoom && rooms.some(room => room.id === activeRoom)) {
            select.value = activeRoom;
            state.currentRoom = activeRoom;
        } else {
            state.currentRoom = '';
        }
        setRoomControls(Boolean(state.currentRoom));
        if (previousRoom && state.currentRoom && previousRoom !== state.currentRoom) {
            resetConversation(select.selectedOptions[0]?.textContent || 'the room');
        }
        setText(
            'roomActionStatus',
            state.currentRoom ? `Connected to ${select.selectedOptions[0].textContent}.` : 'Choose or create a room to begin.',
            false,
        );
    }

    async function loadRooms(preferredRoom) {
        try {
            const response = await fetch('/api/rooms', { headers: { Accept: 'application/json' } });
            const payload = await readJsonResponse(response, 'Unable to load rooms.');
            renderRooms(payload, preferredRoom);
        } catch (error) {
            setText('roomActionStatus', error.message, true);
        }
    }

    async function joinSelectedRoom() {
        const select = byId('roomSelect');
        const room = select && select.value;
        if (!room) {
            setText('roomActionStatus', 'Choose a room first.', true);
            return;
        }
        const button = byId('joinRoomBtn');
        if (button) button.disabled = true;
        setText('roomActionStatus', 'Joining room…', false);
        try {
            const response = await fetch('/join_room', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({
                    room,
                    password: (byId('joinRoomPassword') && byId('joinRoomPassword').value) || '',
                }),
            });
            await readJsonResponse(response, 'Unable to join that room.');
            if (byId('joinRoomPassword')) byId('joinRoomPassword').value = '';
            await loadRooms(room);
            root.KasugaiFileTransfer?.openPanel();
        } catch (error) {
            setText('roomActionStatus', error.message, true);
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function createRoom() {
        const nameInput = byId('newRoomName');
        const roomName = nameInput ? nameInput.value.trim() : '';
        if (!roomName) {
            setText('roomActionStatus', 'Enter a room name.', true);
            nameInput?.focus();
            return;
        }
        const button = byId('createRoomBtn');
        if (button) button.disabled = true;
        setText('roomActionStatus', 'Creating room…', false);
        try {
            const response = await fetch('/create_room', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({
                    roomName,
                    roomPassword: (byId('roomPassword') && byId('roomPassword').value) || '',
                }),
            });
            const payload = await readJsonResponse(response, 'Unable to create the room.');
            nameInput.value = '';
            if (byId('roomPassword')) byId('roomPassword').value = '';
            togglePanel('createRoomPanel', 'toggleCreateRoomBtn', false);
            await loadRooms(payload.room && payload.room.id);
            root.KasugaiFileTransfer?.openPanel();
        } catch (error) {
            setText('roomActionStatus', error.message, true);
        } finally {
            if (button) button.disabled = false;
        }
    }

    function removeChatEmptyState() {
        byId('chatEmptyState')?.remove();
    }

    function appendMessage(sender, content) {
        const timeline = byId('chatMessages');
        if (!timeline) return;
        removeChatEmptyState();
        const message = document.createElement('article');
        message.className = 'team-room-message';
        const isOwnMessage = String(sender) === currentUserId();
        message.classList.toggle('is-own', isOwnMessage);
        const heading = document.createElement('strong');
        heading.textContent = isOwnMessage ? 'You' : sender;
        const body = document.createElement('p');
        body.textContent = content;
        message.append(heading, body);
        timeline.appendChild(message);
        if (drawerIsOpen()) {
            message.scrollIntoView({ block: 'nearest' });
        }
    }

    async function sendMessage(event) {
        event.preventDefault();
        const input = byId('chatInput');
        const message = input ? input.value.trim() : '';
        if (!state.currentRoom || !message) return;
        const button = byId('sendChat');
        if (button) button.disabled = true;
        setText('chatSendStatus', '', false);
        try {
            const response = await fetch('/send_message', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    Accept: 'application/json',
                },
                body: new URLSearchParams({ message }),
            });
            await readJsonResponse(response, 'Unable to send the message.');
            input.value = '';
        } catch (error) {
            setText('chatSendStatus', error.message, true);
        } finally {
            if (button) button.disabled = !state.currentRoom;
        }
    }

    function showScreenStage(visible) {
        const stage = byId('screenShareStage');
        if (stage) stage.hidden = !visible;
        const screenSection = stage?.closest('.team-room-screen-section');
        screenSection?.classList.toggle('is-active', visible);
    }

    function setScreenControls(isSharing) {
        const start = byId('startScreenShareBtn');
        const stop = byId('stopScreenShareBtn');
        if (start) start.disabled = isSharing || state.remoteScreenActive || !state.currentRoom;
        if (stop) {
            stop.disabled = !isSharing;
            stop.hidden = !isSharing;
        }
        byId('teamRoomDrawer')?.classList.toggle('is-sharing', isSharing);
        updateActivityBadges();
    }

    function getFullscreenElement() {
        return document.fullscreenElement
            || document.webkitFullscreenElement
            || document.msFullscreenElement;
    }

    function updateFullscreenButton() {
        const container = byId('videoContainer');
        const button = byId('fullscreenScreenShareBtn');
        if (!container || !button) return;
        const fullscreen = getFullscreenElement() === container;
        button.setAttribute('aria-pressed', String(fullscreen));
        button.setAttribute('aria-label', fullscreen ? 'Exit full screen' : 'View shared screen full screen');
        const label = button.querySelector('span');
        if (label) label.textContent = fullscreen ? 'Exit full screen' : 'Full screen';
    }

    function canvasToJpegBlob(canvas) {
        return new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY));
    }

    async function captureAndSendFrame() {
        const video = byId('screenVideo');
        if (
            state.frameInFlight
            || !state.screenStream
            || !video
            || !video.videoWidth
            || !video.videoHeight
        ) return;

        state.frameInFlight = true;
        try {
            state.captureCanvas = state.captureCanvas || document.createElement('canvas');
            const canvas = state.captureCanvas;
            const size = getScaledDimensions(video.videoWidth, video.videoHeight);
            canvas.width = size.width;
            canvas.height = size.height;
            canvas.getContext('2d', { alpha: false }).drawImage(
                video,
                0,
                0,
                size.width,
                size.height,
            );
            const blob = await canvasToJpegBlob(canvas);
            if (!blob || !state.screenStream) return;
            const response = await fetch('/api/screenshare/frame', {
                method: 'POST',
                headers: { 'Content-Type': 'image/jpeg' },
                body: blob,
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(payload.error || 'Unable to share this frame.');
            }
        } catch (error) {
            setText('screenShareStatus', error.message, true);
        } finally {
            state.frameInFlight = false;
        }
    }

    async function startScreenShare() {
        if (!state.currentRoom) {
            setText('screenShareStatus', 'Join a room before sharing your screen.', true);
            setText('roomActionStatus', 'Join a room before sharing your screen.', true);
            return;
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
            setText('screenShareStatus', 'Screen capture is not supported by this browser.', true);
            setText('roomActionStatus', 'Screen capture is not supported by this browser.', true);
            return;
        }
        try {
            state.screenStream = await navigator.mediaDevices.getDisplayMedia({
                video: { cursor: 'always', frameRate: { ideal: 5, max: 8 } },
                audio: false,
            });
            const localVideo = byId('screenVideo');
            const remoteImage = byId('remoteScreenView');
            localVideo.srcObject = state.screenStream;
            localVideo.hidden = false;
            if (remoteImage) remoteImage.hidden = true;
            await localVideo.play().catch(() => {});
            showScreenStage(true);
            setScreenControls(true);
            setText('screenShareStatus', 'You are sharing your screen.', false);
            setText('roomActionStatus', '', false);
            captureAndSendFrame();
            state.captureIntervalId = window.setInterval(captureAndSendFrame, FRAME_INTERVAL_MS);
            const [track] = state.screenStream.getVideoTracks();
            track?.addEventListener('ended', stopScreenShare, { once: true });
        } catch (error) {
            if (error.name !== 'NotAllowedError') {
                setText('screenShareStatus', error.message || 'Unable to start screen sharing.', true);
                setText('roomActionStatus', error.message || 'Unable to start screen sharing.', true);
            }
            setScreenControls(false);
        }
    }

    async function stopScreenShare() {
        if (state.captureIntervalId) {
            window.clearInterval(state.captureIntervalId);
            state.captureIntervalId = null;
        }
        state.screenStream?.getTracks().forEach(track => track.stop());
        state.screenStream = null;
        const localVideo = byId('screenVideo');
        if (localVideo) {
            localVideo.srcObject = null;
            localVideo.hidden = true;
        }
        const remoteImage = byId('remoteScreenView');
        const remoteVisible = remoteImage && !remoteImage.hidden;
        state.remoteScreenActive = Boolean(remoteVisible);
        showScreenStage(Boolean(remoteVisible));
        setScreenControls(false);
        setText(
            'screenShareStatus',
            remoteVisible ? 'A room member is sharing.' : 'Screen sharing is idle.',
            false,
        );
        try {
            await fetch('/api/screenshare/stop', { method: 'POST' });
        } catch (_error) {
            // Local capture is already stopped; the server will expire the stream.
        }
    }

    async function toggleFullscreen() {
        const container = byId('videoContainer');
        if (!container) return;
        try {
            if (getFullscreenElement() === container) {
                const exit = document.exitFullscreen
                    || document.webkitExitFullscreen
                    || document.msExitFullscreen;
                if (exit) await exit.call(document);
            } else {
                const request = container.requestFullscreen
                    || container.webkitRequestFullscreen
                    || container.msRequestFullscreen;
                if (!request) throw new Error('Full screen is not supported by this browser.');
                await request.call(container);
            }
            updateFullscreenButton();
        } catch (error) {
            setText('screenShareStatus', error.message, true);
        }
    }

    function togglePanel(panelId, buttonId, forceOpen) {
        const panel = byId(panelId);
        const button = byId(buttonId);
        if (!panel || !button) return;
        const open = forceOpen === undefined ? panel.hidden : Boolean(forceOpen);
        panel.hidden = !open;
        button.setAttribute('aria-expanded', String(open));
        if (open && panelId === 'fileComposer') {
            root.KasugaiFileTransfer?.openPanel();
            byId('fileRecipient')?.focus();
        }
    }

    function drawerIsOpen() {
        const drawer = byId('teamRoomDrawer');
        return Boolean(drawer && !drawer.hidden && drawer.getAttribute('aria-hidden') === 'false');
    }

    function closeCompetingSurface() {
        const settings = byId('settingsModal');
        if (settings && settings.classList.contains('is-open')) {
            settings.querySelector('.close')?.click();
        }
        const assistant = byId('assistantDialog');
        if (assistant && assistant.getAttribute('aria-hidden') === 'false') {
            assistant.querySelector('[data-close-dialog]')?.click();
        }
    }

    function openDrawer(opener) {
        const drawer = byId('teamRoomDrawer');
        if (!drawer || drawerIsOpen()) return;
        closeCompetingSurface();
        if (state.hideTimer) window.clearTimeout(state.hideTimer);
        state.returnFocus = opener && opener.focus ? opener : document.activeElement;
        drawer.hidden = false;
        drawer.setAttribute('aria-hidden', 'false');
        void drawer.offsetWidth;
        drawer.classList.add('is-open');
        state.unreadCount = 0;
        updateActivityBadges();
        document.querySelectorAll('[data-team-room-trigger]').forEach(button => {
            button.setAttribute('aria-expanded', 'true');
        });
        loadRooms();
        root.KasugaiFileTransfer?.openPanel();
        window.setTimeout(() => byId('teamRoomCloseButton')?.focus(), 0);
    }

    function closeDrawer(options) {
        const drawer = byId('teamRoomDrawer');
        if (!drawer || !drawerIsOpen()) return;
        drawer.classList.remove('is-open');
        drawer.setAttribute('aria-hidden', 'true');
        document.querySelectorAll('[data-team-room-trigger]').forEach(button => {
            button.setAttribute('aria-expanded', 'false');
        });
        state.hideTimer = window.setTimeout(() => {
            if (drawer.getAttribute('aria-hidden') === 'true') drawer.hidden = true;
        }, DRAWER_CLOSE_DELAY_MS);
        if (!options || options.restoreFocus !== false) {
            state.returnFocus?.focus?.();
        }
    }

    function connectSocket() {
        if (state.socket || typeof root.io !== 'function') return;
        state.socket = root.io({ transports: ['polling'] });
        state.socket.on('new_message', data => {
            const event = parseIncomingEvent(data, currentUserId());
            if (event.kind === 'file_offer') {
                markUnreadActivity();
                root.KasugaiFileTransfer?.addOffer(event.offer);
            } else if (event.kind === 'message') {
                if (event.sender !== currentUserId()) markUnreadActivity();
                appendMessage(event.sender, event.content);
            }
        });
        state.socket.on('screen_frame', data => {
            if (String(data.sender || '') === currentUserId()) return;
            const remoteImage = byId('remoteScreenView');
            const localVideo = byId('screenVideo');
            if (!remoteImage) return;
            remoteImage.src = `data:image/jpeg;base64,${data.data}`;
            remoteImage.hidden = false;
            if (!state.screenStream && localVideo) localVideo.hidden = true;
            if (!state.remoteScreenActive) markUnreadActivity();
            state.remoteScreenActive = true;
            showScreenStage(true);
            setText('screenShareStatus', 'A room member is sharing.', false);
            setScreenControls(Boolean(state.screenStream));
            updateActivityBadges();
        });
        state.socket.on('screen_share_stopped', data => {
            if (String((data && data.sender) || '') === currentUserId()) return;
            const remoteImage = byId('remoteScreenView');
            if (remoteImage) {
                remoteImage.hidden = true;
                remoteImage.removeAttribute('src');
            }
            state.remoteScreenActive = false;
            showScreenStage(Boolean(state.screenStream));
            if (!state.screenStream) setText('screenShareStatus', 'Screen sharing is idle.', false);
            setScreenControls(Boolean(state.screenStream));
            updateActivityBadges();
        });
    }

    function initializeTeamRoom() {
        if (!byId('teamRoomDrawer')) return;
        setRoomControls(false);
        setScreenControls(false);
        connectSocket();

        document.querySelectorAll('[data-team-room-trigger]').forEach(button => {
            button.addEventListener('click', event => {
                event.preventDefault();
                drawerIsOpen() ? closeDrawer() : openDrawer(button);
            });
        });
        byId('teamRoomCloseButton')?.addEventListener('click', () => closeDrawer());
        byId('joinRoomBtn')?.addEventListener('click', joinSelectedRoom);
        byId('createRoomBtn')?.addEventListener('click', createRoom);
        byId('toggleCreateRoomBtn')?.addEventListener('click', () => {
            togglePanel('createRoomPanel', 'toggleCreateRoomBtn');
        });
        byId('toggleFileComposerBtn')?.addEventListener('click', () => {
            togglePanel('fileComposer', 'toggleFileComposerBtn');
        });
        byId('closeFileComposerBtn')?.addEventListener('click', () => {
            togglePanel('fileComposer', 'toggleFileComposerBtn', false);
            byId('toggleFileComposerBtn')?.focus();
        });
        const fileInput = byId('fileToSend');
        const updateFileLabel = () => {
            const label = byId('filePickerLabel');
            if (label) label.textContent = fileInput?.files?.[0]?.name || 'Choose a file';
        };
        fileInput?.addEventListener('change', updateFileLabel);
        byId('sendFileForm')?.addEventListener('reset', () => window.setTimeout(updateFileLabel, 0));
        byId('chatForm')?.addEventListener('submit', sendMessage);
        byId('chatInput')?.addEventListener('keydown', event => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                byId('chatForm')?.requestSubmit();
            }
        });
        byId('startScreenShareBtn')?.addEventListener('click', startScreenShare);
        byId('stopScreenShareBtn')?.addEventListener('click', stopScreenShare);
        byId('fullscreenScreenShareBtn')?.addEventListener('click', toggleFullscreen);

        ['fullscreenchange', 'webkitfullscreenchange', 'msfullscreenchange'].forEach(name => {
            document.addEventListener(name, updateFullscreenButton);
        });
        window.addEventListener('pagehide', () => {
            if (!state.screenStream) return;
            if (navigator.sendBeacon) {
                navigator.sendBeacon('/api/screenshare/stop', new Blob([]));
            } else {
                fetch('/api/screenshare/stop', { method: 'POST', keepalive: true }).catch(() => {});
            }
            state.screenStream.getTracks().forEach(track => track.stop());
        });
        document.addEventListener('keydown', event => {
            if (event.key !== 'Escape' || !drawerIsOpen()) return;
            if (byId('fileComposer') && !byId('fileComposer').hidden) {
                togglePanel('fileComposer', 'toggleFileComposerBtn', false);
            } else if (byId('createRoomPanel') && !byId('createRoomPanel').hidden) {
                togglePanel('createRoomPanel', 'toggleCreateRoomBtn', false);
            } else {
                closeDrawer();
            }
        });

        const linkState = deepLinkState(window.location.search);
        if (linkState.open) {
            openDrawer(document.querySelector('[data-team-room-trigger]'));
            if (linkState.expandScreen) {
                window.setTimeout(() => {
                    const screenSection = byId('teamRoomScreenHeading')?.closest('section');
                    screenSection?.scrollIntoView({ block: 'nearest' });
                    byId('startScreenShareBtn')?.focus();
                }, 0);
            }
        }
        if (root.lucide) root.lucide.createIcons();
    }

    root.KasugaiTeamRoom = {
        open: openDrawer,
        close: closeDrawer,
        isOpen: drawerIsOpen,
    };

    if (typeof document !== 'undefined') {
        document.addEventListener('DOMContentLoaded', initializeTeamRoom);
    }
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            activityIndicatorState,
            parseIncomingEvent,
            getScaledDimensions,
            deepLinkState,
        };
    }
})(typeof window !== 'undefined' ? window : globalThis);
