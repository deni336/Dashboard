document.addEventListener('DOMContentLoaded', function () {
    // Update background first
    updateBackgroundImage();

    // Attach event listeners to the dynamic buttons
    document.querySelectorAll('.dynamic-button').forEach(button => {
        button.addEventListener('click', function () {
            const buttonName = this.textContent;
            // Send the button name to the server to handle the click
            fetch(`/button_click/${encodeURIComponent(buttonName)}`, { method: 'POST' })
                .then(response => {
                    if (!response.ok) {
                        console.error('Failed to execute button action:', response.statusText);
                    }
                })
                .catch(error => console.error('Error during button click:', error));
        });
    });
    
    // Attach event listener to Embedded Browser button
    document.getElementById('embeddedBrowserBtn').addEventListener('click', function () {
        embeddedBrowserModal.style.display = "block";
    });

    // Handle loading a URL into the embedded iframe
    document.getElementById('loadUrlBtn').addEventListener('click', function () {
        const iframe = document.getElementById('embeddedIframe');
        const url = document.getElementById('embeddedBrowserUrl').value;

        // Validate URL before loading
        if (url) {
            iframe.src = url.startsWith('http://') || url.startsWith('https://') ? url : `http://${url}`;
        } else {
            alert('Please enter a valid URL.');
        }
    });

    // Close Embedded Browser Modal
    closeBtns.forEach(function (btn) {
        btn.onclick = function () {
            btn.parentElement.parentElement.style.display = "none";
        }
    });
});


// Get the modal for Embedded Browser
const embeddedBrowserModal = document.getElementById("embeddedBrowserModal");

// Get buttons that open the modals
const embeddedBrowserBtn = document.getElementById("embeddedBrowserBtn");

// Functions to open each modal
embeddedBrowserBtn.onclick = function() {
    embeddedBrowserModal.style.display = "block";
}

document.getElementById('backgroundForm').addEventListener('submit', function(event) {
    event.preventDefault();  // Prevent the default form submission

    let formData = new FormData(this);

    // Use Fetch API to send the form data
    fetch('/change_background', {
        method: 'POST',
        body: formData
    })
    .then(response => {
        if (response.ok) {
            // Update the background image after successful upload
            updateBackgroundImage();
        } else {
            alert('Failed to upload background image.');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred while uploading the background image.');
    });
});

function updateBackgroundImage() {
    const imageUrl = `/resources/bg.jpg?${new Date().getTime()}`;
    console.log("Setting background image to:", imageUrl);
    document.body.style.backgroundImage = `url('${imageUrl}')`;
}


// Get modals
const chatModal = document.getElementById("chatModal");
const fileTransferModal = document.getElementById("fileTransferModal");
const settingsModal = document.getElementById("settingsModal");

// Get buttons that open the modals
const chatBtn = document.getElementById("chatBtn");
const fileTransferBtn = document.getElementById("fileTransferBtn");
const screenShareBtn = document.getElementById("screenShareBtn");
const settingsBtn = document.getElementById("settingsBtn");
const homeBtn = document.getElementById("homeBtn");

// Get the <span> element that closes the modal
const closeBtns = document.querySelectorAll(".close");
var closeBtn = document.getElementsByClassName("close")[0];

// Functions to open each modal
chatBtn.onclick = function() {
    chatModal.style.display = "block";
}
// Close the modal when the 'x' is clicked
closeBtn.onclick = function() {
    chatModal.style.display = "none";
}

document.getElementById("sendChat").onclick = function() {
    var message = document.getElementById("chatInput").value;
    if (message.trim() !== "") {
        var chatMessages = document.getElementById("chatMessages");
        var newMessage = document.createElement("p");
        newMessage.textContent = message;
        chatMessages.appendChild(newMessage);

        // Send the message to the Flask route
        fetch('/send_message', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: new URLSearchParams({
                'message': message
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Error:', data.error);
            } else {
                console.log('Success:', data.status);
            }
        })
        .catch((error) => {
            console.error('Error:', error);
        });

        document.getElementById("chatInput").value = ""; // Clear the input
    }
};

// Initialize socket connection (ensure the server address is correct)
var socket = io('http"//127.0.0.1:8000');

// Listen for new messages from the server
socket.on('new_message', function(data) {
    // Display the new message in the chat window
    var chatMessages = document.getElementById("chatMessages");
    var newMessage = document.createElement("p");
    newMessage.textContent = data.sender + ": " + data.content;
    chatMessages.appendChild(newMessage);
});

fileTransferBtn.onclick = function() {
    closeAllModals();
    fileTransferModal.style.display = "block";
}

settingsBtn.onclick = function() {
    closeAllModals();
    settingsModal.style.display = "block";
}

// Function to close all modals
homeBtn.onclick = function() {
    closeAllModals();
}

// Close modals when the close button (x) is clicked
closeBtns.forEach(function(btn) {
    btn.onclick = function() {
        btn.parentElement.parentElement.style.display = "none";
    }
});

// Close all modals
function closeAllModals() {
    chatModal.style.display = "none";
    fileTransferModal.style.display = "none";
    settingsModal.style.display = "none";
}

// Join Room Button Functionality
document.getElementById('joinRoomBtn').addEventListener('click', function() {
    const room = document.getElementById('roomSelect').value;
    if (room) {
        console.log(`Joining room: ${room}`);
        fetch('/join_room', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ room: room })
        })
        .then(response => {
            if (response.ok) {
                console.log(`Successfully joined room: ${room}`);
            } else {
                console.error(`Failed to join room: ${room}`);
            }
        })
        .catch(error => {
            console.error('Error:', error);
        });
    } else {
        console.error('Please select a room to join.');
    }
});

// Create Room Button Functionality
document.getElementById('createRoomBtn').addEventListener('click', function() {
    const roomName = document.getElementById('newRoomName').value;
    const roomPassword = document.getElementById('roomPassword').value;
    if (roomName) {
        console.log(`Creating room: ${roomName} with password: ${roomPassword}`);
        fetch('/create_room', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ roomName: roomName, roomPassword: roomPassword })
        })
        .then(response => {
            if (response.ok) {
                console.log(`Successfully created room: ${roomName}`);
            } else {
                console.error(`Failed to create room: ${roomName}`);
            }
        })
        .catch(error => {
            console.error('Error:', error);
        });
    } else {
        console.error('Please enter a room name.');
    }
});

document.getElementById('logoutBtn').addEventListener('click', function() {
    fetch('/logout', {
        method: 'GET'
    })
    .then(response => {
        if (response.ok) {
            console.log('Logged out successfully.');
            window.location.href = '/'; // Redirect to home or login page
        } else {
            console.error('Failed to log out.');
        }
    })
    .catch(error => {
        console.error('Error:', error);
    });
});
