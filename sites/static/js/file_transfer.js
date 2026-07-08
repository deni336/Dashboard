// Shared file-transfer behavior for index.html and screenshare.html.

(function () {
    const state = {
        incoming: new Map(),
        sent: [],
        bound: false,
    };

    function byId(id) {
        return document.getElementById(id);
    }

    function formatFileSize(bytes) {
        const size = Number(bytes) || 0;
        if (size < 1024) return `${size} B`;
        if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
        return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    }

    function setStatus(message, isError) {
        const statusEl = byId('fileSendStatus');
        if (!statusEl) return;
        statusEl.textContent = message || '';
        statusEl.classList.toggle('settings-error', Boolean(isError));
    }

    function setProgress(value, visible) {
        const progress = byId('fileSendProgress');
        if (!progress) return;
        progress.hidden = !visible;
        progress.value = value;
    }

    function normalizeOffer(offer) {
        return {
            fileId: offer.fileId,
            name: offer.name || offer.fileId,
            size: Number(offer.size) || 0,
            mimeType: offer.mimeType || 'application/octet-stream',
            senderId: offer.senderId || '',
            senderName: offer.senderName || 'Unknown',
            recipientId: offer.recipientId || '',
            createdAt: offer.createdAt || '',
            downloaded: Boolean(offer.downloaded),
        };
    }

    function addOffer(offer, options) {
        if (!offer || !offer.fileId) return;
        const normalized = normalizeOffer(offer);
        const current = state.incoming.get(normalized.fileId);
        if (current && current.downloaded) {
            normalized.downloaded = true;
        }
        state.incoming.set(normalized.fileId, normalized);
        renderIncomingFilesList();

        if (!options || options.chatBubble !== false) {
            addFileOfferChatBubble(normalized);
        }
    }

    function renderIncomingFilesList() {
        const list = byId('incomingFilesList');
        if (!list) return;
        list.innerHTML = '';

        const offers = Array.from(state.incoming.values());
        if (offers.length === 0) {
            const empty = document.createElement('li');
            empty.className = 'settings-empty';
            empty.textContent = 'No incoming files yet.';
            list.appendChild(empty);
            return;
        }

        offers.forEach(offer => {
            const item = document.createElement('li');
            item.className = 'settings-list-item';

            const label = document.createElement('span');
            label.className = 'settings-list-label';
            label.textContent = `${offer.name} (${formatFileSize(offer.size)}) from ${offer.senderName}`;

            const downloadBtn = document.createElement('button');
            downloadBtn.type = 'button';
            downloadBtn.className = 'settings-action-btn';
            downloadBtn.textContent = offer.downloaded ? 'Download Again' : 'Download';
            downloadBtn.addEventListener('click', () => downloadFile(offer, downloadBtn));

            item.appendChild(label);
            item.appendChild(downloadBtn);
            list.appendChild(item);
        });
    }

    function renderSentFilesList() {
        const list = byId('sentFilesList');
        if (!list) return;
        list.innerHTML = '';

        if (state.sent.length === 0) {
            const empty = document.createElement('li');
            empty.className = 'settings-empty';
            empty.textContent = 'No files sent yet.';
            list.appendChild(empty);
            return;
        }

        state.sent.forEach(file => {
            const item = document.createElement('li');
            item.className = 'settings-list-item';

            const label = document.createElement('span');
            label.className = 'settings-list-label';
            label.textContent = `${file.name} (${formatFileSize(file.size)})`;

            item.appendChild(label);
            list.appendChild(item);
        });
    }

    function parseDownloadName(response, fallback) {
        const disposition = response.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
        if (!match) return fallback;
        try {
            return decodeURIComponent(match[1]);
        } catch (e) {
            return match[1];
        }
    }

    function triggerBrowserDownload(blob, filename) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    }

    function downloadFile(offer, button) {
        button.disabled = true;
        button.textContent = 'Downloading...';

        fetch(`/api/files/${encodeURIComponent(offer.fileId)}/download`)
            .then(async response => {
                if (!response.ok) {
                    const error = await response.json().catch(() => ({}));
                    throw new Error(error.error || 'Failed to download file.');
                }
                const blob = await response.blob();
                const filename = parseDownloadName(response, offer.name);
                triggerBrowserDownload(blob, filename);
                offer.downloaded = true;
                state.incoming.set(offer.fileId, offer);
                renderIncomingFilesList();
            })
            .catch(error => {
                console.error('Error downloading file:', error);
                alert(error.message || 'Failed to download file.');
            })
            .finally(() => {
                button.disabled = false;
                button.textContent = offer.downloaded ? 'Download Again' : 'Download';
            });
    }

    function addFileOfferChatBubble(offer) {
        const chatMessages = byId('chatMessages');
        if (!chatMessages || byId(`file-offer-${offer.fileId}`)) return;

        const bubble = document.createElement('div');
        bubble.className = 'file-offer';
        bubble.id = `file-offer-${offer.fileId}`;

        const label = document.createElement('span');
        label.className = 'file-offer-label';
        label.textContent = `${offer.senderName} sent you a file: ${offer.name} (${formatFileSize(offer.size)})`;

        const downloadBtn = document.createElement('button');
        downloadBtn.type = 'button';
        downloadBtn.className = 'settings-action-btn';
        downloadBtn.textContent = offer.downloaded ? 'Download Again' : 'Download';
        downloadBtn.addEventListener('click', () => downloadFile(offer, downloadBtn));

        bubble.appendChild(label);
        bubble.appendChild(downloadBtn);
        chatMessages.appendChild(bubble);
    }

    function loadRoomParticipants() {
        const select = byId('fileRecipient');
        if (!select) return Promise.resolve();

        select.innerHTML = '<option value="">Loading room members...</option>';
        return fetch('/api/room/participants')
            .then(response => response.json())
            .then(participants => {
                select.innerHTML = '';
                const placeholder = document.createElement('option');
                placeholder.value = '';
                placeholder.textContent = participants.length
                    ? 'Select a room member...'
                    : 'No other room members available';
                select.appendChild(placeholder);

                participants.forEach(p => {
                    const option = document.createElement('option');
                    option.value = p.id;
                    option.textContent = p.name;
                    select.appendChild(option);
                });
            })
            .catch(error => {
                console.error('Error loading room participants:', error);
                select.innerHTML = '<option value="">Unable to load room members</option>';
            });
    }

    function loadOffers() {
        return fetch('/api/files/offers')
            .then(response => response.json())
            .then(offers => {
                state.incoming.clear();
                offers.forEach(offer => addOffer(offer, { chatBubble: false }));
                renderIncomingFilesList();
            })
            .catch(error => console.error('Error loading file offers:', error));
    }

    function sendFile(event) {
        event.preventDefault();
        setStatus('');

        const recipientId = byId('fileRecipient').value;
        const fileInput = byId('fileToSend');
        if (!recipientId) {
            setStatus('Please choose a recipient.', true);
            return;
        }
        if (!fileInput.files.length) {
            setStatus('Please choose a file.', true);
            return;
        }

        const form = byId('sendFileForm');
        const submitBtn = form.querySelector('button[type="submit"]');
        const file = fileInput.files[0];
        const formData = new FormData();
        formData.append('file', file);
        formData.append('recipient_id', recipientId);

        const request = new XMLHttpRequest();
        request.open('POST', '/api/files/send');
        request.responseType = 'json';

        request.upload.addEventListener('progress', event => {
            if (!event.lengthComputable) return;
            setProgress(Math.round((event.loaded / event.total) * 100), true);
        });

        request.addEventListener('load', () => {
            const data = request.response || {};
            if (request.status < 200 || request.status >= 300) {
                setStatus(data.error || 'Failed to send file.', true);
                return;
            }

            setStatus(`Sent "${data.name}".`, false);
            state.sent.unshift({
                fileId: data.file_id,
                name: data.name,
                size: data.size || file.size,
            });
            renderSentFilesList();
            form.reset();
        });

        request.addEventListener('error', () => {
            setStatus('An error occurred while sending the file.', true);
        });

        request.addEventListener('loadend', () => {
            setProgress(0, false);
            if (submitBtn) submitBtn.disabled = false;
        });

        if (submitBtn) submitBtn.disabled = true;
        setProgress(0, true);
        request.send(formData);
    }

    function bind() {
        if (state.bound) return;
        state.bound = true;

        const form = byId('sendFileForm');
        if (form) {
            form.addEventListener('submit', sendFile);
        }
        renderIncomingFilesList();
        renderSentFilesList();
        loadOffers();
    }

    function openModal() {
        loadRoomParticipants();
        loadOffers();
        renderSentFilesList();
    }

    window.KasugaiFileTransfer = {
        bind,
        openModal,
        addOffer,
        renderIncomingFilesList,
        loadRoomParticipants,
    };

    document.addEventListener('DOMContentLoaded', bind);
})();
