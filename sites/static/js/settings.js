// Shared Settings modal behavior: quick-launch buttons, application settings,
// and background image. Included by both index.html and
// screenshare.html so the Settings modal behaves identically on each page.

document.addEventListener('DOMContentLoaded', function () {
    updateBackgroundImage();
    loadButtons();

    document.querySelectorAll('.settings-tab').forEach(function (tab) {
        tab.addEventListener('click', function () {
            document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.settings-section').forEach(s => s.classList.remove('active'));
            tab.classList.add('active');
            document.querySelector(`.settings-section[data-section="${tab.dataset.tab}"]`).classList.add('active');
        });
    });

    // Event delegation so newly added/removed buttons always work without rebinding
    document.getElementById('buttonContainer').addEventListener('click', function (event) {
        const button = event.target.closest('.dynamic-button');
        if (!button) return;

        fetch(`/button_click/${encodeURIComponent(button.textContent)}`, { method: 'POST' })
            .then(response => {
                if (!response.ok) {
                    console.error('Failed to execute button action:', response.statusText);
                }
            })
            .catch(error => console.error('Error during button click:', error));
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

    document.getElementById('backgroundForm').addEventListener('submit', function (event) {
        event.preventDefault();
        const formData = new FormData(this);

        fetch('/change_background', { method: 'POST', body: formData })
            .then(response => {
                if (response.ok) {
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

});

function updateBackgroundImage() {
    const imageUrl = `/resources/bg.jpg?${new Date().getTime()}`;
    document.body.style.backgroundImage = `url('${imageUrl}')`;
}

function renderButtonContainer(buttons) {
    const container = document.getElementById('buttonContainer');
    container.innerHTML = '';
    buttons.forEach(function (button) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'dynamic-button';
        btn.textContent = button.name;
        container.appendChild(btn);
    });
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
