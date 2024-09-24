// Get modals
const chatModal = document.getElementById("chatModal");
const fileTransferModal = document.getElementById("fileTransferModal");
const screenShareModal = document.getElementById("screenShareModal");
const settingsModal = document.getElementById("settingsModal");

// Get buttons that open the modals
const chatBtn = document.getElementById("chatBtn");
const fileTransferBtn = document.getElementById("fileTransferBtn");
const screenShareBtn = document.getElementById("screenShareBtn");
const settingsBtn = document.getElementById("settingsBtn");
const homeBtn = document.getElementById("homeBtn");

// Get the <span> element that closes the modal
const closeBtns = document.querySelectorAll(".close");

// Functions to open each modal
chatBtn.onclick = function() {
    closeAllModals();
    chatModal.style.display = "block";
}

fileTransferBtn.onclick = function() {
    closeAllModals();
    fileTransferModal.style.display = "block";
}

screenShareBtn.onclick = function() {
    closeAllModals();
    screenShareModal.style.display = "block";
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
    screenShareModal.style.display = "none";
    settingsModal.style.display = "none";
}

// Close modals if user clicks outside of the modal content
window.onclick = function(event) {
    if (event.target.classList.contains('modal')) {
        closeAllModals();
    }
}
