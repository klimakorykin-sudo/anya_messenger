// chat.js — список + личка + группа + канал + ЧС + фон + выход/кик/переименование
(function () {
    const layout = document.querySelector('.layout');
    if (!layout) return;

    const meId = parseInt(layout.dataset.meId, 10);
    const chatContainer = document.getElementById('chat-container');
    const emptyState = document.getElementById('empty-state');

    let currentWs = null;
    let currentChatId = null;

    // ============ ВКЛАДКИ ============
    const tabs = document.querySelectorAll('.tab');
    const tabChats = document.getElementById('tab-chats');
    const tabUsers = document.getElementById('tab-users');
    let usersLoaded = false;

    tabs.forEach(t => {
        t.addEventListener('click', async () => {
            tabs.forEach(x => x.classList.remove('active'));
            t.classList.add('active');
            if (t.dataset.tab === 'chats') {
                tabChats.classList.remove('hidden');
                tabUsers.classList.add('hidden');
            } else {
                tabChats.classList.add('hidden');
                tabUsers.classList.remove('hidden');
                if (!usersLoaded) await loadUsers();
            }
        });
    });

    async function loadUsers() {
        try {
            const r = await fetch('/api/users');
            const users = await r.json();
            tabUsers.innerHTML = '';
            if (!users.length) {
                tabUsers.innerHTML = '<li class="empty-hint">Пока никого нет</li>';
                return;
            }
            for (const u of users) {
                const li = document.createElement('li');
                const a = document.createElement('a');
                a.href = '#';
                a.className = 'chat-link';
                a.dataset.otherId = u.id;

                if (u.avatar) {
                    const img = document.createElement('img');
                    img.src = `/static/avatars/${u.avatar}`;
                    img.className = 'avatar-img avatar-img-sm';
                    a.appendChild(img);
                } else {
                    const s = document.createElement('span');
                    s.className = 'avatar';
                    s.textContent = (u.username[0] || '?').toUpperCase();
                    a.appendChild(s);
                }

                const nameEl = document.createElement('span');
                nameEl.className = 'item-name';
                nameEl.textContent = u.username;
                if (u.is_superadmin) {
                    const star = document.createElement('span');
                    star.className = 'star';
                    star.textContent = ' ⭐';
                    nameEl.appendChild(star);
                }
                a.appendChild(nameEl);

                const mailEl = document.createElement('span');
                mailEl.className = 'last-msg';
                mailEl.textContent = u.email;
                a.appendChild(mailEl);

                li.appendChild(a);
                tabUsers.appendChild(li);
            }
            bindChatLinks();
            usersLoaded = true;
        } catch (e) { console.error(e); }
    }

    // ============ ПОИСК ============
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            const q = searchInput.value.trim().toLowerCase();
            document.querySelectorAll('.sidebar-list li').forEach(li => {
                if (li.classList.contains('empty-hint')) return;
                li.style.display = li.textContent.toLowerCase().includes(q) ? '' : 'none';
            });
        });
    }

    // ============ ССЫЛКИ ============
    function bindChatLinks() {
        document.querySelectorAll('.chat-link').forEach(a => {
            a.onclick = (e) => {
                e.preventDefault();
                if (a.dataset.chatId) openGroup(a.dataset.chatId, true);
                else openChat(a.dataset.otherId, true);
            };
        });
    }
    bindChatLinks();

    // ============ ЛИЧКА ============
    async function openChat(otherId, pushUrl) {
        closeWs();
        try {
            const r = await fetch(`/chat/${otherId}/partial`);
            if (!r.ok) { alert('Ошибка: ' + await r.text()); return; }
            const html = await r.text();
            chatContainer.innerHTML = html;
            emptyState.style.display = 'none';
            document.body.classList.add('mobile-chat-open');
            const root = chatContainer.querySelector('.chat-window');
            currentChatId = root.dataset.chatId;
            if (pushUrl) history.pushState({ otherId }, '', `/chat/${otherId}`);
            initChat(root);
        } catch (e) { alert('Ошибка сети: ' + e.message); }
    }

    // ============ ГРУППА / КАНАЛ ============
    async function openGroup(chatId, pushUrl) {
        closeWs();
        try {
            const r = await fetch(`/group/${chatId}/partial`);
            if (!r.ok) { alert('Ошибка: ' + await r.text()); return; }
            const html = await r.text();
            chatContainer.innerHTML = html;
            emptyState.style.display = 'none';
            document.body.classList.add('mobile-chat-open');
            const root = chatContainer.querySelector('.chat-window');
            currentChatId = root.dataset.chatId;
            if (pushUrl) history.pushState({ groupId: chatId }, '', `/group/${chatId}`);
            initChat(root);
        } catch (e) { alert('Ошибка сети: ' + e.message); }
    }

    // ============ ЗАКРЫТИЕ ============
    function closeChat(pushUrl) {
        closeWs();
        chatContainer.innerHTML = '';
        emptyState.style.display = '';
        document.body.classList.remove('mobile-chat-open');
        currentChatId = null;
        if (pushUrl) history.pushState({}, '', '/');
    }
    function closeWs() {
        if (currentWs) { try { currentWs.close(); } catch (e) {} currentWs = null; }
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && currentChatId) closeChat(true);
    });
    document.addEventListener('click', (e) => {
        if (e.target.id === 'back-btn') closeChat(true);
    });
    window.addEventListener('popstate', (e) => {
        if (e.state && e.state.otherId) openChat(e.state.otherId, false);
        else if (e.state && e.state.groupId) openGroup(e.state.groupId, false);
        else closeChat(false);
    });

    // ============ ИНИЦИАЛИЗАЦИЯ ============
    function initChat(root) {
        const chatId = root.dataset.chatId;
        const chatType = root.dataset.chatType;
        let currentBg = root.dataset.bg || '';
        let isBlocked = root.dataset.blocked === '1';
        const otherIsSuperadmin = root.dataset.otherSuperadmin === '1';

        const messagesEl = root.querySelector('#messages');
        const formEl = root.querySelector('#chat-form');
        const inputEl = root.querySelector('#msg-input');
        const statusEl = root.querySelector('#status');
        const blockBtn = root.querySelector('#block-btn');
        const banner = root.querySelector('#blocked-banner');
        const leaveBtn = root.querySelector('#leave-btn');
        const renameBtn = root.querySelector('#rename-btn');

        if (!messagesEl || !formEl || !inputEl) return;

        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(`${proto}://${location.host}/ws/chat/${chatId}`);
        currentWs = ws;

        ws.addEventListener('open', () => { if (statusEl) statusEl.textContent = 'онлайн'; inputEl.focus(); });
        ws.addEventListener('close', () => { if (statusEl) statusEl.textContent = 'не в сети'; });
        ws.addEventListener('message', (ev) => {
            const data = JSON.parse(ev.data);
            if (data.type === 'message') renderMessage(messagesEl, data);
            else if (data.type === 'presence' && statusEl) {
                statusEl.textContent = data.online ? 'онлайн' : 'не в сети';
            } else if (data.type === 'background') {
                applyBackground(messagesEl, data.background);
                root.dataset.bg = data.background || '';
            } else if (data.type === 'blocked_changed') {
                isBlocked = data.blocked;
                root.dataset.blocked = data.blocked ? '1' : '0';
                applyBlockedUI(isBlocked, formEl, banner, blockBtn);
            } else if (data.type === 'kicked') {
                alert('Тебя удалили из чата');
                location.href = '/';
            } else if (data.type === 'renamed') {
                const t = root.querySelector('#chat-title');
                if (t) t.textContent = data.name;
            } else if (data.type === 'error') {
                alert(data.text);
            }
        });

        formEl.addEventListener('submit', (e) => {
            e.preventDefault();
            const text = inputEl.value.trim();
            if (!text) return;
            if (ws.readyState !== WebSocket.OPEN) { alert('Нет связи'); return; }
            ws.send(JSON.stringify({ text }));
            inputEl.value = '';
        });

        if (blockBtn && !otherIsSuperadmin) {
            blockBtn.addEventListener('click', () => {
                if (isBlocked) {
                    if (!confirm('Разблокировать?')) return;
                    ws.send(JSON.stringify({ type: 'unblock' }));
                } else {
                    if (!confirm('Заблокировать?')) return;
                    ws.send(JSON.stringify({ type: 'block' }));
                }
            });
        }

        // ---- Выход из группы ----
        if (leaveBtn) {
            leaveBtn.addEventListener('click', () => {
                if (!confirm('Выйти из чата? Ты больше не увидишь его в списке.')) return;
                const f = document.getElementById('leave-form');
                f.action = `/group/${chatId}/leave`;
                f.submit();
            });
        }

        // ---- Переименование ----
        const renameModal = document.getElementById('rename-modal');
        const renameForm = document.getElementById('rename-form');
        const renameInput = document.getElementById('rename-input');
        const renameClose = document.getElementById('rename-close');
        if (renameBtn && renameModal) {
            renameBtn.addEventListener('click', () => {
                const titleEl = root.querySelector('#chat-title');
                if (titleEl) renameInput.value = titleEl.textContent;
                renameModal.classList.add('open');
                renameInput.focus();
            });
            if (renameClose) {
                renameClose.addEventListener('click', () => renameModal.classList.remove('open'));
            }
            renameModal.addEventListener('click', (e) => {
                if (e.target === renameModal) renameModal.classList.remove('open');
            });
            renameForm.addEventListener('submit', (e) => {
                e.preventDefault();
                renameForm.action = `/group/${chatId}/rename`;
                renameForm.submit();
            });
        }

        // ---- Модалка участников ----
        const membersBtn = root.querySelector('#members-btn');
        const membersModal = document.getElementById('members-modal');
        const membersClose = document.getElementById('members-close');
        if (membersBtn && membersModal) {
            membersBtn.addEventListener('click', () => membersModal.classList.add('open'));
            if (membersClose) membersClose.addEventListener('click', () => membersModal.classList.remove('open'));
            membersModal.addEventListener('click', (e) => {
                if (e.target === membersModal) membersModal.classList.remove('open');
            });
        }

        // ---- Кик ---- (⚠️ ищем в document, модалка снаружи .chat-window)
        document.querySelectorAll('.kick-btn').forEach(btn => {
            btn.onclick = () => {
                const uid = btn.dataset.userId;
                if (!confirm('Кикнуть участника?')) return;
                const f = document.createElement('form');
                f.method = 'post';
                f.action = `/group/${chatId}/kick/${uid}`;
                document.body.appendChild(f);
                f.submit();
            };
        });

        // ---- Повышение до админа ---- (⚠️ тоже в document)
        document.querySelectorAll('.promote-btn').forEach(btn => {
            btn.onclick = () => {
                const uid = btn.dataset.userId;
                if (!confirm('Сделать админом?')) return;
                const f = document.createElement('form');
                f.method = 'post';
                f.action = `/group/${chatId}/promote/${uid}`;
                document.body.appendChild(f);
                f.submit();
            };
        });

        // ---- Фон ----
        const modal = document.getElementById('bg-modal');
        const bgBtn = root.querySelector('#bg-btn');
        const bgClose = document.getElementById('bg-close');
        const bgClear = document.getElementById('bg-clear');
        const bgUpload = document.getElementById('bg-upload');
        const bgFile = document.getElementById('bg-file');

        applyBackground(messagesEl, currentBg);
        applyBlockedUI(isBlocked, formEl, banner, blockBtn);

        if (bgBtn && modal) bgBtn.addEventListener('click', () => modal.classList.add('open'));
        if (bgClose && modal) bgClose.addEventListener('click', () => modal.classList.remove('open'));
        if (modal) modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.classList.remove('open');
        });

        document.querySelectorAll('.bg-swatch').forEach(sw => {
            sw.addEventListener('click', () => sendBackground(chatId, sw.dataset.bg, messagesEl, root, modal));
        });
        if (bgClear) bgClear.addEventListener('click', () => sendBackground(chatId, '', messagesEl, root, modal));
        if (bgUpload && bgFile) {
            bgUpload.addEventListener('click', async () => {
                const f = bgFile.files[0];
                if (!f) { alert('Выбери файл'); return; }
                const fd = new FormData(); fd.append('file', f);
                bgUpload.disabled = true;
                try {
                    const resp = await fetch(`/chat/${chatId}/background/upload`, { method: 'POST', body: fd });
                    if (!resp.ok) { alert((await resp.json()).detail); return; }
                    const data = await resp.json();
                    applyBackground(messagesEl, data.background);
                    root.dataset.bg = data.background || '';
                    bgFile.value = '';
                    if (modal) modal.classList.remove('open');
                } catch (e) { alert(e.message); }
                finally { bgUpload.disabled = false; }
            });
        }

        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function applyBlockedUI(isBlocked, formEl, banner, blockBtn) {
        if (formEl) formEl.classList.toggle('hidden', isBlocked);
        if (banner) banner.classList.toggle('hidden', !isBlocked);
        if (blockBtn) blockBtn.textContent = isBlocked ? '✅' : '🚫';
    }

    function renderMessage(messagesEl, data) {
        const mine = data.author_id === meId;
        const div = document.createElement('div');
        div.className = 'msg ' + (mine ? 'mine' : 'theirs');
        div.appendChild(document.createTextNode(data.text));
        const meta = document.createElement('span');
        meta.className = 'meta';
        meta.textContent = `${data.author} · ${formatTime(data.created_at)}`;
        div.appendChild(meta);
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }
    function formatTime(iso) {
        const d = new Date(iso);
        return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    }

    const ALL_BG = ['bg-rose','bg-peach','bg-lavender','bg-mint','bg-sky',
                    'bg-sunset','bg-candy','bg-lemon','bg-bubble','bg-night'];

    function applyBackground(messagesEl, bg) {
        ALL_BG.forEach(c => messagesEl.classList.remove(c));
        messagesEl.style.backgroundImage = '';
        if (!bg) {}
        else if (bg.startsWith('custom:')) {
            messagesEl.style.backgroundImage = `url('/static/backgrounds/${bg.slice(7)}')`;
            messagesEl.style.backgroundSize = 'contain';
            messagesEl.style.backgroundRepeat = 'no-repeat';
            messagesEl.style.backgroundPosition = 'center';
        } else {
            messagesEl.classList.add(bg);
        }
        document.querySelectorAll('.bg-swatch').forEach(s => {
            s.classList.toggle('selected', s.dataset.bg === bg);
        });
    }

    async function sendBackground(chatId, bg, messagesEl, root, modal) {
        try {
            const resp = await fetch(`/chat/${chatId}/background`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ background: bg }),
            });
            if (!resp.ok) { alert((await resp.json()).detail); return; }
            applyBackground(messagesEl, bg);
            root.dataset.bg = bg || '';
            if (modal) modal.classList.remove('open');
        } catch (e) { alert(e.message); }
    }

    const initialChat = layout.dataset.initialChat;
    const initialGroup = layout.dataset.initialGroup;
    if (initialChat) openChat(initialChat, false);
    else if (initialGroup) openGroup(initialGroup, false);
})();