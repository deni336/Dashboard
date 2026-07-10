// Page-specific behavior for index.html. Settings-modal behavior (buttons,
// application settings, background image) lives in settings.js.

const chatModal = document.getElementById("chatModal");
const fileTransferModal = document.getElementById("fileTransferModal");
const settingsModal = document.getElementById("settingsModal");

const chatBtn = document.getElementById("chatBtn");
const fileTransferBtn = document.getElementById("fileTransferBtn");
const settingsBtn = document.getElementById("settingsBtn");
const homeBtn = document.getElementById("homeBtn");

function closeAllModals() {
    chatModal.style.display = "none";
    fileTransferModal.style.display = "none";
    settingsModal.style.display = "none";
}

chatBtn.onclick = function () {
    closeAllModals();
    chatModal.style.display = "block";
};

fileTransferBtn.onclick = function () {
    closeAllModals();
    fileTransferModal.style.display = "block";
    window.KasugaiFileTransfer.openModal();
};

settingsBtn.onclick = function () {
    closeAllModals();
    settingsModal.style.display = "block";
    loadButtons();
    loadAppSettings();
};

homeBtn.onclick = function () {
    closeAllModals();
};

document.querySelectorAll(".close").forEach(function (btn) {
    btn.onclick = function () {
        const modal = btn.closest(".modal, #chatModal");
        if (modal) {
            modal.style.display = "none";
        }
    };
});

// ---------- Chat ----------

document.getElementById("sendChat").onclick = function () {
    const message = document.getElementById("chatInput").value;
    if (message.trim() !== "") {
        fetch('/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ 'message': message })
        })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    console.error('Error:', data.error);
                } else {
                    console.log('Success:', data.status);
                }
            })
            .catch((error) => console.error('Error:', error));

        document.getElementById("chatInput").value = "";
    }
};

// Waitress can't serve WebSocket upgrades, so stick to long-polling to match the server.
const socket = io({ transports: ['polling'] });

socket.on('new_message', function (data) {
    // File-transfer offers are smuggled through the chat channel as JSON
    // content tagged type:"file_offer" (see ChatManager.send_file_offer).
    // Every room member receives the broadcast; only render it here if it's
    // actually addressed to this user.
    let offer = null;
    try {
        const parsed = JSON.parse(data.content);
        if (parsed && parsed.type === 'file_offer') {
            offer = parsed;
        }
    } catch (e) {
        // Not JSON -- a normal chat message, fall through.
    }

    if (offer) {
        if (offer.recipientId === window.CURRENT_USER_ID) {
            window.KasugaiFileTransfer.addOffer(offer);
        }
        return;
    }

    const chatMessages = document.getElementById("chatMessages");
    const newMessage = document.createElement("p");
    newMessage.textContent = data.sender + ": " + data.content;
    chatMessages.appendChild(newMessage);
});

document.getElementById('joinRoomBtn').addEventListener('click', function () {
    const room = document.getElementById('roomSelect').value;
    if (!room) {
        console.error('Please select a room to join.');
        return;
    }
    fetch('/join_room', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room: room })
    })
        .then(response => {
            if (response.ok) {
                console.log(`Successfully joined room: ${room}`);
            } else {
                console.error(`Failed to join room: ${room}`);
            }
        })
        .catch(error => console.error('Error:', error));
});

document.getElementById('createRoomBtn').addEventListener('click', function () {
    const roomName = document.getElementById('newRoomName').value;
    const roomPassword = document.getElementById('roomPassword').value;
    if (!roomName) {
        console.error('Please enter a room name.');
        return;
    }
    fetch('/create_room', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ roomName: roomName, roomPassword: roomPassword })
    })
        .then(response => {
            if (response.ok) {
                console.log(`Successfully created room: ${roomName}`);
            } else {
                console.error(`Failed to create room: ${roomName}`);
            }
        })
        .catch(error => console.error('Error:', error));
});

// ---------- Logout ----------

document.getElementById('logoutBtn').addEventListener('click', function () {
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
