// Shared Settings modal behavior: quick-launch buttons, application settings,
// and background image. Included by Home and Projects so the selected
// background follows users across the application.

function initializeSettings() {
    updateBackgroundImage().catch(function () {
        // A fresh installation may not have a custom background yet.
        document.body.style.removeProperty('--kasugai-background-image');
    });
    const backgroundForm = document.getElementById('backgroundForm');
    if (!backgroundForm) return;
    loadButtons();

    document.querySelectorAll('.settings-tab').forEach(function (tab) {
        tab.addEventListener('click', function () {
            document.querySelectorAll('.settings-tab').forEach(t => {
                const active = t === tab;
                t.classList.toggle('active', active);
                t.setAttribute('aria-selected', String(active));
            });
            document.querySelectorAll('.settings-section').forEach(s => s.classList.remove('active'));
            document.querySelector(`.settings-section[data-section="${tab.dataset.tab}"]`).classList.add('active');
        });
    });

    // Event delegation so newly added/removed buttons always work without rebinding
    document.getElementById('buttonContainer').addEventListener('click', function (event) {
        const button = event.target.closest('.dynamic-button');
        if (!button) return;
        const link = safeShortcutUrl(button.dataset.shortcutUrl);
        if (link) window.open(link, '_blank', 'noopener,noreferrer');
    });

    document.getElementById('addButtonForm').addEventListener('submit', function (event) {
        event.preventDefault();
        const errorEl = document.getElementById('buttonError');
        errorEl.textContent = '';

        const name = document.getElementById('buttonName').value.trim();
        const link = document.getElementById('buttonLink').value.trim();

        fetch('/api/buttons', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, link })
        })
            .then(response => response.json().then(data => ({ ok: response.ok, data })))
            .then(({ ok, data }) => {
                if (!ok) {
                    errorEl.textContent = data.error || 'Failed to add button.';
                    return;
                }
                renderButtonContainer(data);
                renderButtonList(data);
                document.getElementById('addButtonForm').reset();
            })
            .catch(error => {
                console.error('Error adding button:', error);
                errorEl.textContent = 'An error occurred while adding the button.';
            });
    });

    backgroundForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        const form = this;
        const formData = new FormData(this);
        const submitButton = form.querySelector('button[type="submit"]');
        const status = document.getElementById('backgroundStatus');
        const originalButtonText = submitButton.textContent;
        status.textContent = 'Uploading background...';
        status.className = 'settings-feedback';
        status.setAttribute('role', 'status');
        submitButton.disabled = true;
        submitButton.textContent = 'Uploading...';

        try {
            const response = await fetch('/change_background', {
                method: 'POST',
                headers: { Accept: 'application/json' },
                body: formData,
            });
            const result = await readBackgroundUploadResponse(response);
            await updateBackgroundImage(result.url);
            form.reset();
            status.textContent = 'Background updated.';
            status.classList.add('success');
        } catch (error) {
            console.error('Error updating background:', error);
            status.textContent = error.message || 'An error occurred while uploading the background image.';
            status.classList.add('error');
            status.setAttribute('role', 'alert');
        } finally {
            submitButton.disabled = false;
            submitButton.textContent = originalButtonText;
        }
    });

    document.getElementById('appSettingsForm').addEventListener('submit', function (event) {
        event.preventDefault();
        const savedEl = document.getElementById('appSettingsSaved');
        savedEl.classList.remove('visible');

        const loglevel = document.getElementById('logLevel').value;
        const uploadfolder = document.getElementById('uploadFolder').value.trim();

        fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ loglevel, uploadfolder })
        })
            .then(response => response.json().then(data => ({ ok: response.ok, data })))
            .then(({ ok, data }) => {
                if (!ok) {
                    alert(data.error || 'Failed to save settings.');
                    return;
                }
                document.getElementById('logLevel').value = data.loglevel;
                document.getElementById('uploadFolder').value = data.uploadfolder;
                savedEl.classList.add('visible');
                setTimeout(() => savedEl.classList.remove('visible'), 2000);
            })
            .catch(error => {
                console.error('Error saving settings:', error);
                alert('An error occurred while saving settings.');
            });
    });

}

async function readBackgroundUploadResponse(response) {
    if (response.redirected) {
        throw new Error('Your session expired. Sign in again before changing the background.');
    }
    let result;
    try {
        result = await response.json();
    } catch (_error) {
        throw new Error('Kasugai returned an invalid background upload response.');
    }
    if (!response.ok) {
        throw new Error(result.error || 'Failed to upload the background image.');
    }
    if (!result.ok || typeof result.url !== 'string' || !result.url) {
        throw new Error('Kasugai returned an incomplete background upload response.');
    }
    return result;
}

function updateBackgroundImage(backgroundUrl = '/resources/background') {
    const imageUrl = new URL(backgroundUrl, window.location.origin);
    imageUrl.searchParams.set('v', Date.now().toString());

    return new Promise(function (resolve, reject) {
        const image = new Image();
        image.onload = function () {
            document.body.style.setProperty(
                '--kasugai-background-image',
                `url('${imageUrl.href}')`,
            );
            resolve(imageUrl.href);
        };
        image.onerror = function () {
            reject(new Error('The uploaded image could not be loaded.'));
        };
        image.src = imageUrl.href;
    });
}

function renderButtonContainer(buttons) {
    const container = document.getElementById('buttonContainer');
    container.innerHTML = '';
    if (buttons.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'home-empty-copy';
        empty.textContent = 'Add the tools and links you reach for every day.';
        container.appendChild(empty);
        return;
    }
    buttons.forEach(function (button) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'dynamic-button';
        const safeLink = safeShortcutUrl(button.link);
        btn.dataset.shortcutUrl = safeLink;
        btn.disabled = !safeLink;
        const icon = document.createElement('i');
        icon.setAttribute('data-lucide', 'arrow-up-right');
        const label = document.createElement('span');
        label.textContent = button.name;
        btn.append(icon, label);
        container.appendChild(btn);
    });
    if (typeof window !== 'undefined' && window.lucide) window.lucide.createIcons();
}

function safeShortcutUrl(value) {
    try {
        const url = new URL(String(value || ''));
        if (url.protocol !== 'https:' || url.username || url.password) return '';
        return url.href;
    } catch (_error) {
        return '';
    }
}

function renderButtonList(buttons) {
    const list = document.getElementById('buttonList');
    list.innerHTML = '';

    if (buttons.length === 0) {
        const empty = document.createElement('li');
        empty.className = 'settings-empty';
        empty.textContent = 'No buttons yet.';
        list.appendChild(empty);
        return;
    }

    buttons.forEach(function (button) {
        const item = document.createElement('li');
        item.className = 'settings-list-item';

        const label = document.createElement('span');
        label.className = 'settings-list-label';
        const name = document.createElement('strong');
        name.textContent = button.name;
        label.appendChild(name);
        label.appendChild(document.createTextNode(` - ${button.link}`));

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'settings-remove-btn';
        removeBtn.textContent = 'Remove';
        removeBtn.title = `Remove ${button.name}`;
        removeBtn.addEventListener('click', function () {
            if (confirm(`Remove the "${button.name}" button?`)) {
                removeButton(button.name);
            }
        });

        item.appendChild(label);
        item.appendChild(removeBtn);
        list.appendChild(item);
    });
}

function loadButtons() {
    fetch('/api/buttons')
        .then(response => response.json())
        .then(buttons => {
            renderButtonContainer(buttons);
            renderButtonList(buttons);
        })
        .catch(error => console.error('Error loading buttons:', error));
}

function removeButton(name) {
    fetch(`/api/buttons/${encodeURIComponent(name)}`, { method: 'DELETE' })
        .then(response => response.json())
        .then(buttons => {
            renderButtonContainer(buttons);
            renderButtonList(buttons);
        })
        .catch(error => console.error('Error removing button:', error));
}

function loadAppSettings() {
    fetch('/api/settings')
        .then(response => response.json())
        .then(settings => {
            document.getElementById('logLevel').value = settings.loglevel;
            document.getElementById('uploadFolder').value = settings.uploadfolder;
        })
        .catch(error => console.error('Error loading settings:', error));
}

if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', initializeSettings);
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        initializeSettings,
        readBackgroundUploadResponse,
        updateBackgroundImage,
        safeShortcutUrl,
    };
}
