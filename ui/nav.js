/* ═══════════════════════════════════════════════════════════
   Commander AI Lab — Shared Navigation Component
   ═══════════════════════════════════════════════════════════ */

(function() {
    const NAV_ITEMS = [
        { href: 'index.html',         label: 'Batch Sim',  icon: 'beaker' },
        { href: 'collection.html',    label: 'Collection', icon: 'stack' },
        { href: 'deckbuilder.html',   label: 'Decks',      icon: 'cards' },
        { href: 'deckgenerator.html', label: 'Auto Gen',   icon: 'sparkle' },
        { href: 'simulator.html',     label: 'Simulator',  icon: 'play' },
        { href: 'coach.html',         label: 'Coach',      icon: 'brain' },
        { href: 'training.html',      label: 'Training',   icon: 'chart' },
    ];

    const ICONS = {
        beaker:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 3h15M6 3v16a2 2 0 002 2h8a2 2 0 002-2V3"/><path d="M6 14h12"/></svg>',
        stack:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="6" rx="1"/><rect x="4" y="14" width="16" height="6" rx="1"/></svg>',
        cards:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="14" height="17" rx="2"/><path d="M18 8h2a2 2 0 012 2v10a2 2 0 01-2 2h-2"/></svg>',
        sparkle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z"/></svg>',
        play:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
        brain:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a7 7 0 017 7c0 2.38-1.19 4.47-3 5.74V17a2 2 0 01-2 2h-4a2 2 0 01-2-2v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 017-7z"/><path d="M9 21h6M10 17v4M14 17v4"/></svg>',
        chart:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>',
    };

    const BRAND_LOGO = '<svg viewBox="0 0 32 32" fill="none"><defs><linearGradient id="lg" x1="0" y1="0" x2="32" y2="32"><stop offset="0%" stop-color="#5b9ef0"/><stop offset="100%" stop-color="#a78bfa"/></linearGradient></defs><rect x="2" y="2" width="28" height="28" rx="8" fill="url(#lg)" opacity="0.15"/><path d="M16 6l3 6h6l-5 4 2 6-6-4-6 4 2-6-5-4h6z" fill="url(#lg)"/></svg>';

    function getCurrentPage() {
        const path = window.location.pathname;
        const filename = path.substring(path.lastIndexOf('/') + 1) || 'index.html';
        return filename;
    }

    function renderNav() {
        const currentPage = getCurrentPage();
        const nav = document.createElement('nav');
        nav.className = 'nav';

        const brand = document.createElement('a');
        brand.className = 'nav-brand';
        brand.href = 'index.html';
        brand.innerHTML = BRAND_LOGO + ' Commander AI Lab';
        nav.appendChild(brand);

        const links = document.createElement('div');
        links.className = 'nav-links';

        NAV_ITEMS.forEach(function(item) {
            const a = document.createElement('a');
            a.href = item.href;
            if (currentPage === item.href) a.className = 'active';
            a.innerHTML = '<span class="nav-icon">' + ICONS[item.icon] + '</span>' + item.label;
            links.appendChild(a);
        });

        nav.appendChild(links);
        document.body.insertBefore(nav, document.body.firstChild);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', renderNav);
    } else {
        renderNav();
    }
})();
