// Screen sharing is implemented as low-rate JPEG frame relay through the
// existing Flask and gRPC media path. Waitress only supports Socket.IO polling
// here, so this intentionally avoids WebRTC signaling assumptions.

document.addEventListener('DOMContentLoaded', () => {
    const startScreenShareBtn = document.getElementById('startScreenShareBtn');
    const stopScreenShareBtn = document.getElementById('stopScreenShareBtn');
    const screenVideo = document.getElementById('screenVideo');
    const remoteScreenView = document.getElementById('remoteScreenView');
    const screenShareStatus = document.getElementById('screenShareStatus');
    const captureCanvas = document.createElement('canvas');

    const FRAME_INTERVAL_MS = 500;
    const JPEG_QUALITY = 0.55;
    const MAX_FRAME_WIDTH = 1280;
    const MAX_FRAME_HEIGHT = 720;

    let screenStream = null;
    let captureIntervalId = null;
    let frameInFlight = false;

    function setStatus(message) {
        screenShareStatus.textContent = message;
    }

    function setSharingControls(isSharing) {
        startScreenShareBtn.disabled = isSharing;
        stopScreenShareBtn.disabled = !isSharing;
    }

    function getScaledDimensions(width, height) {
        const scale = Math.min(1, MAX_FRAME_WIDTH / width, MAX_FRAME_HEIGHT / height);
        return {
            width: Math.max(1, Math.round(width * scale)),
            height: Math.max(1, Math.round(height * scale)),
        };
    }

    function canvasToJpegBlob(canvas) {
        return new Promise(resolve => {
            canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY);
        });
    }

    async function captureAndSendFrame() {
        if (frameInFlight || !screenStream || !screenVideo.videoWidth || !screenVideo.videoHeight) {
            return;
        }

        frameInFlight = true;
        try {
            const size = getScaledDimensions(screenVideo.videoWidth, screenVideo.videoHeight);
            captureCanvas.width = size.width;
            captureCanvas.height = size.height;

            const ctx = captureCanvas.getContext('2d', { alpha: false });
            ctx.drawImage(screenVideo, 0, 0, size.width, size.height);

            const blob = await canvasToJpegBlob(captureCanvas);
            if (!blob || !screenStream) {
                return;
            }

            const response = await fetch('/api/screenshare/frame', {
                method: 'POST',
                headers: { 'Content-Type': 'image/jpeg' },
                body: blob,
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                console.error('Failed to send screen frame:', error.error || response.statusText);
            }
        } catch (error) {
            console.error('Error sending screen frame:', error);
        } finally {
            frameInFlight = false;
        }
    }

    async function stopSharing() {
        if (captureIntervalId) {
            clearInterval(captureIntervalId);
            captureIntervalId = null;
        }

        if (screenStream) {
            screenStream.getTracks().forEach(track => track.stop());
            screenStream = null;
        }

        screenVideo.srcObject = null;
        setSharingControls(false);
        setStatus(remoteScreenView.style.display === 'block'
            ? 'Someone is sharing their screen.'
            : 'No one is sharing right now.');

        try {
            await fetch('/api/screenshare/stop', { method: 'POST' });
        } catch (error) {
            console.error('Error stopping screen share:', error);
        }
    }

    startScreenShareBtn.addEventListener('click', async () => {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
            setStatus('Screen capture is not supported by this browser.');
            return;
        }

        try {
            screenStream = await navigator.mediaDevices.getDisplayMedia({
                video: {
                    cursor: 'always',
                    frameRate: { ideal: 5, max: 8 },
                },
                audio: false,
            });

            screenVideo.srcObject = screenStream;
            await screenVideo.play().catch(() => {});

            setSharingControls(true);
            setStatus('Sharing your screen.');
            captureAndSendFrame();
            captureIntervalId = setInterval(captureAndSendFrame, FRAME_INTERVAL_MS);

            const [track] = screenStream.getVideoTracks();
            if (track) {
                track.addEventListener('ended', stopSharing, { once: true });
            }
        } catch (error) {
            if (error.name !== 'NotAllowedError') {
                console.error('Error starting screen share:', error);
            }
            setSharingControls(false);
        }
    });

    stopScreenShareBtn.addEventListener('click', stopSharing);

    const socket = io({ transports: ['polling'] });

    socket.on('screen_frame', data => {
        if (data.sender === window.CURRENT_USER_ID) {
            return;
        }
        remoteScreenView.src = `data:image/jpeg;base64,${data.data}`;
        remoteScreenView.style.display = 'block';
        setStatus('Someone is sharing their screen.');
    });

    socket.on('screen_share_stopped', data => {
        if (data && data.sender === window.CURRENT_USER_ID) {
            return;
        }
        remoteScreenView.style.display = 'none';
        remoteScreenView.src = '';
        if (!screenStream) {
            setStatus('No one is sharing right now.');
        }
    });

    socket.on('new_message', data => {
        let offer = null;
        try {
            const parsed = JSON.parse(data.content);
            if (parsed && parsed.type === 'file_offer') {
                offer = parsed;
            }
        } catch (e) {
            // Normal chat message.
        }

        if (offer) {
            if (offer.recipientId === window.CURRENT_USER_ID) {
                window.KasugaiFileTransfer.addOffer(offer);
            }
            return;
        }

        const chatMessages = document.getElementById('chatMessages');
        const newMessage = document.createElement('p');
        newMessage.textContent = `${data.sender}: ${data.content}`;
        chatMessages.appendChild(newMessage);
    });

    wireModalNavigation();
    wireChatControls();
    wireLogout();
});

function wireModalNavigation() {
    const chatModal = document.getElementById('chatModal');
    const fileTransferModal = document.getElementById('fileTransferModal');
    const settingsModal = document.getElementById('settingsModal');

    function closeAllModals() {
        chatModal.style.display = 'none';
        fileTransferModal.style.display = 'none';
        settingsModal.style.display = 'none';
    }

    document.getElementById('chatBtn').addEventListener('click', event => {
        event.preventDefault();
        closeAllModals();
        chatModal.style.display = 'block';
    });

    document.getElementById('fileTransferBtn').addEventListener('click', event => {
        event.preventDefault();
        closeAllModals();
        fileTransferModal.style.display = 'block';
        window.KasugaiFileTransfer.openModal();
    });

    document.getElementById('settingsBtn').addEventListener('click', event => {
        event.preventDefault();
        closeAllModals();
        settingsModal.style.display = 'block';
        loadButtons();
        loadAppSettings();
    });

    document.getElementById('homeBtn').addEventListener('click', () => {
        closeAllModals();
    });

    document.querySelectorAll('.close').forEach(btn => {
        btn.addEventListener('click', () => {
            const modal = btn.closest('.modal, #chatModal');
            if (modal) {
                modal.style.display = 'none';
            }
        });
    });
}

function wireChatControls() {
    document.getElementById('sendChat').addEventListener('click', () => {
        const chatInput = document.getElementById('chatInput');
        const message = chatInput.value.trim();
        if (!message) {
            return;
        }

        fetch('/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ message }),
        })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    console.error('Error:', data.error);
                }
            })
            .catch(error => console.error('Error:', error));

        chatInput.value = '';
    });

    document.getElementById('joinRoomBtn').addEventListener('click', () => {
        const room = document.getElementById('roomSelect').value;
        if (!room) {
            console.error('Please select a room to join.');
            return;
        }

        fetch('/join_room', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ room }),
        })
            .then(response => {
                if (!response.ok) {
                    console.error(`Failed to join room: ${room}`);
                }
            })
            .catch(error => console.error('Error:', error));
    });

    document.getElementById('createRoomBtn').addEventListener('click', () => {
        const roomName = document.getElementById('newRoomName').value.trim();
        const roomPassword = document.getElementById('roomPassword').value;
        if (!roomName) {
            console.error('Please enter a room name.');
            return;
        }

        fetch('/create_room', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ roomName, roomPassword }),
        })
            .then(response => {
                if (!response.ok) {
                    console.error(`Failed to create room: ${roomName}`);
                }
            })
            .catch(error => console.error('Error:', error));
    });
}

function wireLogout() {
    document.getElementById('logoutBtn').addEventListener('click', event => {
        event.preventDefault();
        fetch('/logout', { method: 'GET' })
            .then(response => {
                if (response.ok) {
                    window.location.href = '/';
                } else {
                    console.error('Failed to log out.');
                }
            })
            .catch(error => console.error('Error:', error));
    });
}
