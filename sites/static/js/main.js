// Home shell behavior. Collaboration lives in team_room.js and appearance /
// shortcut persistence lives in settings.js.

(function () {
    'use strict';

    let settingsReturnFocus = null;

    function byId(id) {
        return document.getElementById(id);
    }

    function selectSettingsSection(name) {
        const requested = document.querySelector(`.settings-tab[data-tab="${name}"]`)
            || document.querySelector('.settings-tab');
        if (!requested) return;
        document.querySelectorAll('.settings-tab').forEach(tab => {
            const active = tab === requested;
            tab.classList.toggle('active', active);
            tab.setAttribute('aria-selected', String(active));
        });
        document.querySelectorAll('.settings-section').forEach(section => {
            section.classList.toggle('active', section.dataset.section === requested.dataset.tab);
        });
    }

    function openSettings(section, opener) {
        const modal = byId('settingsModal');
        if (!modal) return;
        window.KasugaiTeamRoom?.close({ restoreFocus: false });
        settingsReturnFocus = opener && opener.focus ? opener : document.activeElement;
        selectSettingsSection(section || 'buttons');
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        void modal.offsetWidth;
        modal.classList.add('is-open');
        byId('settingsBtn')?.setAttribute('aria-expanded', 'true');
        loadButtons();
        loadAppSettings();
        window.setTimeout(() => modal.querySelector('.close')?.focus(), 0);
    }

    function closeSettings(options) {
        const modal = byId('settingsModal');
        if (!modal || modal.hidden) return;
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
        byId('settingsBtn')?.setAttribute('aria-expanded', 'false');
        window.setTimeout(() => {
            if (!modal.classList.contains('is-open')) modal.hidden = true;
        }, 180);
        if (!options || options.restoreFocus !== false) settingsReturnFocus?.focus?.();
    }

    function initializeHomeShell() {
        const settingsButton = byId('settingsBtn');
        settingsButton?.addEventListener('click', () => openSettings('buttons', settingsButton));
        document.querySelectorAll('[data-open-settings]').forEach(button => {
            button.addEventListener('click', () => openSettings(button.dataset.openSettings, button));
        });
        byId('settingsModal')?.querySelector('.close')?.addEventListener('click', () => closeSettings());
        byId('settingsModal')?.addEventListener('click', event => {
            if (event.target === event.currentTarget) closeSettings();
        });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && byId('settingsModal')?.classList.contains('is-open')) {
                closeSettings();
            }
        });
        if (window.lucide) window.lucide.createIcons();
    }

    document.addEventListener('DOMContentLoaded', initializeHomeShell);
    window.KasugaiSettingsModal = { open: openSettings, close: closeSettings };
})();
