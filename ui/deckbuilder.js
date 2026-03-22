/* ═══════════════════════════════════════════════════════════
   Commander AI Lab — Deck Builder
   Pure vanilla JS, no frameworks.
   Communicates with backend via fetch() to relative /api/ URLs.
   ═══════════════════════════════════════════════════════════ */

'use strict';

/* ── Mana Cost Rendering ─────────────────────────────────── */

const MANA_COLORS = {
    W: 'deck-pip-W',
    U: 'deck-pip-U',
    B: 'deck-pip-B',
    R: 'deck-pip-R',
    G: 'deck-pip-G',
    C: 'deck-pip-C',
    X: 'deck-pip-X',
};

/**
 * Parse a mana cost string like "{2}{W}{U}" and return an array
 * of { label, cls } objects.
 */
function parseMana(costStr) {
    if (!costStr) return [];
    const pips = [];
    const regex = /\{([^}]+)\}/g;
    let m;
    while ((m = regex.exec(costStr)) !== null) {
        const sym = m[1].toUpperCase();
        if (MANA_COLORS[sym]) {
            pips.push({ label: sym, cls: MANA_COLORS[sym] });
        } else if (/^\d+$/.test(sym)) {
            pips.push({ label: sym, cls: 'deck-pip-N' });
        } else if (sym === 'X') {
            pips.push({ label: 'X', cls: 'deck-pip-X' });
        } else {
            // Hybrid or phyrexian — pick first color
            const first = sym[0];
            pips.push({ label: first, cls: MANA_COLORS[first] || 'deck-pip-N' });
        }
    }
    return pips;
}

/** Build a mana cost element. */
function buildManaCost(costStr) {
    const wrap = el('span', 'deck-mana-cost');
    for (const pip of parseMana(costStr)) {
        const span = el('span', `deck-mana-pip ${pip.cls}`);
        span.textContent = pip.label;
        wrap.appendChild(span);
    }
    return wrap;
}

/* ── DOM Helpers ─────────────────────────────────────────── */

/** Quick element factory. */
function el(tag, className, text) {
    const e = document.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined) e.textContent = text;
    return e;
}

function qs(sel, root) { return (root || document).querySelector(sel); }
function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

/* ── Toast System ────────────────────────────────────────── */

const ToastManager = {
    container: null,
    init() {
        this.container = qs('#deck-toast-container');
    },
    show(message, type = 'info', duration = 3000) {
        const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
        const toast = el('div', `deck-toast toast-${type}`);
        const icon = el('span', 'deck-toast-icon', icons[type] || icons.info);
        const text = el('span', 'deck-toast-text', message);
        toast.appendChild(icon);
        toast.appendChild(text);
        this.container.appendChild(toast);

        const remove = () => {
            toast.classList.add('removing');
            setTimeout(() => toast.remove(), 220);
        };
        setTimeout(remove, duration);
        toast.addEventListener('click', remove);
    }
};

/* ── Card Preview (hover tooltip) ────────────────────────── */

const CardPreview = {
    el: null,
    img: null,
    visible: false,   _hoverTimer: null,   HOVER_DELAY: 450,

    init() {
        this.el = qs('#deck-card-preview');
        this.img = qs('#deck-card-preview-img');
    },

    show(scryfallId, mx, my) {
        if (!scryfallId || !this.el) return;
        this.img.src = `https://api.scryfall.com/cards/${scryfallId}?format=image&version=normal`;
        this.img.onerror = () => this.hide();

        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const w = 180;
        let x = mx + 16;
        let y = my - 20;
        if (x + w > vw - 10) x = mx - w - 16;
        if (y + 252 > vh - 10) y = vh - 262;
        if (y < 10) y = 10;

        this.el.style.left = `${x}px`;
        this.el.style.top  = `${y}px`;
        this.el.style.display = 'block';
        this.visible = true;
    },

    hide() {
        clearTimeout(this._hoverTimer); if (this.el) this.el.style.display = 'none';
        this.visible = false;
    },

    attach(nameEl, scryfallId) {
        if (!scryfallId) return;
        let lastE = null; nameEl.addEventListener('mouseenter', (e) => { lastE = e; clearTimeout(this._hoverTimer); this._hoverTimer = setTimeout(() => { if (lastE) this.show(scryfallId, lastE.clientX, lastE.clientY); }, this.HOVER_DELAY); });
        nameEl.addEventListener('mousemove', (e) => { lastE = e; if (this.visible) this.show(scryfallId, e.clientX, e.clientY); });
        nameEl.addEventListener('mouseleave', () => this.hide());
    }
};

/* ── Confirmation Modal ───────────────────────────────────── */

const ConfirmDialog = {
    overlay: null,
    titleEl: null,
    messageEl: null,
    changesEl: null,
    okBtn: null,
    cancelBtn: null,
    closeBtn: null,
    _resolve: null,

    init() {
        this.overlay  = qs('#deck-confirm-modal');
        this.titleEl  = qs('#deck-confirm-title');
        this.messageEl = qs('#deck-confirm-message');
        this.changesEl = qs('#deck-confirm-changes');
        this.okBtn    = qs('#deck-confirm-ok');
        this.cancelBtn = qs('#deck-confirm-cancel');
        this.closeBtn  = qs('#deck-confirm-close');

        const close = () => { this.overlay.style.display = 'none'; if (this._resolve) this._resolve(false); };
        this.cancelBtn.addEventListener('click', close);
        this.closeBtn.addEventListener('click', close);
        this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) close(); });
        this.okBtn.addEventListener('click', () => {
            this.overlay.style.display = 'none';
            if (this._resolve) this._resolve(true);
        });
    },

    /**
     * @param {object} opts - { title, message, changes: [{label, before, after}] }
     * @returns {Promise<boolean>}
     */
    show({ title = 'Confirm Action', message = '', changes = [], okLabel = 'OK', cancelLabel = 'Cancel' }) {
        this.titleEl.textContent = title;
        this.messageEl.textContent = message;
        this.changesEl.innerHTML = '';
        this.okBtn.textContent = okLabel;
        this.cancelBtn.textContent = cancelLabel;

        if (changes.length > 0) {
            for (const c of changes) {
                const row = el('div', 'deck-confirm-change-row');
                const lbl = el('span', 'deck-confirm-change-label', c.label);
                const diff = (c.after - c.before);
                const cls = diff > 0 ? 'positive' : diff < 0 ? 'negative' : '';
                const val = el('span', `deck-confirm-change-val ${cls}`, `${c.before} → ${c.after}`);
                row.appendChild(lbl);
                row.appendChild(val);
                this.changesEl.appendChild(row);
            }
        } else {
            this.changesEl.style.display = 'none';
        }
        if (changes.length > 0) {
            this.changesEl.style.display = '';
        }

        this.overlay.style.display = 'flex';
        return new Promise(resolve => { this._resolve = resolve; });
    }
};

/* ── API Helpers ─────────────────────────────────────────── */

async function apiFetch(path, options = {}) {
    const res = await fetch(path, {
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
    });
    if (!res.ok) {
        let errMsg = `HTTP ${res.status}`;
        try { const body = await res.json(); errMsg = body.detail || body.message || errMsg; } catch (_) {}
        throw new Error(errMsg);
    }
    if (res.status === 204) return null;
    return res.json();
}

function apiGet(path) { return apiFetch(path); }
function apiPost(path, data) { return apiFetch(path, { method: 'POST', body: JSON.stringify(data) }); }
function apiPut(path, data) { return apiFetch(path, { method: 'PUT', body: JSON.stringify(data) }); }
function apiPatch(path, data) { return apiFetch(path, { method: 'PATCH', body: JSON.stringify(data) }); }
function apiDelete(path) { return apiFetch(path, { method: 'DELETE' }); }

/* ── Scryfall Autocomplete ────────────────────────────────── */

let _scryfallCache = {};

async function scryfallAutocomplete(query) {
    if (!query || query.length < 2) return [];
    if (_scryfallCache[query]) return _scryfallCache[query];
    try {
        const res = await fetch(`https://api.scryfall.com/cards/autocomplete?q=${encodeURIComponent(query)}`);
        if (!res.ok) return [];
        const json = await res.json();
        _scryfallCache[query] = json.data || [];
        return _scryfallCache[query];
    } catch (_) {
        return [];
    }
}

async function scryfallFuzzySearch(query) {
    try {
        const res = await fetch(`https://api.scryfall.com/cards/named?fuzzy=${encodeURIComponent(query)}`);
        if (!res.ok) return null;
        return res.json();
    } catch (_) {
        return null;
    }
}

async function scryfallSearchCards(query) {
    try {
        const res = await fetch(`https://api.scryfall.com/cards/search?q=${encodeURIComponent(query)}&unique=cards&order=name`);
        if (!res.ok) return [];
        const json = await res.json();
        return json.data || [];
    } catch (_) {
        return [];
    }
}

/* ── EDH Target Ratios ────────────────────────────────────── */

const EDH_TARGETS = {
    Land:         { min: 35, target: 37, max: 40, label: 'Lands' },
    Creature:     { min: 20, target: 25, max: 32, label: 'Creatures' },
    Instant:      { min: 7,  target: 10, max: 14, label: 'Instants' },
    Sorcery:      { min: 5,  target: 8,  max: 12, label: 'Sorceries' },
    Artifact:     { min: 6,  target: 10, max: 15, label: 'Artifacts' },
    Enchantment:  { min: 5,  target: 8,  max: 12, label: 'Enchantments' },
    Planeswalker: { min: 0,  target: 2,  max: 5,  label: 'Planeswalkers' },
};

/** Map a card's type_line to one of the canonical groups. */
function getCardTypeGroup(typeLine) {
    if (!typeLine) return 'Other';
    const t = typeLine.toLowerCase();
    if (t.includes('land'))         return 'Land';
    if (t.includes('creature'))     return 'Creature';
    if (t.includes('planeswalker')) return 'Planeswalker';
    if (t.includes('instant'))      return 'Instant';
    if (t.includes('sorcery'))      return 'Sorcery';
    if (t.includes('artifact'))     return 'Artifact';
    if (t.includes('enchantment'))  return 'Enchantment';
    return 'Other';
}

/** Return a ratio progress status string. */
function ratioStatus(count, min, max) {
    if (count === 0 && min === 0) return 'neutral';
    if (count < min)  return 'low';
    if (count > max)  return 'over';
    if (count >= min && count <= max) return 'ok';
    return 'warn';
}

/* ── Debounce Helper ──────────────────────────────────────── */

function debounce(fn, ms) {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

/* ── Color Identity Rendering ────────────────────────────── */

const COLOR_NAMES = { W: 'White', U: 'Blue', B: 'Black', R: 'Red', G: 'Green', C: 'Colorless' };

function buildColorChip(color) {
    const chip = el('span', `deck-color-chip deck-chip-${color}`);
    chip.textContent = color;
    chip.title = COLOR_NAMES[color] || color;
    return chip;
}

function parseColorIdentity(raw) {
    if (!raw) return [];
    if (Array.isArray(raw)) return raw;
    // "WUBRG" string or comma-separated
    if (raw.includes(',')) return raw.split(',').map(c => c.trim().toUpperCase());
    return raw.toUpperCase().split('').filter(c => 'WUBRG'.includes(c));
}

/* ── Type Badge ───────────────────────────────────────────── */

function buildTypeBadge(typeLine) {
    const group = getCardTypeGroup(typeLine || '');
    const badge = el('span', `deck-type-badge deck-type-${group}`, group[0] === 'P' && group !== 'Planeswalker' ? group : group.slice(0, 4));
    badge.title = typeLine || group;
    return badge;
}

/* ── Main DeckBuilder Application ────────────────────────── */

const DeckBuilder = {
    /* State */
    deckId: null,
    deckName: '',
    deckCards: [],
    deckInfo: null,
    analysis: null,
    allDecks: [],
    searchResults: [],
    searchQuery: '',
    searchType: '',
    searchCmcMin: null,
    searchCmcMax: null,
    searchColors: new Set(),
    edhRecData: [],
    edhRecOwnedOnly: false,
    commanderScryfallId: null,
    newCommanderScryfallId: null,
    newCommanderName: '',
    _saveTimer: null,
    _activeTypeFilter: null,
    pplxConfigured: false,
    aiGenCommanderName: '',
    _aiGenSuggestions: [],
    _aiGenActiveIndex: -1,
    _lastGenResult: null,

    /* ── Init ─────────────────────────────────────────────── */

    async init() {
        ToastManager.init();
        CardPreview.init();
        ConfirmDialog.init();

        this._bindTopBar();
        this._bindSearch();
        this._bindQuickAdd();
        this._bindNewDeckModal();
        this._bindCollapsible();
        this._bindRightColumn();
        this._bindAIPanels();

        await this.loadDecks();
        this._checkPplxStatus();

        // Restore last deck from localStorage
        const lastId = localStorage.getItem('deck-builder-last-deck');
        if (lastId) {
            this.deckId = parseInt(lastId, 10);
            qs('#deck-selector').value = this.deckId;
            await this.loadDeck(this.deckId);
        }
    },

    /* ── Top Bar Bindings ─────────────────────────────────── */

    _bindTopBar() {
        const selector = qs('#deck-selector');
        selector.addEventListener('change', async (e) => {
            const id = parseInt(e.target.value, 10);
            if (!isNaN(id)) {
                this.deckId = id;
                await this.loadDeck(id);
            }
        });

        const nameInput = qs('#deck-name-input');
        nameInput.addEventListener('input', () => this._scheduleSaveName());
        nameInput.addEventListener('change', () => this._saveDeckName());

        qs('#deck-new-btn').addEventListener('click', () => this._openNewDeckModal());
        qs('#deck-empty-new-btn').addEventListener('click', () => this._openNewDeckModal());

        qs('#deck-export-btn').addEventListener('click', () => this._exportDck());
        qs('#deck-export-sim-btn').addEventListener('click', () => this._exportDckToSim());
        qs('#deck-sim-btn').addEventListener('click', () => this._exportToSim());
        qs('#deck-import-btn').addEventListener('click', () => this._openImportModal());
        qs('#deck-delete-btn').addEventListener('click', () => this._deleteDeck());
        qs('#deck-clear-all-btn').addEventListener('click', () => this._clearAllDecks());

        // Import modal wiring
        this._initImportModal();

        // Commander portrait click to change commander
        qs('#deck-commander-portrait').addEventListener('click', () => {
            if (!this.deckId) { ToastManager.show('Create a deck first.', 'warning'); return; }
            this._openNewDeckModal(true);
        });
    },

    _scheduleSaveName() {
        clearTimeout(this._saveTimer);
        this._saveTimer = setTimeout(() => this._saveDeckName(), 1200);
    },

    async _saveDeckName() {
        if (!this.deckId) return;
        const name = qs('#deck-name-input').value.trim();
        if (!name || name === this.deckName) return;
        try {
            await apiPut(`/api/decks/${this.deckId}`, { name });
            this.deckName = name;
            this._refreshDeckSelector();
        } catch (err) {
            ToastManager.show(`Failed to rename deck: ${err.message}`, 'error');
        }
    },

    async _deleteDeck() {
        if (!this.deckId) { ToastManager.show('No deck selected.', 'warning'); return; }
        const ok = await ConfirmDialog.show({
            title: 'Delete Deck',
            message: 'Are you sure you want to delete "' + (this.deckName || 'this deck') + '"? This cannot be undone.',
            okLabel: 'Delete',
        });
        if (!ok) return;
        try {
            await apiDelete('/api/decks/' + this.deckId);
            ToastManager.show('Deck deleted.', 'success');
            this.deckId = null;
            this.deckInfo = null;
            this.deckName = '';
            this.deckCards = [];
            localStorage.removeItem('deck-builder-last-deck');
            qs('#deck-delete-btn').style.display = 'none';
            await this.loadDecks();
            qs('#deck-selector').value = '';
            qs('#deck-name-input').value = '';
            qs('#deck-card-groups').innerHTML = '';
        } catch (err) {
            ToastManager.show('Failed to delete deck: ' + err.message, 'error');
        }
    },

    async _clearAllDecks() {
        if (!this.allDecks.length) { ToastManager.show('No decks to clear.', 'warning'); return; }
        const ok = await ConfirmDialog.show({
            title: 'Clear All Decks',
            message: 'Delete all ' + this.allDecks.length + ' decks? This cannot be undone.',
            okLabel: 'Delete All',
        });
        if (!ok) return;
        try {
            await apiDelete('/api/decks');
            ToastManager.show('All decks cleared.', 'success');
            this.deckId = null;
            this.deckInfo = null;
            this.deckName = '';
            this.deckCards = [];
            this.allDecks = [];
            localStorage.removeItem('deck-builder-last-deck');
            qs('#deck-delete-btn').style.display = 'none';
            this._renderDeckSelector();
            qs('#deck-selector').value = '';
            qs('#deck-name-input').value = '';
            qs('#deck-card-groups').innerHTML = '';
        } catch (err) {
            ToastManager.show('Failed to clear decks: ' + err.message, 'error');
        }
    },

    /* ── Deck Loading ─────────────────────────────────────── */

    async loadDecks() {
        try {
            const resp = await apiGet('/api/decks');
            this.allDecks = Array.isArray(resp) ? resp : (resp.decks || []);
            this._renderDeckSelector();
        } catch (_) {
            this.allDecks = [];
        }
    },

    _renderDeckSelector() {
        const sel = qs('#deck-selector');
        const current = sel.value;
        sel.innerHTML = '<option value="">— Select Deck —</option>';
        for (const d of this.allDecks) {
            const opt = document.createElement('option');
            opt.value = d.id;
            opt.textContent = `${d.name}${d.commander_name ? ' (' + d.commander_name + ')' : ''}`;
            sel.appendChild(opt);
        }
        sel.value = current;
    },

    _refreshDeckSelector() {
        const idx = this.allDecks.findIndex(d => d.id === this.deckId);
        if (idx >= 0) {
            this.allDecks[idx].name = this.deckName;
            this._renderDeckSelector();
            qs('#deck-selector').value = this.deckId;
        }
    },

    async loadDeck(id) {
        if (!id) return;
        this.deckId = id;
        localStorage.setItem('deck-builder-last-deck', id);

        // Show loading skeletons
        this._showCardGroupsLoading();

        try {
            // Parallel fetch: deck info + cards
            const [info, cards] = await Promise.all([
                apiGet(`/api/decks/${id}`),
                apiGet(`/api/decks/${id}/cards`),
            ]);
            this.deckInfo = info;
            this.deckName = info.name;
            this.deckCards = Array.isArray(cards) ? cards : (cards.cards || []);
            this.commanderScryfallId = this.deckCards.find(c => c.is_commander)?.scryfall_id || null;

            this._renderTopBar();
            this._renderCardGroups();
            this._showDeckControls();

            // Load analysis for ratio dashboard (non-blocking)
            this._loadAnalysis();

            // Refresh search results with new deck context
            if (this.searchQuery) this._runSearch();

            // Enable AI research button
            this._updateAIResearchBtn();

        } catch (err) {
            ToastManager.show(`Failed to load deck: ${err.message}`, 'error');
            this._renderCardGroups(); // show empty state
        }
    },

    _renderTopBar() {
        const info = this.deckInfo;
        if (!info) return;

        qs('#deck-name-input').value = info.name || '';

        // Commander label
        const cmdLabel = qs('#deck-commander-label');
        if (info.commander_name) {
            cmdLabel.textContent = info.commander_name;
        } else {
            cmdLabel.textContent = 'No commander selected';
        }

        // Commander portrait
        const img = qs('#deck-commander-img');
        const placeholder = qs('.deck-commander-portrait-placeholder');
        const portrait = qs('#deck-commander-portrait');
        const cmdCard = this.deckCards.find(c => c.is_commander);
        if (cmdCard && cmdCard.scryfall_id) {
            img.src = `https://api.scryfall.com/cards/${cmdCard.scryfall_id}?format=image&version=small`;
            img.style.display = 'block';
            placeholder.style.display = 'none';
            this.commanderScryfallId = cmdCard.scryfall_id;

            // Attach card preview hover to commander label and portrait
            CardPreview.attach(cmdLabel, cmdCard.scryfall_id);
            CardPreview.attach(portrait, cmdCard.scryfall_id);
        } else {
            img.style.display = 'none';
            placeholder.style.display = '';
        }

        // Color chips
        const chipsEl = qs('#deck-color-chips');
        chipsEl.innerHTML = '';
        const colors = parseColorIdentity(info.color_identity);
        for (const c of colors) {
            chipsEl.appendChild(buildColorChip(c));
        }

        // Total count
        this._updateCountDisplay();

        // Selector
        qs('#deck-selector').value = info.id;
    },

    _updateCountDisplay() {
        const total = this.deckCards.reduce((s, c) => s + (c.quantity || 1), 0);
        const countEl = qs('#deck-total-count');
        countEl.textContent = total;
        countEl.className = 'deck-count-num' + (total > 100 ? ' over-limit' : total === 100 ? ' at-limit' : '');

        const footerTotal = qs('#deck-footer-total');
        if (footerTotal) footerTotal.textContent = total;

        const owned = this.deckCards
            .filter(c => (c.owned_quantity || 0) >= (c.quantity || 1))
            .reduce((s, c) => s + (c.quantity || 1), 0);
        const footerOwned = qs('#deck-footer-owned');
        if (footerOwned) footerOwned.textContent = owned;

        const nonLands = this.deckCards.filter(c => getCardTypeGroup(c.type_line) !== 'Land');
        const avgCmc = nonLands.length > 0
            ? (nonLands.reduce((s, c) => s + (c.cmc || 0) * (c.quantity || 1), 0) /
               nonLands.reduce((s, c) => s + (c.quantity || 1), 0)).toFixed(1)
            : '0.0';
        const footerCmc = qs('#deck-footer-avg-cmc');
        if (footerCmc) footerCmc.textContent = avgCmc;
    },

    _showDeckControls() {
        qs('#deck-quickadd-row').style.display = '';
        qs('#deck-stats-footer').style.display = '';
        qs('#deck-delete-btn').style.display = this.deckId ? '' : 'none';
    },

    /* ── Card Groups Rendering ────────────────────────────── */

    _showCardGroupsLoading() {
        const container = qs('#deck-card-groups');
        container.innerHTML = '';
        for (let i = 0; i < 5; i++) {
            const skel = el('div', 'deck-skeleton deck-skeleton-row');
            container.appendChild(skel);
        }
    },

    _renderCardGroups() {
        const container = qs('#deck-card-groups');
        container.innerHTML = '';

        if (!this.deckId || !this.deckCards || this.deckCards.length === 0) {
            const empty = el('div', 'deck-empty-state deck-empty-state-lg');
            const icon = el('div', 'deck-empty-icon', '⚔');
            const text = el('div', 'deck-empty-text', this.deckId
                ? 'Your deck is empty. Add cards from the search panel.'
                : 'Create or select a deck to start building.');
            const btn = el('button', 'deck-btn deck-btn-accent');
            btn.textContent = '+ New Deck';
            btn.addEventListener('click', () => this._openNewDeckModal());
            empty.appendChild(icon);
            empty.appendChild(text);
            if (!this.deckId) empty.appendChild(btn);
            container.appendChild(empty);
            return;
        }

        // Separate commander(s) from the rest
        const commanders = this.deckCards.filter(c => c.is_commander);
        const nonCommanders = this.deckCards.filter(c => !c.is_commander);

        // Render commander section first
        if (commanders.length > 0) {
            const cmdSection = this._buildSection('Commander', commanders, true);
            container.appendChild(cmdSection);
        }

        // Group remaining cards by type
        const groups = {};
        for (const card of nonCommanders) {
            const group = getCardTypeGroup(card.type_line);
            if (!groups[group]) groups[group] = [];
            groups[group].push(card);
        }

        const ORDER = ['Creature', 'Land', 'Instant', 'Sorcery', 'Artifact', 'Enchantment', 'Planeswalker', 'Other'];

        for (const type of ORDER) {
            if (!groups[type] || groups[type].length === 0) continue;
            const sectionEl = this._buildSection(type, groups[type]);
            container.appendChild(sectionEl);
        }

        // Update meta label
        const metaEl = qs('#deck-card-list-meta');
        const total = this.deckCards.reduce((s, c) => s + (c.quantity || 1), 0);
        metaEl.textContent = `${this.deckCards.length} unique · ${total} total`;

        this._updateCountDisplay();
    },

    _buildSection(type, cards, isCommanderSection) {
        const target = isCommanderSection ? null : EDH_TARGETS[type];
        const count = cards.reduce((s, c) => s + (c.quantity || 1), 0);

        const section = el('div', `deck-section${isCommanderSection ? ' deck-section-commander' : ''}`);
        section.dataset.type = type;

        // Section header
        const header = el('div', 'deck-section-header');

        const arrow = el('span', 'deck-section-toggle', '▼');

        const sectionLabel = isCommanderSection ? '⚔ Commander' : (type === 'Other' ? 'Other / Misc' : `${type}s`);
        const nameLbl = el('span', 'deck-section-name', sectionLabel);

        let countText = `${count}`;
        if (target) countText += ` / ~${target.target}`;
        const countLbl = el('span', 'deck-section-count', countText);

        header.appendChild(arrow);
        header.appendChild(nameLbl);
        header.appendChild(countLbl);

        // Progress bar (skip for commander section)
        if (!isCommanderSection) {
            const progress = el('div', 'deck-section-progress');
            const fill = el('div', 'deck-section-progress-fill');
            if (target) {
                const pct = Math.min(100, Math.round((count / target.max) * 100));
                fill.style.width = `${pct}%`;
                fill.classList.add(`status-${ratioStatus(count, target.min, target.max)}`);
            } else {
                fill.style.width = '50%';
                fill.classList.add('status-neutral');
            }
            progress.appendChild(fill);
            header.appendChild(progress);
        }

        // Body
        const body = el('div', 'deck-section-body');
        // Set an explicit max-height so CSS transition works
        body.style.maxHeight = '9999px';

        for (const card of cards) {
            body.appendChild(this._buildCardRow(card));
        }

        header.addEventListener('click', () => {
            const collapsed = body.classList.toggle('collapsed');
            arrow.classList.toggle('collapsed', collapsed);
            if (!collapsed) {
                body.style.maxHeight = '9999px';
            } else {
                body.style.maxHeight = '0px';
            }
        });

        section.appendChild(header);
        section.appendChild(body);
        return section;
    },

    _buildCardRow(card) {
        const isCmd = card.is_commander;
        const row = el('div', `deck-card-row${isCmd ? ' is-commander' : ''}`);
        row.dataset.cardId = card.id;

        // Owned dot
        const ownedDot = el('span', `deck-card-owned-dot${(card.owned_quantity || 0) > 0 ? '' : ' unowned'}`);
        ownedDot.title = `Owned: ${card.owned_quantity || 0}`;
        row.appendChild(ownedDot);

        // Mana cost (before name)
        if (card.mana_cost) {
            const manaEl = buildManaCost(card.mana_cost);
            manaEl.className = 'deck-card-row-mana';
            row.appendChild(manaEl);
        }

        // Name (hoverable for card preview)
        const nameEl = el('span', 'deck-card-row-name', card.card_name);
        const hoverSfId = card.scryfall_id || (isCmd ? this.commanderScryfallId : null);
        if (hoverSfId) CardPreview.attach(nameEl, hoverSfId);
        row.appendChild(nameEl);

        // Role chip (only for non-commander)
        if (!isCmd) {
            const role = card.role_tag || '';
            const roleChip = el('span', 'deck-card-role-chip', role || 'role');
            roleChip.title = 'Click to set role';
            roleChip.addEventListener('click', () => this._setRoleTag(card));
            row.appendChild(roleChip);
        }

        // Quantity controls (not for commander)
        if (!isCmd) {
            const qtyWrap = el('div', 'deck-qty-controls');
            const minusBtn = el('button', 'deck-qty-btn', '−');
            const qtyNum = el('span', 'deck-qty-num', String(card.quantity || 1));
            const plusBtn = el('button', 'deck-qty-btn', '+');

            minusBtn.addEventListener('click', () => this._changeQty(card, -1));
            plusBtn.addEventListener('click',  () => this._changeQty(card, +1));

            qtyWrap.appendChild(minusBtn);
            qtyWrap.appendChild(qtyNum);
            qtyWrap.appendChild(plusBtn);
            row.appendChild(qtyWrap);
        }

        // Commander badge (after other controls, at end of row)
        if (isCmd) {
            const cmdBadge = el('span', 'deck-card-commander-badge', 'Commander');
            row.appendChild(cmdBadge);
        }

        // Remove button
        const removeBtn = el('button', 'deck-card-remove-btn', '✕');
        removeBtn.title = 'Remove from deck';
        removeBtn.addEventListener('click', () => this._removeCard(card));
        row.appendChild(removeBtn);

        return row;
    },

    async _changeQty(card, delta) {
        const newQty = (card.quantity || 1) + delta;
        if (newQty < 1) {
            await this._removeCard(card);
            return;
        }
        try {
            await apiPatch(`/api/decks/${this.deckId}/cards/${card.id}`, { quantity: newQty });
            card.quantity = newQty;
            // Update the row's quantity display without full re-render
            const row = qs(`[data-card-id="${card.id}"]`);
            if (row) {
                const num = qs('.deck-qty-num', row);
                if (num) num.textContent = newQty;
            }
            this._updateCountDisplay();
            this._updateRatioBar(getCardTypeGroup(card.type_line));
        } catch (err) {
            ToastManager.show(`Failed to update quantity: ${err.message}`, 'error');
        }
    },

    async _removeCard(card) {
        try {
            await apiDelete(`/api/decks/${this.deckId}/cards/${card.id}`);
            this.deckCards = this.deckCards.filter(c => c.id !== card.id);
            this._renderCardGroups();
            this._loadAnalysis();
            ToastManager.show(`Removed ${card.card_name}`, 'info');
        } catch (err) {
            ToastManager.show(`Failed to remove: ${err.message}`, 'error');
        }
    },

    async _setRoleTag(card) {
        const roles = ['ramp', 'draw', 'removal', 'wipe', 'tutor', 'protection', 'win-con', 'synergy', 'value', 'beatdown', ''];
        const current = card.role_tag || '';
        const currentIdx = roles.indexOf(current);
        const next = roles[(currentIdx + 1) % roles.length];

        try {
            await apiPatch(`/api/decks/${this.deckId}/cards/${card.id}`, { role_tag: next });
            card.role_tag = next;
            const row = qs(`[data-card-id="${card.id}"]`);
            if (row) {
                const chip = qs('.deck-card-role-chip', row);
                if (chip) chip.textContent = next || 'role';
            }
        } catch (err) {
            ToastManager.show(`Failed to set role: ${err.message}`, 'error');
        }
    },

    /* ── Adding Cards ─────────────────────────────────────── */

    async addCardToDeck(scryfallId, cardName, quantity = 1, isCommander = false) {
        if (!this.deckId) {
            ToastManager.show('Select or create a deck first.', 'warning');
            return;
        }
        try {
            await apiPost(`/api/decks/${this.deckId}/cards`, {
                scryfall_id: scryfallId,
                card_name: cardName || '',
                quantity,
                is_commander: isCommander ? 1 : 0,
            });
            // Reload deck cards
            const _cardsResp = await apiGet(`/api/decks/${this.deckId}/cards`);
            this.deckCards = Array.isArray(_cardsResp) ? _cardsResp : (_cardsResp.cards || []);
            this._renderCardGroups();
            this._loadAnalysis();
            ToastManager.show(`Added ${cardName}`, 'success');
            // Refresh search results to update in-deck status
            if (this.searchQuery) this._refreshSearchInDeckStatus();
        } catch (err) {
            if (err.message.includes('already in deck') || err.message.includes('already exists')) {
                ToastManager.show(`${cardName} is already in your deck`, 'warning');
            } else {
                ToastManager.show(`Failed to add ${cardName}: ${err.message}`, 'error');
            }
        }
    },

    _refreshSearchInDeckStatus() {
        const inDeckIds = new Set(this.deckCards.map(c => c.scryfall_id));
        qsa('.deck-search-row', qs('#deck-search-results')).forEach(row => {
            const id = row.dataset.scryfallId;
            if (inDeckIds.has(id)) {
                row.classList.add('in-deck');
                const addBtn = qs('.deck-search-row-add', row);
                if (addBtn) addBtn.textContent = '✓';
            } else {
                row.classList.remove('in-deck');
                const addBtn = qs('.deck-search-row-add', row);
                if (addBtn) addBtn.textContent = '+';
            }
        });
    },

    /* ── Collection Search ────────────────────────────────── */

    _bindSearch() {
        const bar = qs('#deck-search-bar');
        const typeFilter = qs('#deck-type-filter');
        const cmcMin = qs('#deck-cmc-min');
        const cmcMax = qs('#deck-cmc-max');

        const debouncedSearch = debounce(() => this._runSearch(), 350);

        bar.addEventListener('input', (e) => {
            this.searchQuery = e.target.value.trim();
            debouncedSearch();
        });

        typeFilter.addEventListener('change', (e) => {
            this.searchType = e.target.value;
            this._runSearch();
        });

        cmcMin.addEventListener('change', (e) => {
            this.searchCmcMin = e.target.value !== '' ? parseInt(e.target.value, 10) : null;
            debouncedSearch();
        });

        cmcMax.addEventListener('change', (e) => {
            this.searchCmcMax = e.target.value !== '' ? parseInt(e.target.value, 10) : null;
            debouncedSearch();
        });

        // Color filter pills
        qs('#deck-color-filter').addEventListener('click', (e) => {
            const btn = e.target.closest('.deck-color-pip');
            if (!btn) return;
            const color = btn.dataset.color;
            if (this.searchColors.has(color)) {
                this.searchColors.delete(color);
                btn.classList.remove('active');
            } else {
                this.searchColors.add(color);
                btn.classList.add('active');
            }
            debouncedSearch();
        });

        qs('#deck-add-all-owned-btn').addEventListener('click', () => this._addAllMatching());
    },

    async _runSearch() {
        const resultsEl = qs('#deck-search-results');

        if (!this.searchQuery && !this.searchType && this.searchColors.size === 0 && this.searchCmcMin === null && this.searchCmcMax === null) {
            resultsEl.innerHTML = '';
            const empty = el('div', 'deck-empty-state');
            empty.appendChild(el('div', 'deck-empty-icon', '🃏'));
            empty.appendChild(el('div', 'deck-empty-text', 'Search your collection to add cards'));
            resultsEl.appendChild(empty);
            qs('#deck-search-count').textContent = '0 results';
            qs('#deck-add-all-owned-btn').style.display = 'none';
            return;
        }

        // Show loading
        resultsEl.innerHTML = '<div class="deck-loading-inline"><div class="deck-loading-spinner"></div>Searching...</div>';

        try {
            let params = ['pageSize=200'];
            if (this.searchQuery) params.push(`q=${encodeURIComponent(this.searchQuery)}`);
            if (this.deckId)      params.push(`deck_id=${this.deckId}`);
            if (this.searchType)  params.push(`types=${encodeURIComponent(this.searchType)}`);
            if (this.searchCmcMin !== null) params.push(`cmcMin=${this.searchCmcMin}`);
            if (this.searchCmcMax !== null) params.push(`cmcMax=${this.searchCmcMax}`);
            if (this.searchColors.size > 0) params.push(`colors=${[...this.searchColors].join(',')}`);

            const url = `/api/collection?${params.join('&')}`;
            const _collResp = await apiGet(url);
            let cards = Array.isArray(_collResp) ? _collResp : (_collResp.items || []);

            // Client-side fallback filters
            if (this.searchType) {
                cards = cards.filter(c => getCardTypeGroup(c.type_line || '') === this.searchType);
            }
            if (this.searchCmcMin !== null) {
                cards = cards.filter(c => (c.cmc || 0) >= this.searchCmcMin);
            }
            if (this.searchCmcMax !== null) {
                cards = cards.filter(c => (c.cmc || 0) <= this.searchCmcMax);
            }

            this.searchResults = cards;
            this._renderSearchResults(cards);

        } catch (err) {
            resultsEl.innerHTML = `<div class="deck-empty-state"><div class="deck-empty-text" style="color:var(--lab-danger)">${err.message}</div></div>`;
        }
    },

    _renderSearchResults(cards) {
        const resultsEl = qs('#deck-search-results');
        resultsEl.innerHTML = '';

        qs('#deck-search-count').textContent = `${cards.length} result${cards.length !== 1 ? 's' : ''}`;

        if (cards.length === 0) {
            const empty = el('div', 'deck-empty-state');
            empty.appendChild(el('div', 'deck-empty-icon', '🔍'));
            empty.appendChild(el('div', 'deck-empty-text', 'No cards found in your collection'));
            resultsEl.appendChild(empty);
            qs('#deck-add-all-owned-btn').style.display = 'none';
            return;
        }

        const inDeckIds = new Set(this.deckCards.map(c => c.scryfall_id));
        let hasOwned = false;

        for (const card of cards) {
            const inDeck = inDeckIds.has(card.scryfall_id);
            const owned = (card.quantity || card.owned_quantity || 0) > 0;
            if (owned) hasOwned = true;

            const row = el('div', `deck-search-row${inDeck ? ' in-deck' : ''}`);
            row.dataset.scryfallId = card.scryfall_id;

            const nameEl = el('span', 'deck-search-row-name', card.card_name || card.name);
            CardPreview.attach(nameEl, card.scryfall_id);

            const manaEl = buildManaCost(card.mana_cost);
            manaEl.className = 'deck-search-row-mana';

            const ownedEl = el('span', `deck-search-row-owned${owned ? ' has-owned' : ''}`,
                owned ? `×${card.quantity || card.owned_quantity}` : '—');
            ownedEl.title = `Owned: ${card.quantity || card.owned_quantity || 0}`;

            const addBtn = el('button', 'deck-search-row-add', inDeck ? '✓' : '+');
            addBtn.title = inDeck ? 'Already in deck' : 'Add to deck';
            addBtn.addEventListener('click', () => {
                this.addCardToDeck(card.scryfall_id, card.card_name || card.name);
            });

            row.appendChild(nameEl);
            row.appendChild(manaEl);
            row.appendChild(ownedEl);
            row.appendChild(addBtn);
            resultsEl.appendChild(row);
        }

        // Show bulk-add button if there are owned cards
        const bulkBtn = qs('#deck-add-all-owned-btn');
        bulkBtn.style.display = hasOwned ? '' : 'none';
    },

    async _addAllMatching() {
        const owned = this.searchResults.filter(c => (c.quantity || c.owned_quantity || 0) > 0);
        if (owned.length === 0) {
            ToastManager.show('No owned cards in search results.', 'warning');
            return;
        }

        const confirmed = await ConfirmDialog.show({
            title: 'Add All Owned',
            message: `Add all ${owned.length} owned matching card(s) to your deck?`,
            changes: [{ label: 'Cards to add', before: 0, after: owned.length }],
        });
        if (!confirmed) return;

        let added = 0, skipped = 0;
        for (const card of owned) {
            try {
                await apiPost(`/api/decks/${this.deckId}/cards`, {
                    scryfall_id: card.scryfall_id,
                    card_name: card.card_name || card.name || '',
                    quantity: 1,
                });
                added++;
            } catch (_) {
                skipped++;
            }
        }

        const _cr1 = await apiGet(`/api/decks/${this.deckId}/cards`);
        this.deckCards = Array.isArray(_cr1) ? _cr1 : (_cr1.cards || []);
        this._renderCardGroups();
        this._loadAnalysis();
        this._refreshSearchInDeckStatus();
        ToastManager.show(`Bulk added ${added} cards${skipped > 0 ? ` (${skipped} skipped)` : ''}`, 'success');
    },

    /* ── Quick Add ────────────────────────────────────────── */

    _bindQuickAdd() {
        const input = qs('#deck-quickadd-input');
        const dropdown = qs('#deck-quickadd-dropdown');
        const addBtn = qs('#deck-quickadd-btn');

        let _activeIndex = -1;
        let _suggestions = [];

        const debouncedAC = debounce(async (q) => {
            if (!q || q.length < 2) { dropdown.style.display = 'none'; return; }
            const names = await scryfallAutocomplete(q);
            _suggestions = names.slice(0, 8);
            _activeIndex = -1;
            this._renderQuickAddDropdown(_suggestions, _activeIndex, dropdown);
        }, 280);

        input.addEventListener('input', (e) => debouncedAC(e.target.value.trim()));

        input.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowDown') {
                _activeIndex = Math.min(_activeIndex + 1, _suggestions.length - 1);
                this._renderQuickAddDropdown(_suggestions, _activeIndex, dropdown);
                e.preventDefault();
            } else if (e.key === 'ArrowUp') {
                _activeIndex = Math.max(_activeIndex - 1, -1);
                this._renderQuickAddDropdown(_suggestions, _activeIndex, dropdown);
                e.preventDefault();
            } else if (e.key === 'Enter') {
                e.preventDefault();
                const name = _activeIndex >= 0 ? _suggestions[_activeIndex] : input.value.trim();
                if (name) this._quickAddByName(name, input, dropdown);
            } else if (e.key === 'Escape') {
                dropdown.style.display = 'none';
            }
        });

        document.addEventListener('click', (e) => {
            if (!input.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.style.display = 'none';
            }
        });

        addBtn.addEventListener('click', () => {
            const name = input.value.trim();
            if (name) this._quickAddByName(name, input, dropdown);
        });

        dropdown.addEventListener('click', (e) => {
            const item = e.target.closest('.deck-quickadd-item');
            if (item) {
                const name = item.dataset.name;
                this._quickAddByName(name, input, dropdown);
            }
        });
    },

    _renderQuickAddDropdown(suggestions, activeIndex, dropdown) {
        dropdown.innerHTML = '';
        if (suggestions.length === 0) { dropdown.style.display = 'none'; return; }
        for (let i = 0; i < suggestions.length; i++) {
            const name = suggestions[i];
            const item = el('div', `deck-quickadd-item${i === activeIndex ? ' active' : ''}`);
            item.dataset.name = name;
            item.appendChild(el('span', 'deck-quickadd-item-name', name));
            dropdown.appendChild(item);
        }
        dropdown.style.display = 'block';
    },

    async _quickAddByName(name, input, dropdown) {
        if (!this.deckId) {
            ToastManager.show('Create or select a deck first.', 'warning');
            return;
        }
        dropdown.style.display = 'none';
        input.value = '';

        // Scryfall fuzzy lookup to get the scryfall_id
        const card = await scryfallFuzzySearch(name);
        if (!card) {
            ToastManager.show(`Card "${name}" not found on Scryfall`, 'error');
            return;
        }
        await this.addCardToDeck(card.id, card.name);
    },

    /* ── Analysis & Ratio Dashboard ──────────────────────── */

    async _loadAnalysis() {
        if (!this.deckId) return;
        try {
            this.analysis = await apiGet(`/api/decks/${this.deckId}/analysis`);
            this._renderRatioDashboard();
            this._renderShortfalls();
        } catch (_) {
            this._renderRatioDashboard(true);
        }
    },

    _renderRatioDashboard(failed = false) {
        const barsEl = qs('#deck-ratio-bars');
        barsEl.innerHTML = '';

        if (failed || !this.analysis) {
            barsEl.appendChild(el('div', 'deck-ratio-placeholder', failed ? 'Analysis unavailable' : 'Load a deck to see ratios'));
            return;
        }

        const counts = this.analysis.counts_by_type || {};

        for (const [type, tgt] of Object.entries(EDH_TARGETS)) {
            const count = counts[type] || 0;
            const maxRange = tgt.max;
            const status = ratioStatus(count, tgt.min, tgt.max);
            const pct = maxRange > 0 ? Math.min(100, (count / maxRange) * 100) : 0;

            const row = el('div', `deck-ratio-bar-row${this._activeTypeFilter === type ? ' active-filter' : ''}`);
            row.dataset.type = type;
            row.title = `${tgt.label}: ${count} (target: ${tgt.min}–${tgt.max})`;

            row.addEventListener('click', () => {
                if (this._activeTypeFilter === type) {
                    this._activeTypeFilter = null;
                    qs('#deck-type-filter').value = '';
                } else {
                    this._activeTypeFilter = type;
                    qs('#deck-type-filter').value = type;
                }
                this._runSearch();
                this._renderRatioDashboard();
            });

            const label = el('span', 'deck-ratio-bar-label', tgt.label);
            const track = el('div', 'deck-ratio-bar-track');
            const fill  = el('div', `deck-ratio-bar-fill status-${status}`);
            fill.style.width = `${pct}%`;

            // Min/max indicator marks
            if (maxRange > 0) {
                const minMark = el('div', 'deck-ratio-bar-target-min');
                minMark.style.left = `${(tgt.min / maxRange) * 100}%`;
                const maxMark = el('div', 'deck-ratio-bar-target-max');
                maxMark.style.left = `${Math.min(100, (tgt.max / maxRange) * 100)}%`;
                track.appendChild(minMark);
                track.appendChild(maxMark);
            }

            track.appendChild(fill);

            const nums = el('span', 'deck-ratio-bar-nums');
            const cur = el('span', 'deck-ratio-current', String(count));
            nums.appendChild(cur);
            nums.appendChild(document.createTextNode(` / ${tgt.target}`));

            row.appendChild(label);
            row.appendChild(track);
            row.appendChild(nums);
            barsEl.appendChild(row);
        }
    },

    _updateRatioBar(type) {
        // Lightweight update: recalculate count for one type and re-draw
        const counts = {};
        for (const card of this.deckCards) {
            const g = getCardTypeGroup(card.type_line);
            counts[g] = (counts[g] || 0) + (card.quantity || 1);
        }
        if (this.analysis) {
            this.analysis.counts_by_type = counts;
            this._renderRatioDashboard();
        }
    },

    _renderShortfalls() {
        const sfEl = qs('#deck-shortfalls');
        sfEl.innerHTML = '';
        const fixActions = qs('#deck-fix-actions');

        if (!this.analysis) {
            sfEl.appendChild(el('div', 'deck-ratio-placeholder', 'No analysis available'));
            fixActions.style.display = 'none';
            return;
        }

        const counts = this.analysis.counts_by_type || {};
        let hasIssues = false;

        for (const [type, tgt] of Object.entries(EDH_TARGETS)) {
            const count = counts[type] || 0;
            const status = ratioStatus(count, tgt.min, tgt.max);
            if (status === 'ok' || status === 'neutral') continue;

            hasIssues = true;
            const row = el('div', 'deck-shortfall-row');
            const icon = el('span', 'deck-shortfall-icon', status === 'low' ? '⬇' : status === 'over' ? '⬆' : '⚠');
            const text = el('span', 'deck-shortfall-text', `${tgt.label} (${count})`);
            const delta = tgt.target - count;
            const deltaEl = el('span', `deck-shortfall-delta ${delta > 0 ? 'needs-more' : 'over-count'}`);
            deltaEl.textContent = delta > 0 ? `+${delta} needed` : `${delta} over`;

            row.appendChild(icon);
            row.appendChild(text);
            row.appendChild(deltaEl);
            sfEl.appendChild(row);
        }

        if (!hasIssues) {
            const ok = el('div', 'deck-shortfall-row');
            ok.appendChild(el('span', 'deck-shortfall-icon', '✓'));
            ok.appendChild(el('span', 'deck-shortfall-text deck-text-success', 'Ratios look good!'));
            sfEl.appendChild(ok);
        }

        fixActions.style.display = hasIssues ? '' : 'none';
    },

    /* ── Fix My Ratios ────────────────────────────────────── */

    _bindRightColumn() {
        qs('#deck-autosuggest-btn').addEventListener('click', () => this._autoSuggestFromCollection());
        qs('#deck-edhrec-refresh-btn').addEventListener('click', () => this._loadEdhRecs());
        qs('#deck-edhrec-owned-only').addEventListener('change', (e) => {
            this.edhRecOwnedOnly = e.target.checked;
            this._loadEdhRecs();
        });
        qs('#deck-edhrec-bulk-owned-btn').addEventListener('click', () => this._bulkAddEdhRecOwned());
    },

    async _autoSuggestFromCollection() {
        if (!this.deckId) {
            ToastManager.show('Load a deck first.', 'warning');
            return;
        }
        const suggestEl = qs('#deck-fix-suggestions');
        suggestEl.style.display = 'block';
        suggestEl.innerHTML = '<div class="deck-loading-inline"><div class="deck-loading-spinner"></div>Finding suggestions...</div>';

        try {
            const recsResp = await apiGet(`/api/decks/${this.deckId}/recommended-from-collection?max_results=20`);
            // API returns {grouped: {type: [cards]}, total, shortfall_types}
            // Flatten grouped into array for rendering
            let recsList = [];
            if (recsResp && recsResp.grouped) {
                for (const cards of Object.values(recsResp.grouped)) {
                    recsList.push(...cards);
                }
            } else if (Array.isArray(recsResp)) {
                recsList = recsResp;
            }
            this._renderFixSuggestions(recsList);
        } catch (err) {
            suggestEl.innerHTML = `<div class="deck-ratio-placeholder" style="color:var(--lab-danger)">${err.message}</div>`;
        }
    },

    _renderFixSuggestions(recs) {
        const suggestEl = qs('#deck-fix-suggestions');
        suggestEl.innerHTML = '';

        if (!recs || recs.length === 0) {
            suggestEl.appendChild(el('div', 'deck-ratio-placeholder', 'No suggestions found in collection'));
            return;
        }

        // Group by type
        const groups = {};
        for (const r of recs) {
            const type = getCardTypeGroup(r.type_line || '');
            if (!groups[type]) groups[type] = [];
            groups[type].push(r);
        }

        for (const [type, cards] of Object.entries(groups)) {
            const group = el('div', 'deck-fix-group');

            const titleRow = el('div', 'deck-fix-group-title');
            titleRow.appendChild(el('span', null, type));
            const addAllBtn = el('button', 'deck-btn deck-btn-xs deck-btn-ghost', `Add all (${cards.length})`);
            addAllBtn.addEventListener('click', () => this._bulkAddSuggestions(cards));
            titleRow.appendChild(addAllBtn);
            group.appendChild(titleRow);

            for (const card of cards) {
                const row = el('div', 'deck-fix-card');

                const cardName = card.card_name || card.name || '';
                const nameEl = el('span', 'deck-fix-card-name', cardName);
                CardPreview.attach(nameEl, card.scryfall_id);

                const ownedEl = el('span', 'deck-fix-card-owned', `×${card.owned_qty || card.owned_quantity || 0}`);

                const addBtn = el('button', 'deck-btn deck-btn-xs deck-btn-accent', '+');
                addBtn.addEventListener('click', () => this.addCardToDeck(card.scryfall_id, cardName));

                row.appendChild(nameEl);
                row.appendChild(ownedEl);
                row.appendChild(addBtn);
                group.appendChild(row);
            }

            suggestEl.appendChild(group);
        }
    },

    async _bulkAddSuggestions(cards) {
        if (!this.deckId || cards.length === 0) return;

        const confirmed = await ConfirmDialog.show({
            title: 'Bulk Add Suggestions',
            message: `Add ${cards.length} suggested card(s) to the deck?`,
            changes: [{ label: 'Cards to add', before: 0, after: cards.length }],
        });
        if (!confirmed) return;

        let added = 0, skipped = 0;
        for (const card of cards) {
            try {
                await apiPost(`/api/decks/${this.deckId}/cards`, {
                    scryfall_id: card.scryfall_id,
                    card_name: card.card_name || card.name || '',
                    quantity: 1,
                });
                added++;
            } catch (_) {
                skipped++;
            }
        }

        const _cr2 = await apiGet(`/api/decks/${this.deckId}/cards`);
        this.deckCards = Array.isArray(_cr2) ? _cr2 : (_cr2.cards || []);
        this._renderCardGroups();
        this._loadAnalysis();
        ToastManager.show(`Added ${added} cards${skipped > 0 ? ` (${skipped} skipped)` : ''}`, 'success');
    },

    /* ── EDHREC Recommendations ──────────────────────────── */

    async _loadEdhRecs() {
        if (!this.deckId) return;
        const listEl = qs('#deck-edhrec-list');
        listEl.innerHTML = '<div class="deck-loading-inline"><div class="deck-loading-spinner"></div>Loading EDHREC data...</div>';

        try {
            const url = `/api/decks/${this.deckId}/edh-recs?only_owned=${this.edhRecOwnedOnly}&max_results=30`;
            const edhResp = await apiGet(url);
            this.edhRecData = Array.isArray(edhResp) ? edhResp : (edhResp.recommendations || []);
            this._renderEdhRecs();
        } catch (err) {
            listEl.innerHTML = `<div class="deck-ratio-placeholder" style="color:var(--lab-danger)">${err.message}</div>`;
        }
    },

    _renderEdhRecs() {
        const listEl = qs('#deck-edhrec-list');
        listEl.innerHTML = '';
        const bulkEl = qs('#deck-edhrec-bulk');

        if (!this.edhRecData || this.edhRecData.length === 0) {
            listEl.appendChild(el('div', 'deck-ratio-placeholder', 'No EDHREC recommendations available'));
            bulkEl.style.display = 'none';
            return;
        }

        const inDeckIds = new Set(this.deckCards.map(c => c.scryfall_id));
        let hasOwned = false;

        for (const card of this.edhRecData) {
            const inDeck = inDeckIds.has(card.scryfall_id);
            if (card.owned) hasOwned = true;

            const row = el('div', `deck-edhrec-card${inDeck ? ' in-deck' : ''}`);
            row.dataset.scryfallId = card.scryfall_id;

            const main = el('div', 'deck-edhrec-card-main');

            const nameEl = el('span', 'deck-edhrec-card-name', card.name);
            CardPreview.attach(nameEl, card.scryfall_id);

            const meta = el('div', 'deck-edhrec-card-meta');

            const pct = el('span', 'deck-edhrec-pct');
            pct.innerHTML = `<strong>${Math.round((card.inclusion_pct || 0) * 100)}%</strong> incl.`;

            const syn = el('span', `deck-edhrec-synergy${(card.synergy_score || 0) > 0 ? ' positive' : ''}`);
            syn.textContent = `syn: ${card.synergy_score != null ? (card.synergy_score > 0 ? '+' : '') + card.synergy_score.toFixed(2) : 'n/a'}`;

            const typeBadge = buildTypeBadge(card.type_line || '');

            meta.appendChild(pct);
            meta.appendChild(syn);
            meta.appendChild(typeBadge);

            if (card.owned) {
                const ownedBadge = el('span', 'deck-owned-badge', 'Owned');
                meta.appendChild(ownedBadge);
            }

            main.appendChild(nameEl);
            main.appendChild(meta);
            row.appendChild(main);

            if (!inDeck) {
                const addBtn = el('button', 'deck-btn deck-btn-xs deck-btn-accent', '+');
                addBtn.addEventListener('click', () => this.addCardToDeck(card.scryfall_id, card.name));
                row.appendChild(addBtn);
            } else {
                const inDeckLbl = el('span', 'deck-text-muted', '✓');
                inDeckLbl.style.fontSize = '11px';
                row.appendChild(inDeckLbl);
            }

            listEl.appendChild(row);
        }

        bulkEl.style.display = hasOwned ? '' : 'none';
    },

    async _bulkAddEdhRecOwned() {
        if (!this.deckId) return;
        const inDeckIds = new Set(this.deckCards.map(c => c.scryfall_id));
        const toAdd = this.edhRecData.filter(c => c.owned && !inDeckIds.has(c.scryfall_id));

        if (toAdd.length === 0) {
            ToastManager.show('No new owned cards to add.', 'warning');
            return;
        }

        const confirmed = await ConfirmDialog.show({
            title: 'Add All Owned EDHREC Recs',
            message: `Add ${toAdd.length} owned recommendation(s) to the deck?`,
            changes: [{ label: 'Cards to add', before: 0, after: toAdd.length }],
        });
        if (!confirmed) return;

        try {
            await apiPost(`/api/decks/${this.deckId}/bulk-add-recommended`, {
                source: 'edhrec',
                only_owned: true,
                respect_ratios: true,
            });
            const _cr3 = await apiGet(`/api/decks/${this.deckId}/cards`);
            this.deckCards = Array.isArray(_cr3) ? _cr3 : (_cr3.cards || []);
            this._renderCardGroups();
            this._loadAnalysis();
            this._renderEdhRecs();
            ToastManager.show(`Added owned EDHREC recommendations`, 'success');
        } catch (err) {
            // Fallback: add one by one
            let added = 0, skipped = 0;
            for (const card of toAdd) {
                try {
                    await apiPost(`/api/decks/${this.deckId}/cards`, {
                        scryfall_id: card.scryfall_id,
                        card_name: card.name || '',
                        quantity: 1,
                    });
                    added++;
                } catch (_) {
                    skipped++;
                }
            }
            const _cr4 = await apiGet(`/api/decks/${this.deckId}/cards`);
            this.deckCards = Array.isArray(_cr4) ? _cr4 : (_cr4.cards || []);
            this._renderCardGroups();
            this._loadAnalysis();
            this._renderEdhRecs();
            ToastManager.show(`Added ${added}${skipped > 0 ? ` (${skipped} skipped)` : ''}`, 'success');
        }
    },

    /* ── Collapsible Panels ───────────────────────────────── */

    _bindCollapsible() {
        qsa('.deck-panel-header-collapsible').forEach(header => {
            const targetId = header.dataset.target;
            const body = qs(`#${targetId}`);
            const arrow = qs('.deck-collapse-arrow', header);
            if (!body) return;
            body.style.maxHeight = body.scrollHeight + 'px';

            header.addEventListener('click', () => {
                const isCollapsed = body.classList.toggle('collapsed');
                arrow.classList.toggle('collapsed', isCollapsed);
                body.style.maxHeight = isCollapsed ? '0px' : body.scrollHeight + 1000 + 'px';
            });
        });
    },

    /* ── New Deck Modal ───────────────────────────────────── */

    _bindNewDeckModal() {
        qs('#deck-new-modal-close').addEventListener('click', () => this._closeNewDeckModal());
        qs('#deck-new-cancel').addEventListener('click', () => this._closeNewDeckModal());
        qs('#deck-new-modal').addEventListener('click', (e) => {
            if (e.target === qs('#deck-new-modal')) this._closeNewDeckModal();
        });
        qs('#deck-new-create').addEventListener('click', () => this._createNewDeck());

        qs('#deck-clear-commander-btn').addEventListener('click', () => {
            this.newCommanderScryfallId = null;
            this.newCommanderName = '';
            qs('#deck-new-commander-selected').style.display = 'none';
            qs('#deck-new-commander-search').value = '';
        });

        // Commander autocomplete in new deck modal
        const cmdSearch = qs('#deck-new-commander-search');
        const cmdDropdown = qs('#deck-new-commander-dropdown');
        let _cmdSuggestions = [];
        let _cmdActiveIndex = -1;

        const debouncedCmdSearch = debounce(async (q) => {
            if (!q || q.length < 2) { cmdDropdown.style.display = 'none'; return; }
            // Search Scryfall for legendary creatures
            const cards = await scryfallSearchCards(`${q} is:commander`);
            _cmdSuggestions = cards.slice(0, 8);
            _cmdActiveIndex = -1;
            this._renderCommanderDropdown(_cmdSuggestions, _cmdActiveIndex, cmdDropdown);
        }, 350);

        cmdSearch.addEventListener('input', (e) => debouncedCmdSearch(e.target.value.trim()));

        cmdSearch.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowDown') {
                _cmdActiveIndex = Math.min(_cmdActiveIndex + 1, _cmdSuggestions.length - 1);
                this._renderCommanderDropdown(_cmdSuggestions, _cmdActiveIndex, cmdDropdown);
                e.preventDefault();
            } else if (e.key === 'ArrowUp') {
                _cmdActiveIndex = Math.max(_cmdActiveIndex - 1, -1);
                this._renderCommanderDropdown(_cmdSuggestions, _cmdActiveIndex, cmdDropdown);
                e.preventDefault();
            } else if (e.key === 'Enter' && _cmdActiveIndex >= 0) {
                e.preventDefault();
                const card = _cmdSuggestions[_cmdActiveIndex];
                this._selectCommanderOption(card, cmdSearch, cmdDropdown);
            } else if (e.key === 'Escape') {
                cmdDropdown.style.display = 'none';
            }
        });

        cmdDropdown.addEventListener('click', (e) => {
            const item = e.target.closest('.deck-commander-option');
            if (!item) return;
            const idx = parseInt(item.dataset.index, 10);
            const card = _cmdSuggestions[idx];
            if (card) this._selectCommanderOption(card, cmdSearch, cmdDropdown);
        });

        document.addEventListener('click', (e) => {
            if (!cmdSearch.contains(e.target) && !cmdDropdown.contains(e.target)) {
                cmdDropdown.style.display = 'none';
            }
        });
    },

    _renderCommanderDropdown(cards, activeIndex, dropdown) {
        dropdown.innerHTML = '';
        if (cards.length === 0) { dropdown.style.display = 'none'; return; }
        for (let i = 0; i < cards.length; i++) {
            const card = cards[i];
            const item = el('div', `deck-commander-option${i === activeIndex ? ' active' : ''}`);
            item.dataset.index = i;

            const nameEl = el('span', 'deck-commander-option-name', card.name);
            const colorWrap = el('span', 'deck-commander-option-color');
            const ci = card.color_identity || [];
            for (const c of ci) {
                colorWrap.appendChild(buildColorChip(c));
            }

            item.appendChild(nameEl);
            item.appendChild(colorWrap);
            dropdown.appendChild(item);
        }
        dropdown.style.display = 'block';
    },

    _selectCommanderOption(card, input, dropdown) {
        this.newCommanderScryfallId = card.id;
        this.newCommanderName = card.name;
        input.value = '';
        dropdown.style.display = 'none';

        qs('#deck-new-commander-name').textContent = card.name;
        qs('#deck-new-commander-selected').style.display = 'flex';
    },

    _openNewDeckModal(commanderOnly = false) {
        const modal = qs('#deck-new-modal');
        this.newCommanderScryfallId = null;
        this.newCommanderName = '';
        qs('#deck-new-name').value = commanderOnly ? (this.deckName || '') : '';
        qs('#deck-new-commander-search').value = '';
        qs('#deck-new-commander-selected').style.display = 'none';
        modal.style.display = 'flex';
        if (!commanderOnly) qs('#deck-new-name').focus();
        else qs('#deck-new-commander-search').focus();
    },

    _closeNewDeckModal() {
        qs('#deck-new-modal').style.display = 'none';
        this.newCommanderScryfallId = null;
        this.newCommanderName = '';
    },

    async _createNewDeck() {
        const name = qs('#deck-new-name').value.trim();
        if (!name) {
            qs('#deck-new-name').focus();
            ToastManager.show('Please enter a deck name.', 'warning');
            return;
        }

        const payload = {
            name,
            commander_scryfall_id: this.newCommanderScryfallId || undefined,
            commander_name: this.newCommanderName || undefined,
        };

        try {
            const deck = await apiPost('/api/decks', payload);
            this.deckId = deck.id;
            this.deckName = deck.name;
            this._closeNewDeckModal();

            // Add commander card BEFORE loading deck so it renders correctly
            if (this.newCommanderScryfallId) {
                try {
                    await apiPost(`/api/decks/${deck.id}/cards`, {
                        scryfall_id: this.newCommanderScryfallId,
                        card_name: this.newCommanderName || '',
                        quantity: 1,
                        is_commander: 1,
                    });
                } catch (cmdErr) {
                    console.warn('Failed to add commander card:', cmdErr);
                }
            }

            await this.loadDecks();
            await this.loadDeck(deck.id);
            ToastManager.show(`Created deck "${deck.name}"`, 'success');
        } catch (err) {
            ToastManager.show(`Failed to create deck: ${err.message}`, 'error');
        }
    },

    /* ── Import ───────────────────────────────────────────── */

    _importFileText: '',

    _initImportModal() {
        const modal = qs('#deck-import-modal');
        const closeModal = () => { modal.style.display = 'none'; };
        qs('#deck-import-modal-close').addEventListener('click', closeModal);
        qs('#deck-import-cancel').addEventListener('click', closeModal);
        modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

        // Tabs
        for (const tab of document.querySelectorAll('.deck-import-tab')) {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.deck-import-tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                const which = tab.dataset.tab;
                qs('#deck-import-paste-panel').style.display = which === 'paste' ? '' : 'none';
                qs('#deck-import-file-panel').style.display = which === 'file' ? '' : 'none';
            });
        }

        // File upload
        const dropzone = qs('#deck-import-dropzone');
        const fileInput = qs('#deck-import-file');
        dropzone.addEventListener('click', () => fileInput.click());
        dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
        dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            if (e.dataTransfer.files.length) this._handleImportFile(e.dataTransfer.files[0]);
        });
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length) this._handleImportFile(fileInput.files[0]);
        });

        // Mode radio toggles name row visibility
        for (const radio of document.querySelectorAll('input[name="import-mode"]')) {
            radio.addEventListener('change', () => {
                const mode = document.querySelector('input[name="import-mode"]:checked').value;
                qs('#deck-import-new-name-row').style.display = mode === 'new' ? '' : 'none';
            });
        }

        // Go button
        qs('#deck-import-go').addEventListener('click', () => this._doImport());
    },

    _handleImportFile(file) {
        const reader = new FileReader();
        reader.onload = () => {
            this._importFileText = reader.result;
            qs('#deck-import-file-name').textContent = file.name + ' (' + (reader.result.split('\n').length) + ' lines)';
        };
        reader.readAsText(file);
    },

    _openImportModal() {
        const modal = qs('#deck-import-modal');
        qs('#deck-import-textarea').value = '';
        qs('#deck-import-name').value = '';
        qs('#deck-import-file-name').textContent = '';
        qs('#deck-import-file').value = '';
        qs('#deck-import-progress').style.display = 'none';
        qs('#deck-import-result').style.display = 'none';
        qs('#deck-import-go').disabled = false;
        qs('#deck-import-go').textContent = 'Import';
        this._importFileText = '';

        // If no deck loaded, default to "new"
        if (!this.deckId) {
            document.querySelector('input[name="import-mode"][value="new"]').checked = true;
            qs('#deck-import-new-name-row').style.display = '';
        }

        modal.style.display = 'flex';
        qs('#deck-import-textarea').focus();
    },

    async _doImport() {
        const activeTab = document.querySelector('.deck-import-tab.active').dataset.tab;
        let text = '';

        if (activeTab === 'paste') {
            text = qs('#deck-import-textarea').value.trim();
        } else {
            text = this._importFileText;
        }

        if (!text) {
            ToastManager.show('No decklist to import.', 'warning');
            return;
        }

        const mode = document.querySelector('input[name="import-mode"]:checked').value;
        const importBtn = qs('#deck-import-go');
        importBtn.disabled = true;
        importBtn.textContent = 'Importing...';

        qs('#deck-import-progress').style.display = 'block';
        qs('#deck-import-progress-bar').style.width = '30%';
        qs('#deck-import-result').style.display = 'none';

        try {
            let result;

            if (mode === 'new') {
                const name = qs('#deck-import-name').value.trim();
                const res = await fetch('/api/decks/import-new', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text, name }),
                });
                result = await res.json();
                if (result.error) throw new Error(result.error);

                qs('#deck-import-progress-bar').style.width = '100%';
                this._showImportResult(result);

                // Load the new deck
                await this.loadDecks();
                await this.loadDeck(result.deckId);
                ToastManager.show('Imported "' + result.deckName + '" (' + result.added + ' cards)', 'success');

            } else {
                // add or replace into current deck
                if (!this.deckId) {
                    ToastManager.show('Select or create a deck first, or use "Create new deck" mode.', 'warning');
                    importBtn.disabled = false;
                    importBtn.textContent = 'Import';
                    qs('#deck-import-progress').style.display = 'none';
                    return;
                }

                const clearFirst = mode === 'replace';
                const res = await fetch('/api/decks/' + this.deckId + '/import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text, clearFirst }),
                });
                result = await res.json();
                if (result.error) throw new Error(result.error);

                qs('#deck-import-progress-bar').style.width = '100%';
                this._showImportResult(result);

                // Reload current deck
                await this.loadDeck(this.deckId);
                const msg = 'Imported ' + result.added + ' cards' + (result.failed > 0 ? ' (' + result.failed + ' not found)' : '');
                ToastManager.show(msg, result.failed > 0 ? 'warning' : 'success');
            }

            // Close modal after short delay
            setTimeout(() => {
                qs('#deck-import-modal').style.display = 'none';
            }, 1500);

        } catch (err) {
            ToastManager.show('Import failed: ' + err.message, 'error');
        } finally {
            importBtn.disabled = false;
            importBtn.textContent = 'Import';
        }
    },

    _showImportResult(result) {
        const el = qs('#deck-import-result');
        el.style.display = 'block';

        let html = '<div style="font-size: 13px;">';
        html += '<span style="color: #3fb950; font-weight: 600;">' + result.added + ' cards imported</span>';
        if (result.failed > 0) {
            html += ' &mdash; <span style="color: #f85149;">' + result.failed + ' not found</span>';
            html += '<div style="margin-top: 6px; color: #8b949e; font-size: 12px;">';
            html += 'Not found: ' + (result.failedNames || []).join(', ');
            html += '</div>';
        }
        html += '</div>';
        el.innerHTML = html;
    },

    /* ── Export ───────────────────────────────────────────── */

    _exportDck() {
        if (!this.deckId || this.deckCards.length === 0) {
            ToastManager.show('No deck loaded.', 'warning');
            return;
        }
        const lines = [];
        const commanders = this.deckCards.filter(c => c.is_commander);
        const nonCmd = this.deckCards.filter(c => !c.is_commander);

        if (commanders.length > 0) {
            lines.push('[Commander]');
            for (const c of commanders) {
                lines.push(`1 ${c.card_name}`);
            }
            lines.push('');
        }

        lines.push('[Deck]');
        for (const c of nonCmd) {
            lines.push(`${c.quantity || 1} ${c.card_name}`);
        }

        const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${(this.deckName || 'deck').replace(/[^a-z0-9_-]/gi, '_')}.dck`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        ToastManager.show('Exported .dck file', 'success');
    },

    async _exportToSim() {
        if (!this.deckId) {
            ToastManager.show('Load a deck first.', 'warning');
            return;
        }
        const btn = qs('#deck-sim-btn');
        btn.disabled = true;
        const originalText = btn.innerHTML;
        btn.innerHTML = '<div class="deck-loading-spinner"></div> Simulating...';

        try {
            // Run a quick 10-game sim directly
            const res = await fetch('/api/sim/run-from-deck', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ deckId: this.deckId, numGames: 10, recordLogs: false }),
            });
            const ct = res.headers.get('content-type') || '';
            if (!ct.includes('application/json')) {
                const txt = await res.text();
                throw new Error('Server returned non-JSON (HTTP ' + res.status + '): ' + txt.substring(0, 120));
            }
            const startData = await res.json();
            if (startData.error) throw new Error(startData.error);

            // Poll until done
            const simId = startData.simId;
            let done = false;
            while (!done) {
                await new Promise(r => setTimeout(r, 300));
                const statusRes = await fetch('/api/sim/status?simId=' + simId);
                if (!statusRes.ok) throw new Error('Status poll failed: HTTP ' + statusRes.status);
                const status = await statusRes.json();
                btn.innerHTML = '<div class="deck-loading-spinner"></div> ' + status.completed + '/' + status.total;
                if (status.status === 'complete') {
                    done = true;
                    const resultRes = await fetch('/api/sim/result?simId=' + simId);
                    if (!resultRes.ok) throw new Error('Result fetch failed: HTTP ' + resultRes.status);
                    const result = await resultRes.json();
                    const s = result.summary;
                    ToastManager.show(
                        `Win Rate: ${s.winRate}% (${s.wins}W/${s.losses}L) | Avg ${s.avgTurns} turns | ${s.elapsedSeconds}s`,
                        s.winRate >= 50 ? 'success' : 'warning',
                        6000
                    );
                    // Offer to open full simulator
                    if (confirm(`Quick sim: ${s.winRate}% win rate (${s.wins}/${s.totalGames}).\n\nOpen the full Simulator page for detailed results?`)) {
                        window.location.href = 'simulator.html';
                    }
                } else if (status.status === 'error') {
                    throw new Error(status.error || 'Simulation failed');
                }
            }
        } catch (err) {
            ToastManager.show(`Simulation failed: ${err.message}`, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    },

    /* ── AI Panels (Perplexity) ──────────────────────────── */


    /* ── Export Deck to Forge Sim Folder ────────────────── */

    async _exportDckToSim() {
        if (!this.deckId) {
            ToastManager.show('Load a deck first.', 'warning');
            return;
        }
        const btn = qs('#deck-export-sim-btn');
        btn.disabled = true;
        const originalText = btn.innerHTML;
        btn.innerHTML = '<div class="deck-loading-spinner"></div> Exporting...';

        try {
            const res = await fetch('/api/decks/' + this.deckId + '/export-to-sim', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            const ct = res.headers.get('content-type') || '';
            if (!ct.includes('application/json')) {
                const txt = await res.text();
                throw new Error('Server returned non-JSON (HTTP ' + res.status + '): ' + txt.substring(0, 120));
            }
            const data = await res.json();
            if (!data.success) throw new Error(data.detail || 'Export failed');

            ToastManager.show(
                'Exported "' + data.deckName + '" (' + data.totalCards + ' cards) to Forge sim folder',
                'success',
                5000
            );
        } catch (err) {
            ToastManager.show('Export failed: ' + err.message, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    },

    async _checkPplxStatus() {
        try {
            const status = await apiGet('/api/pplx/status');
            this.pplxConfigured = status && status.configured;
        } catch {
            this.pplxConfigured = false;
        }
        const researchPanel = qs('#deck-ai-research-panel');
        const generatePanel = qs('#deck-ai-generate-panel');
        if (researchPanel) researchPanel.style.display = this.pplxConfigured ? '' : 'none';
        if (generatePanel) generatePanel.style.display = this.pplxConfigured ? '' : 'none';
    },

    _bindAIPanels() {
        // Research button
        const researchBtn = qs('#ai-research-btn');
        if (researchBtn) {
            researchBtn.addEventListener('click', () => this._runAIResearch());
        }

        // Generate button
        const genBtn = qs('#ai-gen-btn');
        if (genBtn) {
            genBtn.addEventListener('click', () => this._runAIGenerate());
        }

        // Commander autocomplete for AI Generate
        this._bindAIGenCommanderSearch();
    },

    /** Update the research button state — call after deck changes */
    _updateAIResearchBtn() {
        const btn = qs('#ai-research-btn');
        if (!btn) return;
        btn.disabled = !this.deckId || !this.pplxConfigured;
    },

    /* ── AI Research Flow ─────────────────────────────────── */

    async _runAIResearch() {
        if (!this.deckId) {
            ToastManager.show('Load a deck first.', 'warning');
            return;
        }
        const btn = qs('#ai-research-btn');
        const loading = qs('#ai-research-loading');
        const results = qs('#ai-research-results');
        const controls = qs('#deck-ai-research-body .deck-ai-controls');

        const goal = qs('#ai-research-goal').value.trim() || undefined;
        const budgetRaw = qs('#ai-research-budget').value;
        const budget = budgetRaw ? parseFloat(budgetRaw) : undefined;
        const omitRaw = qs('#ai-research-omit').value.trim();
        const omitCards = omitRaw ? omitRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
        const useCollection = qs('#ai-research-use-collection').checked;

        btn.disabled = true;
        loading.style.display = 'flex';
        results.style.display = 'none';
        results.innerHTML = '';

        try {
            const data = await apiPost('/api/deck-research', {
                deck_id: this.deckId,
                goal,
                budget_usd: budget,
                omit_cards: omitCards,
                use_collection: useCollection,
            });

            if (data.error) {
                results.innerHTML = '<div class="deck-ai-error">AI returned an error: ' + this._esc(data.error) + '</div>';
                results.style.display = 'block';
                return;
            }

            this._renderResearchResults(data, results);
            results.style.display = 'block';

            // Expand the panel body max-height so results are visible
            const body = qs('#deck-ai-research-body');
            if (body) body.style.maxHeight = body.scrollHeight + 2000 + 'px';
        } catch (err) {
            results.innerHTML = '<div class="deck-ai-error">Research failed: ' + this._esc(err.message) + '</div>';
            results.style.display = 'block';
            ToastManager.show('AI research failed: ' + err.message, 'error');
        } finally {
            btn.disabled = false;
            loading.style.display = 'none';
        }
    },

    _renderResearchResults(data, container) {
        let html = '';
        const esc = (t) => this._esc(t);

        // ── Header: Rating + Bracket + Archetype ──────────────────
        const ratingNum = parseInt(data.overall_rating, 10);
        const ratingClass = isNaN(ratingNum) ? '' : (ratingNum >= 7 ? 'high' : ratingNum >= 4 ? 'mid' : 'low');
        const bracketLvl = data.bracket_level && data.bracket_level.level;
        const bracketCls = bracketLvl <= 1 ? 'bracket-1' : bracketLvl <= 2 ? 'bracket-2' : bracketLvl <= 3 ? 'bracket-3' : 'bracket-4';

        html += '<div class="deck-ai-header-row">';
        html += '<div class="deck-ai-rating"><span class="deck-ai-rating-num ' + ratingClass + '">' + (isNaN(ratingNum) ? '?' : ratingNum) + '</span><span class="deck-ai-rating-sublabel">/10</span></div>';
        if (bracketLvl) html += '<span class="deck-ai-bracket-badge ' + bracketCls + '">Bracket ' + bracketLvl + '</span>';
        if (data.archetype) html += '<span class="deck-ai-archetype-badge">' + esc(data.archetype.replace('_', ' ')) + '</span>';
        html += '</div>';

        // Rating explanation
        if (data.rating_explanation) {
            html += '<div class="deck-ai-notes deck-ai-rating-explanation">' + esc(data.rating_explanation) + '</div>';
        }

        // ── Deck Description ──────────────────────────────────────
        if (data.deck_description) {
            html += '<div class="deck-ai-section">';
            html += '<div class="deck-ai-section-title">Deck Overview</div>';
            html += '<div class="deck-ai-strategy">' + esc(data.deck_description) + '</div>';
            html += '</div>';
        }

        // ── Bracket Details ───────────────────────────────────────
        if (data.bracket_level) {
            const b = data.bracket_level;
            html += '<div class="deck-ai-section">';
            html += '<div class="deck-ai-section-title">Bracket Assessment</div>';
            html += '<div class="deck-ai-bracket-detail">';
            if (b.reasoning) html += '<div class="deck-ai-notes"><strong>Why Bracket ' + (b.level || '?') + ':</strong> ' + esc(b.reasoning) + '</div>';
            if (b.power_ceiling) html += '<div class="deck-ai-notes"><strong>Power Ceiling:</strong> ' + esc(b.power_ceiling) + '</div>';
            html += '</div></div>';
        }

        // ── Win Conditions ────────────────────────────────────────
        if (data.win_conditions && data.win_conditions.length) {
            html += '<div class="deck-ai-section">';
            html += '<div class="deck-ai-section-title">Win Conditions</div>';
            for (const wc of data.win_conditions) {
                const relCls = wc.reliability === 'high' ? 'high' : wc.reliability === 'medium' ? 'mid' : 'low';
                html += '<div class="deck-ai-wincon">';
                html += '<div class="deck-ai-wincon-header">';
                html += '<span class="deck-ai-wincon-name">' + esc(wc.name) + '</span>';
                if (wc.reliability) html += '<span class="deck-ai-reliability-badge ' + relCls + '">' + esc(wc.reliability) + '</span>';
                html += '</div>';
                if (wc.cards_involved && wc.cards_involved.length) {
                    html += '<div class="deck-ai-wincon-cards">';
                    for (const cn of wc.cards_involved) html += '<span class="deck-ai-card-chip">' + esc(cn) + '</span>';
                    html += '</div>';
                }
                if (wc.description) html += '<div class="deck-ai-notes">' + esc(wc.description) + '</div>';
                html += '</div>';
            }
            html += '</div>';
        }

        // ── Synergy Packages ──────────────────────────────────────
        if (data.synergy_packages && data.synergy_packages.length) {
            html += '<div class="deck-ai-section">';
            html += '<div class="deck-ai-section-title">Synergy Packages</div>';
            for (const sp of data.synergy_packages) {
                const strCls = sp.strength === 'strong' ? 'high' : sp.strength === 'moderate' ? 'mid' : 'low';
                html += '<div class="deck-ai-synergy-pkg">';
                html += '<div class="deck-ai-synergy-header">';
                html += '<span class="deck-ai-synergy-name">' + esc(sp.package_name) + '</span>';
                if (sp.strength) html += '<span class="deck-ai-reliability-badge ' + strCls + '">' + esc(sp.strength) + '</span>';
                html += '</div>';
                if (sp.cards && sp.cards.length) {
                    html += '<div class="deck-ai-wincon-cards">';
                    for (const cn of sp.cards) html += '<span class="deck-ai-card-chip">' + esc(cn) + '</span>';
                    html += '</div>';
                }
                if (sp.description) html += '<div class="deck-ai-notes">' + esc(sp.description) + '</div>';
                html += '</div>';
            }
            html += '</div>';
        }

        // ── Threat Assessment (game phases) ───────────────────────
        if (data.threat_assessment) {
            const ta = data.threat_assessment;
            html += '<div class="deck-ai-section">';
            html += '<div class="deck-ai-section-title">Threat Assessment</div>';
            html += '<div class="deck-ai-phases">';
            if (ta.early_game) html += '<div class="deck-ai-phase"><span class="deck-ai-phase-label">Early (T1-3)</span><span class="deck-ai-phase-text">' + esc(ta.early_game) + '</span></div>';
            if (ta.mid_game) html += '<div class="deck-ai-phase"><span class="deck-ai-phase-label">Mid (T4-7)</span><span class="deck-ai-phase-text">' + esc(ta.mid_game) + '</span></div>';
            if (ta.late_game) html += '<div class="deck-ai-phase"><span class="deck-ai-phase-label">Late (T8+)</span><span class="deck-ai-phase-text">' + esc(ta.late_game) + '</span></div>';
            if (ta.vulnerability) html += '<div class="deck-ai-phase deck-ai-phase-vuln"><span class="deck-ai-phase-label">Vulnerable To</span><span class="deck-ai-phase-text">' + esc(ta.vulnerability) + '</span></div>';
            html += '</div></div>';
        }

        // ── Strengths / Weaknesses ────────────────────────────────
        if ((data.strengths && data.strengths.length) || (data.weaknesses && data.weaknesses.length)) {
            html += '<div class="deck-ai-section deck-ai-sw-grid">';
            if (data.strengths && data.strengths.length) {
                html += '<div class="deck-ai-sw-col">';
                html += '<div class="deck-ai-section-title deck-ai-sw-title-good">Strengths</div>';
                html += '<ul class="deck-ai-list">';
                for (const s of data.strengths) html += '<li>' + esc(s) + '</li>';
                html += '</ul></div>';
            }
            if (data.weaknesses && data.weaknesses.length) {
                html += '<div class="deck-ai-sw-col">';
                html += '<div class="deck-ai-section-title deck-ai-sw-title-bad">Weaknesses</div>';
                html += '<ul class="deck-ai-list">';
                for (const w of data.weaknesses) html += '<li>' + esc(w) + '</li>';
                html += '</ul></div>';
            }
            html += '</div>';
        }

        // ── Role Gaps ────────────────────────────────────────────
        if (data.role_gaps && typeof data.role_gaps === 'object') {
            html += '<div class="deck-ai-section">';
            html += '<div class="deck-ai-section-title">Role Analysis</div>';
            html += '<div class="deck-ai-role-gaps">';
            for (const [role, info] of Object.entries(data.role_gaps)) {
                if (!info || typeof info !== 'object') continue;
                const cur = info.current || 0;
                const rec = info.recommended || 0;
                const diff = cur - rec;
                const barPct = rec > 0 ? Math.min(100, Math.round((cur / rec) * 100)) : 100;
                const barCls = diff >= 0 ? 'good' : (diff >= -2 ? 'warn' : 'bad');
                html += '<div class="deck-ai-role-row">';
                html += '<span class="deck-ai-role-name">' + esc(role.replace('_', ' ')) + '</span>';
                html += '<div class="deck-ai-role-bar-wrap"><div class="deck-ai-role-bar ' + barCls + '" style="width:' + barPct + '%"></div></div>';
                html += '<span class="deck-ai-role-nums">' + cur + '/' + rec + '</span>';
                html += '</div>';
                if (info.note) html += '<div class="deck-ai-role-note">' + esc(info.note) + '</div>';
            }
            html += '</div></div>';
        }

        // ── Mana Analysis ────────────────────────────────────────
        if (data.mana_analysis && typeof data.mana_analysis === 'object') {
            const ma = data.mana_analysis;
            html += '<div class="deck-ai-section">';
            html += '<div class="deck-ai-section-title">Mana Base Analysis</div>';
            if (ma.land_count) html += '<div class="deck-ai-notes"><strong>Lands:</strong> ' + esc(ma.land_count) + '</div>';
            if (ma.color_fixing) html += '<div class="deck-ai-notes"><strong>Color Fixing:</strong> ' + esc(ma.color_fixing) + '</div>';
            if (ma.ramp_package) html += '<div class="deck-ai-notes"><strong>Ramp:</strong> ' + esc(ma.ramp_package) + '</div>';
            if (ma.curve_assessment) html += '<div class="deck-ai-notes"><strong>Curve:</strong> ' + esc(ma.curve_assessment) + '</div>';
            if (ma.problem_cards && ma.problem_cards.length) {
                html += '<div class="deck-ai-notes"><strong>Problem Cards:</strong> ';
                html += ma.problem_cards.map(c => '<span class="deck-ai-card-chip deck-ai-card-chip-warn">' + esc(c) + '</span>').join(' ');
                html += '</div>';
            }
            html += '</div>';
        }

        // ── Cuts ─────────────────────────────────────────────────
        if (data.cuts && data.cuts.length) {
            html += '<div class="deck-ai-section">';
            html += '<div class="deck-ai-section-title">Suggested Cuts (' + data.cuts.length + ')</div>';
            for (const c of data.cuts) {
                const sevCls = c.severity === 'must_cut' ? 'sev-must' : c.severity === 'should_cut' ? 'sev-should' : 'sev-consider';
                html += '<div class="deck-ai-card-row cut-row">';
                html += '<span class="deck-ai-card-name">' + esc(c.name) + '</span>';
                if (c.severity) html += '<span class="deck-ai-severity-badge ' + sevCls + '">' + esc(c.severity.replace('_', ' ')) + '</span>';
                html += '</div>';
                if (c.reason) html += '<div class="deck-ai-card-detail">' + esc(c.reason) + '</div>';
            }
            html += '</div>';
        }

        // ── Adds ─────────────────────────────────────────────────
        if (data.adds && data.adds.length) {
            html += '<div class="deck-ai-section">';
            html += '<div class="deck-ai-section-title">Suggested Adds (' + data.adds.length + ')</div>';
            for (const a of data.adds) {
                const priCls = a.priority === 'critical' ? 'pri-critical' : a.priority === 'high' ? 'pri-high' : a.priority === 'medium' ? 'pri-medium' : 'pri-nice';
                html += '<div class="deck-ai-card-row add-row" data-card-name="' + esc(a.name) + '" data-scryfall-id="' + (a.scryfall_id || '') + '">';
                html += '<span class="deck-ai-card-name">' + esc(a.name) + '</span>';
                if (a.role) html += '<span class="deck-ai-card-role">' + esc(a.role.replace('_', ' ')) + '</span>';
                if (a.priority) html += '<span class="deck-ai-priority-badge ' + priCls + '">' + esc(a.priority.replace('_', ' ')) + '</span>';
                if (a.from_collection) html += '<span class="deck-ai-card-owned-badge">Owned</span>';
                if (a.estimated_price_usd) html += '<span class="deck-ai-card-price">$' + a.estimated_price_usd.toFixed(2) + '</span>';
                if (a.scryfall_id) html += '<button class="deck-ai-card-add-btn" data-sfid="' + a.scryfall_id + '" data-name="' + esc(a.name) + '">+</button>';
                html += '</div>';
                // Reason + synergy line
                let detail = '';
                if (a.reason) detail += esc(a.reason);
                if (a.synergy_with && a.synergy_with.length) {
                    detail += (detail ? ' ' : '') + '<span class="deck-ai-synergy-tag">Synergizes with: ' + a.synergy_with.map(c => esc(c)).join(', ') + '</span>';
                }
                if (detail) html += '<div class="deck-ai-card-detail">' + detail + '</div>';
            }
            if (data.adds_total_usd) {
                html += '<div class="deck-ai-total"><span>Total adds cost</span><strong>$' + data.adds_total_usd.toFixed(2) + '</strong></div>';
            }
            html += '</div>';
        }

        // ── Strategy Notes ────────────────────────────────────────
        if (data.strategy_notes) {
            html += '<div class="deck-ai-section">';
            html += '<div class="deck-ai-section-title">Strategy Notes</div>';
            html += '<div class="deck-ai-strategy">' + esc(data.strategy_notes) + '</div>';
            html += '</div>';
        }

        container.innerHTML = html;

        // Bind add buttons
        qsa('.deck-ai-card-add-btn', container).forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const sfid = btn.dataset.sfid;
                const name = btn.dataset.name;
                if (sfid) this.addCardToDeck(sfid, name);
            });
        });

        // Attach card preview on hover for add rows with scryfall_id
        qsa('.deck-ai-card-row[data-scryfall-id]', container).forEach(row => {
            const sfid = row.dataset.scryfallId;
            if (sfid) {
                const nameEl = qs('.deck-ai-card-name', row);
                if (nameEl) CardPreview.attach(nameEl, sfid);
            }
        });
    },

    /* ── AI Generate Flow ─────────────────────────────────── */

    _bindAIGenCommanderSearch() {
        const input = qs('#ai-gen-commander');
        const dropdown = qs('#ai-gen-commander-dropdown');
        if (!input || !dropdown) return;

        const debouncedSearch = debounce(async (q) => {
            if (!q || q.length < 2) { dropdown.style.display = 'none'; return; }
            const cards = await scryfallSearchCards(q + ' is:commander');
            this._aiGenSuggestions = cards.slice(0, 8);
            this._aiGenActiveIndex = -1;
            this._renderAIGenDropdown();
        }, 350);

        input.addEventListener('input', (e) => {
            // Clear selection if user edits after selecting
            this.aiGenCommanderName = '';
            const sel = qs('#ai-gen-commander-selected');
            if (sel) sel.style.display = 'none';
            debouncedSearch(e.target.value.trim());
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowDown') {
                this._aiGenActiveIndex = Math.min(this._aiGenActiveIndex + 1, this._aiGenSuggestions.length - 1);
                this._renderAIGenDropdown();
                e.preventDefault();
            } else if (e.key === 'ArrowUp') {
                this._aiGenActiveIndex = Math.max(this._aiGenActiveIndex - 1, -1);
                this._renderAIGenDropdown();
                e.preventDefault();
            } else if (e.key === 'Enter' && this._aiGenActiveIndex >= 0) {
                e.preventDefault();
                const card = this._aiGenSuggestions[this._aiGenActiveIndex];
                if (card) this._selectAIGenCommander(card);
            } else if (e.key === 'Escape') {
                dropdown.style.display = 'none';
            }
        });

        dropdown.addEventListener('click', (e) => {
            const item = e.target.closest('.deck-ai-commander-option');
            if (!item) return;
            const idx = parseInt(item.dataset.index, 10);
            const card = this._aiGenSuggestions[idx];
            if (card) this._selectAIGenCommander(card);
        });

        document.addEventListener('click', (e) => {
            if (!input.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.style.display = 'none';
            }
        });
    },

    _renderAIGenDropdown() {
        const dropdown = qs('#ai-gen-commander-dropdown');
        dropdown.innerHTML = '';
        if (this._aiGenSuggestions.length === 0) { dropdown.style.display = 'none'; return; }
        for (let i = 0; i < this._aiGenSuggestions.length; i++) {
            const card = this._aiGenSuggestions[i];
            const item = el('div', 'deck-ai-commander-option' + (i === this._aiGenActiveIndex ? ' active' : ''));
            item.dataset.index = i;

            const nameEl = el('span', 'deck-ai-commander-option-name', card.name);
            const colorWrap = el('span', 'deck-commander-option-color');
            for (const c of (card.color_identity || [])) {
                colorWrap.appendChild(buildColorChip(c));
            }
            item.appendChild(nameEl);
            item.appendChild(colorWrap);
            dropdown.appendChild(item);
        }
        dropdown.style.display = 'block';
    },

    _selectAIGenCommander(card) {
        this.aiGenCommanderName = card.name;
        const input = qs('#ai-gen-commander');
        const dropdown = qs('#ai-gen-commander-dropdown');
        input.value = card.name;
        dropdown.style.display = 'none';
    },

    async _runAIGenerate() {
        const commander = this.aiGenCommanderName || qs('#ai-gen-commander').value.trim();
        if (!commander) {
            ToastManager.show('Enter a commander name.', 'warning');
            qs('#ai-gen-commander').focus();
            return;
        }

        const btn = qs('#ai-gen-btn');
        const loading = qs('#ai-gen-loading');
        const results = qs('#ai-gen-results');
        const controls = qs('#deck-ai-generate-body .deck-ai-controls');

        const budgetRaw = qs('#ai-gen-budget').value;
        const budget = budgetRaw ? parseFloat(budgetRaw) : undefined;
        const omitRaw = qs('#ai-gen-omit').value.trim();
        const omitCards = omitRaw ? omitRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
        const useCollection = qs('#ai-gen-use-collection').checked;

        btn.disabled = true;
        loading.style.display = 'flex';
        results.style.display = 'none';
        results.innerHTML = '';

        try {
            const data = await apiFetch('/api/deck-generate', {
                method: 'POST',
                body: JSON.stringify({
                    commander,
                    budget_usd: budget,
                    omit_cards: omitCards,
                    use_collection: useCollection,
                }),
            });

            if (data.error) {
                results.innerHTML = '<div class="deck-ai-error">AI returned an error: ' + this._esc(data.error) + '</div>';
                results.style.display = 'block';
                return;
            }

            this._lastGenResult = data;
            this._renderGenerateResults(data, results);
            results.style.display = 'block';

            // Expand panel
            const body = qs('#deck-ai-generate-body');
            if (body) body.style.maxHeight = body.scrollHeight + 5000 + 'px';
        } catch (err) {
            results.innerHTML = '<div class="deck-ai-error">Generation failed: ' + this._esc(err.message) + '</div>';
            results.style.display = 'block';
            ToastManager.show('AI generation failed: ' + err.message, 'error');
        } finally {
            btn.disabled = false;
            loading.style.display = 'none';
        }
    },

    _renderGenerateResults(data, container) {
        let html = '';

        // Strategy
        if (data.strategy) {
            html += '<div class="deck-ai-strategy">' + this._esc(data.strategy) + '</div>';
        }

        // Stats row
        html += '<div class="deck-ai-stats">';
        html += '<div class="deck-ai-stat"><span class="deck-ai-stat-value">' + (data.total_cards || '?') + '</span><span class="deck-ai-stat-label">Cards</span></div>';
        html += '<div class="deck-ai-stat"><span class="deck-ai-stat-value">$' + (data.real_total_usd || 0).toFixed(0) + '</span><span class="deck-ai-stat-label">Total</span></div>';
        html += '<div class="deck-ai-stat"><span class="deck-ai-stat-value">' + (data.from_collection_count || 0) + '</span><span class="deck-ai-stat-label">Owned</span></div>';
        html += '</div>';

        // Cards grouped by role
        if (data.cards && data.cards.length) {
            const groups = {};
            for (const c of data.cards) {
                const role = c.role || 'other';
                if (!groups[role]) groups[role] = [];
                groups[role].push(c);
            }

            const roleOrder = ['commander', 'creature', 'ramp', 'draw', 'removal', 'land', 'utility', 'win_condition', 'other'];
            const sortedRoles = Object.keys(groups).sort((a, b) => {
                const ai = roleOrder.indexOf(a);
                const bi = roleOrder.indexOf(b);
                return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
            });

            for (const role of sortedRoles) {
                const cards = groups[role];
                html += '<div class="deck-ai-section">';
                html += '<div class="deck-ai-section-title">' + this._esc(role.replace('_', ' ')) + ' (' + cards.length + ')</div>';
                for (const c of cards) {
                    html += '<div class="deck-ai-card-row add-row" data-scryfall-id="' + (c.scryfall_id || '') + '">';
                    html += '<span class="deck-ai-card-name">' + this._esc(c.name) + '</span>';
                    if (c.from_collection) html += '<span class="deck-ai-card-owned-badge">Owned</span>';
                    if (c.estimated_price_usd) html += '<span class="deck-ai-card-price">$' + c.estimated_price_usd.toFixed(2) + '</span>';
                    html += '</div>';
                }
                html += '</div>';
            }
        }

        // Reasoning
        if (data.reasoning) {
            const r = data.reasoning;
            html += '<div class="deck-ai-section">';
            html += '<div class="deck-ai-section-title">AI Reasoning</div>';
            if (r.strategy) html += '<div class="deck-ai-notes"><strong>Strategy:</strong> ' + this._esc(r.strategy) + '</div>';
            if (r.mana_curve) html += '<div class="deck-ai-notes"><strong>Mana Curve:</strong> ' + this._esc(r.mana_curve) + '</div>';
            if (r.key_synergies) html += '<div class="deck-ai-notes"><strong>Key Synergies:</strong> ' + this._esc(r.key_synergies) + '</div>';
            if (r.budget_notes) html += '<div class="deck-ai-notes"><strong>Budget:</strong> ' + this._esc(r.budget_notes) + '</div>';
            if (r.collection_usage_notes) html += '<div class="deck-ai-notes"><strong>Collection Usage:</strong> ' + this._esc(r.collection_usage_notes) + '</div>';
            html += '</div>';
        }

        // Apply button
        html += '<button class="deck-btn deck-btn-apply-ai deck-btn-full" id="ai-gen-apply-btn">✅ Create Deck from AI Results</button>';

        container.innerHTML = html;

        // Bind apply button
        const applyBtn = qs('#ai-gen-apply-btn', container);
        if (applyBtn) {
            applyBtn.addEventListener('click', () => this._applyGeneratedDeck());
        }

        // Attach card preview on hover
        qsa('.deck-ai-card-row[data-scryfall-id]', container).forEach(row => {
            const sfid = row.dataset.scryfallId;
            if (sfid) {
                const nameEl = qs('.deck-ai-card-name', row);
                if (nameEl) CardPreview.attach(nameEl, sfid);
            }
        });
    },

    async _applyGeneratedDeck() {
        const data = this._lastGenResult;
        if (!data || !data.cards || !data.cards.length) {
            ToastManager.show('No generated deck to apply.', 'warning');
            return;
        }

        const applyBtn = qs('#ai-gen-apply-btn');
        if (applyBtn) { applyBtn.disabled = true; applyBtn.textContent = 'Creating deck...'; }

        try {
            // Create a new deck
            const deckName = (data.commander || 'AI Deck') + ' (AI)';
            const deck = await apiPost('/api/decks', { name: deckName });
            this.deckId = deck.id;
            this.deckName = deck.name;

            // Add cards one at a time
            let added = 0;
            let failed = 0;
            for (const card of data.cards) {
                if (!card.scryfall_id && !card.name) continue;

                try {
                    let sfid = card.scryfall_id;
                    // If no scryfall_id, try fuzzy Scryfall lookup
                    if (!sfid) {
                        const scryCard = await scryfallFuzzySearch(card.name);
                        if (scryCard) sfid = scryCard.id;
                    }
                    if (!sfid) { failed++; continue; }

                    const isCommander = (card.role === 'commander') ? 1 : 0;
                    await apiPost('/api/decks/' + deck.id + '/cards', {
                        scryfall_id: sfid,
                        card_name: card.name,
                        quantity: card.count || 1,
                        is_commander: isCommander,
                    });
                    added++;
                } catch (cardErr) {
                    console.warn('Failed to add ' + card.name + ':', cardErr.message);
                    failed++;
                }
            }

            // Reload
            await this.loadDecks();
            await this.loadDeck(deck.id);
            qs('#deck-selector').value = deck.id;

            const msg = 'Created "' + deckName + '" with ' + added + ' cards';
            if (failed) {
                ToastManager.show(msg + ' (' + failed + ' failed to resolve)', 'warning', 5000);
            } else {
                ToastManager.show(msg, 'success', 4000);
            }
        } catch (err) {
            ToastManager.show('Failed to create deck: ' + err.message, 'error');
        } finally {
            if (applyBtn) { applyBtn.disabled = false; applyBtn.textContent = '\u2705 Create Deck from AI Results'; }
        }
    },

    /** HTML-escape helper */
    _esc(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    },
};

/* ── Bootstrap ─────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
    DeckBuilder.init().catch(err => {
        console.error('DeckBuilder init error:', err);
        ToastManager.show('Failed to initialize deck builder', 'error');
    });
});
