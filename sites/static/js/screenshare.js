document.addEventListener('DOMContentLoaded', function () {
   // Example placeholder for screen share video functionality
    const video = document.getElementById('screenVideo');
    
    function startScreenShare() {
        const socket = new WebSocket('ws://localhost:8080/screen-share'); // WebSocket to receive frames
        
        socket.onmessage = function(event) {
            const imageBlob = new Blob([event.data], { type: 'image/jpeg' });
            const imageUrl = URL.createObjectURL(imageBlob);
            
            // Display the received frame
            video.src = imageUrl;
        };
        
        socket.onerror = function(error) {
            console.error('WebSocket Error: ', error);
        };
    }
   // Call function to start the screen share
   startScreenShare();
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
