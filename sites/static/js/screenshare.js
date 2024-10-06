document.addEventListener('DOMContentLoaded', () => {
    const startScreenShareBtn = document.getElementById('startScreenShareBtn');
    const stopScreenShareBtn = document.getElementById('stopScreenShareBtn');
    const screenVideo = document.getElementById('screenVideo');
    const viewersList = document.getElementById('viewersList');
    const broadcastsList = document.getElementById('broadcastsList');
    const watchBroadcastBtn = document.getElementById('watchBroadcastBtn');

    let screenStream = null;

    // Start screen sharing
    startScreenShareBtn.addEventListener('click', async () => {
        try {
            screenStream = await navigator.mediaDevices.getDisplayMedia({
                video: {
                    cursor: "always"
                },
                audio: false
            });
            screenVideo.srcObject = screenStream;

            // Enable Stop button and disable Start button
            startScreenShareBtn.disabled = true;
            stopScreenShareBtn.disabled = false;

            // Notify viewers about the screen share (backend implementation required)
            notifyViewersAboutScreenShare();
        } catch (err) {
            console.error("Error: " + err);
        }
    });

    // Stop screen sharing
    stopScreenShareBtn.addEventListener('click', () => {
        if (screenStream) {
            let tracks = screenStream.getTracks();
            tracks.forEach(track => track.stop());
            screenStream = null;
        }

        // Reset video
        screenVideo.srcObject = null;

        // Enable Start button and disable Stop button
        startScreenShareBtn.disabled = false;
        stopScreenShareBtn.disabled = true;

        // Notify viewers that screenshare has stopped
        notifyViewersScreenshareStopped();
    });

    // Watch a selected broadcast
    watchBroadcastBtn.addEventListener('click', () => {
        const selectedBroadcast = broadcastsList.querySelector('li.selected');
        if (selectedBroadcast) {
            const streamId = selectedBroadcast.dataset.streamId;
            watchBroadcastStream(streamId); // Function to watch a broadcast
        }
    });

    // Function to notify viewers about the screen share
    function notifyViewersAboutScreenShare() {
        // You would need to implement backend communication here
        console.log("Notifying viewers about screen share...");
        // E.g., make an API call to update viewers or a WebSocket implementation
    }

    // Function to notify viewers that the screenshare stopped
    function notifyViewersScreenshareStopped() {
        console.log("Notifying viewers that screenshare has stopped...");
    }

    // Function to watch a broadcasted stream
    function watchBroadcastStream(streamId) {
        console.log("Watching broadcast with stream ID: " + streamId);
        // Here you would implement logic to retrieve the selected stream and play it
    }
});


document.addEventListener('DOMContentLoaded', function () {
   // Add event listeners to all dynamically loaded buttons
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
});

// Function to populate buttons with only names (no links)
function populateButtons(buttonNames) {
   const container = document.getElementById('buttonContainer');
   container.innerHTML = '';  // Clear existing buttons

   buttonNames.forEach(buttonName => {
       const buttonElement = document.createElement('button');
       buttonElement.textContent = buttonName;
       buttonElement.onclick = function () {
           // Handle button click by sending the name to the server to resolve the link
           fetch(`/button_click/${buttonName}`, { method: 'POST' })
               .then(response => {
                   if (!response.ok) {
                       console.error('Failed to execute button action:', response.statusText);
                   }
               })
               .catch(error => console.error('Error during button click:', error));
       };
       container.appendChild(buttonElement);
   });
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
   // Force reload the background image by updating the URL with a timestamp to avoid caching
   document.body.style.backgroundImage = `url('/static/img/bg.jpg?${new Date().getTime()}')`;
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

// Send a chat message
document.getElementById("sendChat").onclick = function() {
   var message = document.getElementById("chatInput").value;
   if (message.trim() !== "") {
       var chatMessages = document.getElementById("chatMessages");
       var newMessage = document.createElement("p");
       newMessage.textContent = message;
       chatMessages.appendChild(newMessage);
       document.getElementById("chatInput").value = ""; // Clear the input
   }
}

fileTransferBtn.onclick = function() {
   fileTransferModal.style.display = "block";
}

settingsBtn.onclick = function() {
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

// Logout Button Functionality
document.getElementById('logoutBtn').addEventListener('click', function() {
    fetch('/logout', {
        method: 'POST'
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
