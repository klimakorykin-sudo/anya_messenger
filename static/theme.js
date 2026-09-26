// theme.js — переключение светлой/тёмной темы
(function () {
    const STORAGE_KEY = 'anya-theme';

    // Применяем сохранённую тему СРАЗУ, до отрисовки — чтобы не мигало
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'dark') {
        document.documentElement.classList.add('dark');
    }

    // Ждём загрузку DOM и вешаем обработчик на кнопку
    document.addEventListener('DOMContentLoaded', () => {
        const btn = document.getElementById('theme-toggle');
        if (!btn) return;

        updateIcon(btn);

        btn.addEventListener('click', () => {
            const isDark = document.documentElement.classList.toggle('dark');
            localStorage.setItem(STORAGE_KEY, isDark ? 'dark' : 'light');
            updateIcon(btn);
        });
    });

    function updateIcon(btn) {
        const isDark = document.documentElement.classList.contains('dark');
        btn.textContent = isDark ? '☀️' : '🌙';
        btn.title = isDark ? 'Светлая тема' : 'Тёмная тема';
    }
})();