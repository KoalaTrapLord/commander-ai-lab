/**
 * Commander AI Lab — Collection Management UI
 * ═══════════════════════════════════════════
 *
 * Endpoints consumed:
 *   GET   /api/collection              — list with filters/pagination/sort
 *   GET   /api/collection/{id}         — card detail
 *   PATCH /api/collection/{id}         — update card (category, tags, notes, finish)
 *   POST  /api/collection/import       — import cards
 *   GET   /api/collection/export       — export cards (file download)
 *   GET   /api/collection/{id}/edhrec  — EDHREC recommendations
 */

const Collection = (() => {
    'use strict';

    // ── Configuration ──────────────────────────────────────
    const API_BASE = window.LAB_API_BASE || window.location.origin;
    const LS_PREFS_KEY = 'coll_preferences';
    const DEBOUNCE_MS = 300;

    // ── Card Preview (hover tooltip with delay) ────────────
    const CollCardPreview = {
        el: null,
        img: null,
        visible: false,
        _hoverTimer: null,
        HOVER_DELAY: 225,
        init() {
            this.el = document.getElementById('coll-card-preview');
            this.img = document.getElementById('coll-card-preview-img');
        },
        show(imgUrl, mx, my) {
            if (!imgUrl || !this.el) return;
            this.img.src = imgUrl;
            this.img.onerror = () => this.hide();
            const vw = window.innerWidth, vh = window.innerHeight, w = 220;
            let x = mx + 16, y = my - 20;
            if (x + w > vw - 10) x = mx - w - 16;
            if (y + 310 > vh - 10) y = vh - 320;
            if (y < 10) y = 10;
            this.el.style.left = `${x}px`;
            this.el.style.top = `${y}px`;
            this.el.style.display = 'block';
            this.visible = true;
        },
        hide() {
            clearTimeout(this._hoverTimer);
            if (this.el) this.el.style.display = 'none';
            this.visible = false;
        },
        attachAll() {
            if (!this.el) this.init();
            document.querySelectorAll('.coll-row[data-img-url]').forEach(row => {
                const imgUrl = row.dataset.imgUrl;
                const nameEl = row.querySelector('.coll-td-name');
                if (!imgUrl || !nameEl || nameEl._previewBound) return;
                nameEl._previewBound = true;
                let lastE = null;
                nameEl.addEventListener('mouseenter', (e) => {
                    lastE = e;
                    clearTimeout(this._hoverTimer);
                    this._hoverTimer = setTimeout(() => {
                        if (lastE) this.show(imgUrl, lastE.clientX, lastE.clientY);
                    }, this.HOVER_DELAY);
                });
                nameEl.addEventListener('mousemove', (e) => {
                    lastE = e;
                    if (this.visible) this.show(imgUrl, e.clientX, e.clientY);
                });
                nameEl.addEventListener('mouseleave', () => this.hide());
            });
        },
    };
    const COLOR_MAP = {
        W: { label: 'W', bg: '#f9faf4', color: '#3d3929' },
        U: { label: 'U', bg: '#0e67ab', color: '#fff' },
        B: { label: 'B', bg: '#2b2424', color: '#ccc' },
        R: { label: 'R', bg: '#d3202a', color: '#fff' },
        G: { label: 'G', bg: '#00733e', color: '#fff' },
        C: { label: 'C', bg: '#706f6f', color: '#fff' },
    };

    const CARD_TYPES = ['Creature', 'Instant', 'Sorcery', 'Artifact', 'Enchantment', 'Planeswalker', 'Land'];
    const CATEGORY_SUGGESTIONS = ['Ramp', 'Draw', 'Removal', 'Board Wipe', 'Anthem', 'Protection', 'Tutor', 'Counter', 'Token', 'Sacrifice', 'Recursion', 'Graveyard', 'Lifegain', 'Burn', 'Stax', 'Evasion', 'Finisher', 'Combo'];

    const FIELD_OPTIONS = [
        { value: 'IGNORE',                    label: '— Ignore —' },
        { value: 'QUANTITY',                  label: 'Quantity' },
        { value: 'NAME',                      label: 'Name' },
        { value: 'SET_CODE',                  label: 'Set Code' },
        { value: 'SET_CODE_SECONDARY',        label: 'Set Code (secondary)' },
        { value: 'COLLECTOR_NUMBER',          label: 'Collector Number' },
        { value: 'COLLECTOR_NUMBER_SECONDARY',label: 'Collector Number (secondary)' },
        { value: 'FINISH',                    label: 'Finish' },
        { value: 'CONDITION',                 label: 'Condition' },
        { value: 'LANGUAGE',                  label: 'Language' },
    ];

    const MOXFIELD_DEFAULTS = {
        'Count':            'QUANTITY',
        'Name':             'NAME',
        'Edition':          'SET_CODE',
        'Foil':             'FINISH',
        'Collector Number': 'COLLECTOR_NUMBER',
        'Condition':        'CONDITION',
        'Language':         'LANGUAGE',
    };

    const ARCHIDEKT_DEFAULTS = {
        'Quantity':         'QUANTITY',
        'Name':             'NAME',
        'Set Code':         'SET_CODE',
        'Collector Number': 'COLLECTOR_NUMBER',
    };

    // ── State ───────────────────────────────────────────────
    let state = {
        items: [],
        page: 1,
        pageSize: 50,
        total: 0,
        loading: false,
        search: '',
        sortField: 'name',
        sortDir: 'asc',
        filters: {
            colors: [],
            types: [],
            isLegendary: false,
            isBasic: false,
            isGameChanger: false,
            highSalt: false,
            finish: '',
            cmcMin: null,
            cmcMax: null,
            priceMin: null,
            priceMax: null,
            category: [],
            rarity: [],
            setCode: [],
            powerMin: null,
            powerMax: null,
            toughMin: null,
            toughMax: null,
            keyword: [],
            edhrecMin: null,
            edhrecMax: null,
            qtyMin: null,
            qtyMax: null,
        },
        cachedSets: [],
        cachedKeywords: [],
        selectedCard: null,
        drawerOpen: false,
        drawerTab: 'overview',
        edhrecData: null,
        edhrecLoading: false,
        importStep: 0,
        importSource: '',
        importContent: '',
        importMapping: {},
        importMode: 'MERGE',
        importHeaders: [],
        importMissingFinishNormal: true,
        exportOpen: false,
    selectedRows: new Set(),
        preferences: {
            pageSize: 50,
            sortField: 'name',
            sortDir: 'asc',
            visibleColumns: ['quantity','name','mana_cost','type_line','color_identity','cmc','power_toughness','rarity','set_code','tcg_price','edhrec_rank','salt_score','category','finish','oracle_text'],
        },
    };

    let searchDebounceTimer = null;

    // ── Utilities ───────────────────────────────────────────

    function escapeHtml(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function escapeAttr(str) {
        return escapeHtml(str);
    }

    function formatPrice(price) {
        if (price == null || isNaN(price)) return '—';
        return `$${Number(price).toFixed(2)}`;
    }

    function saltClass(score) {
        if (score == null) return '';
        if (score < 1)  return 'salt-green';
        if (score < 2)  return 'salt-yellow';
        if (score < 3)  return 'salt-orange';
        return 'salt-red';
    }

    function truncate(str, len) {
        if (!str) return '';
        return str.length > len ? str.slice(0, len) + '…' : str;
    }

    function renderManaCost(manaCost) {
        if (!manaCost) return '—';
        // Parse mana symbols like {1}{U}{B}, {X}, {W/U}, etc.
        const symbols = manaCost.match(/\{[^}]+\}/g);
        if (!symbols) return escapeHtml(manaCost);
        return symbols.map(sym => {
            const inner = sym.slice(1, -1); // strip { }
            const ci = COLOR_MAP[inner];
            if (ci) {
                return `<span class="coll-mana-pip" style="background:${ci.bg};color:${ci.color}">${ci.label}</span>`;
            }
            // Generic/colorless/X/hybrid
            return `<span class="coll-mana-pip" style="background:#706f6f;color:#fff">${escapeHtml(inner)}</span>`;
        }).join('');
    }

    function renderColorPips(colorIdentity) {
        if (!colorIdentity || colorIdentity.length === 0) return '<span class="coll-colorless-pip">C</span>';
        return colorIdentity.map(c => {
            const ci = COLOR_MAP[c];
            if (!ci) return '';
            return `<span class="coll-mana-pip" style="background:${ci.bg};color:${ci.color}" title="${c}">${ci.label}</span>`;
        }).join('');
    }

    function renderFinishBadge(finish) {
        if (!finish || finish === 'NORMAL') return '<span class="coll-finish-badge finish-normal">Normal</span>';
        if (finish === 'FOIL')             return '<span class="coll-finish-badge finish-foil">Foil</span>';
        if (finish === 'ETCHED')           return '<span class="coll-finish-badge finish-etched">Etched</span>';
        return `<span class="coll-finish-badge">${escapeHtml(finish)}</span>`;
    }

    function renderCategoryChips(categories, cardId) {
        if (!categories || categories.length === 0) return '<span class="coll-no-category">—</span>';
        return categories.map(cat =>
            `<span class="coll-cat-chip" onclick="event.stopPropagation();Collection.openCategoryPopover(${cardId}, this)">${escapeHtml(cat)}</span>`
        ).join('');
    }

    function showLoading(show) {
        const spinner = document.getElementById('coll-loading');
        if (spinner) spinner.style.display = show ? 'flex' : 'none';
    }

    // ── Preferences ─────────────────────────────────────────

    function loadPreferences() {
        try {
            const saved = localStorage.getItem(LS_PREFS_KEY);
            if (saved) {
                const parsed = JSON.parse(saved);
                state.preferences = { ...state.preferences, ...parsed };
                state.pageSize = state.preferences.pageSize;
                state.sortField = state.preferences.sortField;
                state.sortDir = state.preferences.sortDir;
            }
        } catch (e) {
            console.warn('[Collection] Failed to load preferences:', e);
        }
    }

    function savePreferences() {
        try {
            state.preferences.pageSize = state.pageSize;
            state.preferences.sortField = state.sortField;
            state.preferences.sortDir = state.sortDir;
            localStorage.setItem(LS_PREFS_KEY, JSON.stringify(state.preferences));
        } catch (e) {
            console.warn('[Collection] Failed to save preferences:', e);
        }
    }

    // ── URL Sync ────────────────────────────────────────────

    function syncStateFromUrl() {
        const params = new URLSearchParams(window.location.search);
        if (params.has('q'))          state.search    = params.get('q');
        if (params.has('page'))       state.page      = parseInt(params.get('page'), 10) || 1;
        if (params.has('pageSize'))   state.pageSize  = parseInt(params.get('pageSize'), 10) || 50;
        if (params.has('sortField'))  state.sortField = params.get('sortField');
        if (params.has('sortDir'))    state.sortDir   = params.get('sortDir');
        if (params.has('colors'))     state.filters.colors    = params.get('colors').split(',').filter(Boolean);
        if (params.has('types'))      state.filters.types     = params.get('types').split(',').filter(Boolean);
        if (params.has('finish'))     state.filters.finish    = params.get('finish');
        if (params.has('category'))   state.filters.category  = params.get('category').split(',').filter(Boolean);
        if (params.has('isLegendary'))   state.filters.isLegendary   = params.get('isLegendary') === 'true';
        if (params.has('isBasic'))       state.filters.isBasic       = params.get('isBasic') === 'true';
        if (params.has('isGameChanger')) state.filters.isGameChanger = params.get('isGameChanger') === 'true';
        if (params.has('highSalt'))      state.filters.highSalt      = params.get('highSalt') === 'true';
        if (params.has('cmcMin'))    state.filters.cmcMin   = parseFloat(params.get('cmcMin'));
        if (params.has('cmcMax'))    state.filters.cmcMax   = parseFloat(params.get('cmcMax'));
        if (params.has('priceMin'))  state.filters.priceMin = parseFloat(params.get('priceMin'));
        if (params.has('priceMax'))  state.filters.priceMax = parseFloat(params.get('priceMax'));
        if (params.has('rarity'))    state.filters.rarity   = params.get('rarity').split(',').filter(Boolean);
        if (params.has('setCode'))   state.filters.setCode  = params.get('setCode').split(',').filter(Boolean);
        if (params.has('powerMin'))  state.filters.powerMin = parseFloat(params.get('powerMin'));
        if (params.has('powerMax'))  state.filters.powerMax = parseFloat(params.get('powerMax'));
        if (params.has('toughMin'))  state.filters.toughMin = parseFloat(params.get('toughMin'));
        if (params.has('toughMax'))  state.filters.toughMax = parseFloat(params.get('toughMax'));
        if (params.has('keyword'))   state.filters.keyword  = params.get('keyword').split(',').filter(Boolean);
        if (params.has('edhrecMin')) state.filters.edhrecMin = parseInt(params.get('edhrecMin'));
        if (params.has('edhrecMax')) state.filters.edhrecMax = parseInt(params.get('edhrecMax'));
        if (params.has('qtyMin'))    state.filters.qtyMin   = parseInt(params.get('qtyMin'));
        if (params.has('qtyMax'))    state.filters.qtyMax   = parseInt(params.get('qtyMax'));
    }

    function pushUrlState() {
        const params = new URLSearchParams();
        if (state.search)              params.set('q',            state.search);
        if (state.page > 1)            params.set('page',         state.page);
        if (state.pageSize !== 50)     params.set('pageSize',     state.pageSize);
        if (state.sortField !== 'name') params.set('sortField',   state.sortField);
        if (state.sortDir !== 'asc')   params.set('sortDir',      state.sortDir);
        if (state.filters.colors.length)    params.set('colors',    state.filters.colors.join(','));
        if (state.filters.types.length)     params.set('types',     state.filters.types.join(','));
        if (state.filters.finish)           params.set('finish',    state.filters.finish);
        if (state.filters.category.length)  params.set('category',  state.filters.category.join(','));
        if (state.filters.isLegendary)      params.set('isLegendary',   'true');
        if (state.filters.isBasic)          params.set('isBasic',        'true');
        if (state.filters.isGameChanger)    params.set('isGameChanger',  'true');
        if (state.filters.highSalt)         params.set('highSalt',       'true');
        if (state.filters.cmcMin != null)   params.set('cmcMin',   state.filters.cmcMin);
        if (state.filters.cmcMax != null)   params.set('cmcMax',   state.filters.cmcMax);
        if (state.filters.priceMin != null) params.set('priceMin', state.filters.priceMin);
        if (state.filters.priceMax != null) params.set('priceMax', state.filters.priceMax);
        if (state.filters.rarity.length)    params.set('rarity',   state.filters.rarity.join(','));
        if (state.filters.setCode.length)   params.set('setCode',  state.filters.setCode.join(','));
        if (state.filters.powerMin != null) params.set('powerMin', state.filters.powerMin);
        if (state.filters.powerMax != null) params.set('powerMax', state.filters.powerMax);
        if (state.filters.toughMin != null) params.set('toughMin', state.filters.toughMin);
        if (state.filters.toughMax != null) params.set('toughMax', state.filters.toughMax);
        if (state.filters.keyword.length)   params.set('keyword',  state.filters.keyword.join(','));
        if (state.filters.edhrecMin != null) params.set('edhrecMin', state.filters.edhrecMin);
        if (state.filters.edhrecMax != null) params.set('edhrecMax', state.filters.edhrecMax);
        if (state.filters.qtyMin != null)   params.set('qtyMin',   state.filters.qtyMin);
        if (state.filters.qtyMax != null)   params.set('qtyMax',   state.filters.qtyMax);
        const qs = params.toString();
        history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
    }

    // ── API ─────────────────────────────────────────────────

    function buildCollectionQuery() {
        const p = new URLSearchParams();
        p.set('page',      state.page);
        p.set('pageSize',  state.pageSize);
        p.set('sortField', state.sortField);
        p.set('sortDir',   state.sortDir);
        if (state.search) p.set('q', state.search);
        const f = state.filters;
        if (f.colors.length)    p.set('colors',    f.colors.join(','));
        if (f.types.length)     p.set('types',     f.types.join(','));
        if (f.finish)           p.set('finish',    f.finish);
        if (f.category.length)  p.set('category',  f.category.join(','));
        if (f.isLegendary)      p.set('isLegendary',   'true');
        if (f.isBasic)          p.set('isBasic',        'true');
        if (f.isGameChanger)    p.set('isGameChanger',  'true');
        if (f.highSalt)         p.set('highSalt',       'true');
        if (f.cmcMin != null)   p.set('cmcMin',   f.cmcMin);
        if (f.cmcMax != null)   p.set('cmcMax',   f.cmcMax);
        if (f.priceMin != null) p.set('priceMin', f.priceMin);
        if (f.priceMax != null) p.set('priceMax', f.priceMax);
        if (f.rarity.length)    p.set('rarity',   f.rarity.join(','));
        if (f.setCode.length)   p.set('setCode',  f.setCode.join(','));
        if (f.powerMin != null) p.set('powerMin', f.powerMin);
        if (f.powerMax != null) p.set('powerMax', f.powerMax);
        if (f.toughMin != null) p.set('toughMin', f.toughMin);
        if (f.toughMax != null) p.set('toughMax', f.toughMax);
        if (f.keyword.length)   p.set('keyword',  f.keyword.join(','));
        if (f.edhrecMin != null) p.set('edhrecMin', f.edhrecMin);
        if (f.edhrecMax != null) p.set('edhrecMax', f.edhrecMax);
        if (f.qtyMin != null)   p.set('qtyMin',   f.qtyMin);
        if (f.qtyMax != null)   p.set('qtyMax',   f.qtyMax);
        return p.toString();
    }

    async function fetchCollection() {
        if (state.loading) return;
        state.loading = true;
        showLoading(true);
        try {
            const qs = buildCollectionQuery();
            const res = await fetch(`${API_BASE}/api/collection?${qs}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            state.items = data.items || [];
            state.total = data.total || 0;
            state.page  = data.page  || state.page;
        } catch (err) {
            console.error('[Collection] fetchCollection error:', err);
            state.items = [];
            state.total = 0;
        } finally {
            state.loading = false;
            showLoading(false);
        }
        renderTable();
        renderSortBar();
        renderPagination();
        renderCountBadge();
    }

    // ── Stats Dashboard ──────────────────────────────────────
    let statsData = null;
    let statsOpen = false;

    async function fetchStats() {
        try {
            const res = await fetch(`${API_BASE}/api/collection/stats`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            statsData = await res.json();
        } catch (err) {
            console.error('[Collection] fetchStats error:', err);
            statsData = null;
        }
    }

    function toggleStats() {
        statsOpen = !statsOpen;
        const panel = document.getElementById('coll-stats-panel');
        if (!panel) return;
        if (statsOpen) {
            if (!statsData) {
                panel.innerHTML = '<div class="coll-stats-loading">Loading stats…</div>';
                panel.style.display = 'block';
                fetchStats().then(() => renderStatsPanel());
            } else {
                renderStatsPanel();
            }
            panel.style.display = 'block';
        } else {
            panel.style.display = 'none';
        }
    }

    function renderStatsPanel() {
        const panel = document.getElementById('coll-stats-panel');
        if (!panel || !statsData) return;
        const s = statsData;

        // CMC curve bar chart (CSS-only)
        const cmcMax = Math.max(...Object.values(s.cmcCurve || {}), 1);
        const cmcBars = [0,1,2,3,4,5,6,7].map(i => {
            const count = (s.cmcCurve || {})[String(i)] || 0;
            const pct = Math.round((count / cmcMax) * 100);
            const label = i === 7 ? '7+' : String(i);
            return `<div class="coll-stat-bar-col">
                <div class="coll-stat-bar" style="height:${pct}%" title="${count}"></div>
                <span class="coll-stat-bar-label">${label}</span>
            </div>`;
        }).join('');

        // Color distribution
        const colorTotal = Math.max(Object.values(s.colorDistribution || {}).reduce((a,b) => a+b, 0), 1);
        const colorBars = ['W','U','B','R','G','C'].map(c => {
            const count = (s.colorDistribution || {})[c] || 0;
            const pct = Math.round((count / colorTotal) * 100);
            const ci = COLOR_MAP[c];
            return `<div class="coll-stat-color-bar">
                <span class="coll-stat-color-pip" style="background:${ci.bg};color:${ci.color}">${ci.label}</span>
                <div class="coll-stat-hbar-track"><div class="coll-stat-hbar" style="width:${pct}%;background:${ci.bg}"></div></div>
                <span class="coll-stat-hbar-val">${count}</span>
            </div>`;
        }).join('');

        // Type distribution
        const typeTotal = Math.max(Object.values(s.typeDistribution || {}).reduce((a,b) => a+b, 0), 1);
        const typeBars = Object.entries(s.typeDistribution || {}).sort((a,b) => b[1]-a[1]).map(([t, count]) => {
            const pct = Math.round((count / typeTotal) * 100);
            return `<div class="coll-stat-type-row">
                <span class="coll-stat-type-label">${escapeHtml(t)}</span>
                <div class="coll-stat-hbar-track"><div class="coll-stat-hbar coll-stat-hbar-type" style="width:${pct}%"></div></div>
                <span class="coll-stat-hbar-val">${count}</span>
            </div>`;
        }).join('');

        // Rarity distribution
        const rarityOrder = ['common','uncommon','rare','mythic'];
        const rarityColors = {common:'#706f6f', uncommon:'#859ba6', rare:'#c9a849', mythic:'#d35400'};
        const rarityTotal = Math.max(Object.values(s.rarityDistribution || {}).reduce((a,b) => a+b, 0), 1);
        const rarityBars = rarityOrder.map(r => {
            const count = (s.rarityDistribution || {})[r] || 0;
            const pct = Math.round((count / rarityTotal) * 100);
            return `<div class="coll-stat-type-row">
                <span class="coll-stat-type-label" style="color:${rarityColors[r] || '#ccc'}">${r.charAt(0).toUpperCase() + r.slice(1)}</span>
                <div class="coll-stat-hbar-track"><div class="coll-stat-hbar" style="width:${pct}%;background:${rarityColors[r] || '#555'}"></div></div>
                <span class="coll-stat-hbar-val">${count}</span>
            </div>`;
        }).join('');

        // Top value cards
        const topCards = (s.topValueCards || []).map(c =>
            `<div class="coll-stat-top-row"><span>${escapeHtml(c.name)}</span><span>$${Number(c.price).toFixed(2)}</span></div>`
        ).join('');

        // Category/role coverage
        const catEntries = Object.entries(s.categoryDistribution || {}).sort((a,b) => b[1]-a[1]).slice(0, 12);
        const catMax = Math.max(...catEntries.map(e => e[1]), 1);
        const catBars = catEntries.map(([cat, count]) => {
            const pct = Math.round((count / catMax) * 100);
            return `<div class="coll-stat-type-row">
                <span class="coll-stat-type-label">${escapeHtml(cat)}</span>
                <div class="coll-stat-hbar-track"><div class="coll-stat-hbar coll-stat-hbar-cat" style="width:${pct}%"></div></div>
                <span class="coll-stat-hbar-val">${count}</span>
            </div>`;
        }).join('');

        panel.innerHTML = `
            <div class="coll-stats-grid">
                <div class="coll-stats-summary">
                    <div class="coll-stat-card"><div class="coll-stat-num">${(s.totalCards || 0).toLocaleString()}</div><div class="coll-stat-label">Total Cards</div></div>
                    <div class="coll-stat-card"><div class="coll-stat-num">${(s.totalUniqueCards || 0).toLocaleString()}</div><div class="coll-stat-label">Unique</div></div>
                    <div class="coll-stat-card"><div class="coll-stat-num">$${(s.totalValue || 0).toLocaleString(undefined,{minimumFractionDigits:2})}</div><div class="coll-stat-label">Total Value</div></div>
                    <div class="coll-stat-card"><div class="coll-stat-num">${s.avgCmc || 0}</div><div class="coll-stat-label">Avg CMC</div></div>
                </div>
                <div class="coll-stats-section">
                    <h4>CMC Curve</h4>
                    <div class="coll-stat-bar-chart">${cmcBars}</div>
                </div>
                <div class="coll-stats-section">
                    <h4>Color Distribution</h4>
                    ${colorBars}
                </div>
                <div class="coll-stats-section">
                    <h4>Type Distribution</h4>
                    ${typeBars}
                </div>
                <div class="coll-stats-section">
                    <h4>Rarity</h4>
                    ${rarityBars}
                </div>
                <div class="coll-stats-section">
                    <h4>Role Coverage</h4>
                    ${catBars || '<div class="coll-stats-empty">No categories assigned yet</div>'}
                </div>
                <div class="coll-stats-section">
                    <h4>Top Value Cards</h4>
                    ${topCards || '<div class="coll-stats-empty">No priced cards</div>'}
                </div>
            </div>
        `;
    }


    async function fetchCardDetail(cardId) {
        const res = await fetch(`${API_BASE}/api/collection/${cardId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    async function fetchEdhrecData(cardId) {
        const res = await fetch(`${API_BASE}/api/collection/${cardId}/edhrec`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    async function patchCard(cardId, payload) {
        const res = await fetch(`${API_BASE}/api/collection/${cardId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    // ── Init ────────────────────────────────────────────────

    async function init() {
        loadPreferences();
        syncStateFromUrl();
        renderPage();
        bindEvents();
        adjustTableHeight();
        window.addEventListener('resize', adjustTableHeight);
        // Pre-load set/keyword caches for filter autocomplete
        loadSetsCache();
        loadKeywordsCache();
        applyColumnVisibility();
    await fetchCollection();
    }

    /** Adjust table container height based on actual topbar height */
    function adjustTableHeight() {
        const topbar = document.querySelector('.coll-topbar');
        const tableWrap = document.querySelector('.coll-table-wrap');
        if (topbar && tableWrap) {
            const topbarH = topbar.offsetHeight;
            // 16px padding-top of coll-main + 16px padding-bottom
            tableWrap.style.maxHeight = 'calc(100vh - ' + (topbarH + 48) + 'px)';
        }
    }

    // ── Page Render ─────────────────────────────────────────

    function renderPage() {
        const container = document.getElementById('collection-container');
        if (!container) return;

        container.innerHTML = `
        <div id="collection-page">

            <!-- Loading overlay -->
            <div id="coll-loading" style="display:none">
                <div class="coll-spinner"></div>
            </div>

            <!-- Top Bar -->
            <div class="coll-topbar">
                <div class="coll-topbar-left">
                    <h1 class="coll-title">Collection</h1>
                    <span class="coll-count" id="coll-count">0 cards</span>
                </div>
                <div class="coll-topbar-right">
                    <input type="text" id="coll-search" class="coll-search"
                           placeholder="Search cards…"
                           value="${escapeAttr(state.search)}"
                           autocomplete="off" />
                    <button class="coll-scan-btn" onclick="Collection.openScan()">Scan</button>
                    <button class="coll-import-btn" onclick="Collection.openImport()">Import</button>
                    <button class="coll-export-btn" onclick="Collection.openExport()">Export</button>
                    <button class="coll-autoclassify-btn" onclick="Collection.autoClassify()" title="Auto-detect categories (Ramp, Draw, Removal, etc.) for uncategorized cards">Auto-Classify</button>
                    <button class="coll-reenrich-btn" onclick="Collection.reEnrich()" title="Re-fetch all card data from Scryfall">Refresh Data</button>
          <button class="coll-stats-btn" onclick="Collection.toggleStats()" title="Show collection statistics dashboard">📊 Stats</button>
          <div style="position:relative">
          <button class="coll-col-toggle-btn" onclick="Collection.openColumnPanel()" title="Show/hide table columns">☰ Columns</button>
          <div id="coll-col-panel" class="coll-col-panel" style="display:none"></div>
                  </div>
          <a href="deckbuilder.html" class="coll-nav-link" style="color:var(--lab-purple);border-color:var(--lab-purple)">⚔ Deck Builder</a>
                    <a href="deckgenerator.html" class="coll-nav-link" style="color:var(--lab-warning);border-color:var(--lab-warning)">⚡ Auto Gen</a>
                </div>
            </div>
        <!-- Stats Dashboard Panel -->
        <div id="coll-stats-panel" class="coll-stats-panel" style="display:none"></div>

            <!-- Main -->
            <div class="coll-main">

                <!-- Left Filter Panel -->
                <aside class="coll-filters" id="coll-filters">
                    ${renderFiltersHtml()}
                </aside>

                <!-- Table Area -->
                <div class="coll-table-wrap">
                    ${renderSortBarHtml()}
                    <div class="coll-table-container">
                        <table class="coll-table" id="coll-table">
                            ${renderTableHeaderHtml()}
                            <tbody id="coll-tbody"></tbody>
                        </table>
                    </div>
                    <div class="coll-pagination" id="coll-pagination"></div>
        <!-- Bulk Action Bar -->
                    <div id="coll-bulk-bar" class="coll-bulk-bar" style="display:none">
                        <span id="coll-bulk-count" class="coll-bulk-count">0 selected</span>
                        <button class="coll-bulk-btn" onclick="Collection.selectAllRows()">Select All</button>
                        <button class="coll-bulk-btn" onclick="Collection.clearSelection()">Clear</button>
                        <span class="coll-bulk-sep">|</span>
                        <span class="coll-bulk-label">Qty:</span>
                        <button class="coll-bulk-btn" onclick="Collection.bulkAdjustQuantity(-1)" title="Subtract 1">−</button>
                        <button class="coll-bulk-btn" onclick="Collection.bulkAdjustQuantity(1)" title="Add 1">+</button>
                        <input type="number" id="coll-bulk-qty-input" class="coll-bulk-qty-input" min="0" value="1" placeholder="n">
                        <button class="coll-bulk-btn coll-bulk-set-btn" onclick="Collection.bulkSetQuantity()">Set</button>
                    </div>
                </div>

            </div>

            <!-- Detail Drawer -->
            <div class="coll-drawer" id="coll-drawer">
                <div class="coll-drawer-inner" id="coll-drawer-inner"></div>
            </div>
            <div class="coll-drawer-backdrop" id="coll-drawer-backdrop" onclick="Collection.closeDrawer()"></div>

            <!-- Category Popover -->
            <div class="coll-cat-popover" id="coll-cat-popover" style="display:none"></div>

            <!-- Import Modal -->
            <div class="coll-modal-overlay" id="coll-import-modal">
                <div class="coll-modal-content coll-modal-wide" id="coll-import-body"></div>
            </div>

            <!-- Export Modal -->
            <div class="coll-modal-overlay" id="coll-export-modal">
                <div class="coll-modal-content" id="coll-export-body"></div>
            </div>

            <!-- Scan Modal -->
            <div class="coll-modal-overlay" id="coll-scan-modal">
                <div class="coll-modal-content coll-modal-wide" id="coll-scan-body"></div>
            </div>

        </div>`;

        renderTable();
        renderPagination();
    }

    // ── Sort Bar HTML ───────────────────────────────────────

    function renderSortBarHtml() {
        const sortOptions = [
            { value: 'name',       label: 'Name' },
            { value: 'tcg_price',  label: 'Price' },
            { value: 'cmc',        label: 'CMC / Mana Value' },
            { value: 'quantity',   label: 'Quantity' },
            { value: 'type_line',  label: 'Type' },
            { value: 'rarity',     label: 'Rarity' },
            { value: 'edhrec_rank',label: 'EDHREC Rank' },
            { value: 'salt_score', label: 'Salt Score' },
            { value: 'set_code',   label: 'Set' },
            { value: 'finish',     label: 'Finish' },
        ];
        const opts = sortOptions.map(o =>
            `<option value="${o.value}" ${state.sortField === o.value ? 'selected' : ''}>${o.label}</option>`
        ).join('');
        const dirLabel = state.sortDir === 'asc' ? '▲ Asc' : '▼ Desc';
        return `
        <div class="coll-sort-bar">
            <span class="coll-sort-bar-label">Sort by</span>
            <select class="coll-sort-select" id="coll-sort-select" onchange="Collection.setSortFromBar(this.value)">
                ${opts}
            </select>
            <button class="coll-sort-dir-btn" id="coll-sort-dir-btn" onclick="Collection.toggleSortDir()" title="Toggle sort direction">${dirLabel}</button>
            <span class="coll-sort-bar-count" id="coll-sort-bar-count">${state.total.toLocaleString()} cards</span>
        </div>`;
    }

    function renderSortBar() {
        const bar = document.querySelector('.coll-sort-bar');
        if (bar) {
            bar.outerHTML = renderSortBarHtml();
        }
    }

    function setSortFromBar(field) {
        state.sortField = field;
        state.page = 1;
        savePreferences();
        pushUrlState();
        fetchCollection();
    }

    function toggleSortDir() {
        state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
        state.page = 1;
        savePreferences();
        pushUrlState();
        fetchCollection();
    }

    // ── Filter Panel HTML ───────────────────────────────────

    function renderFiltersHtml() {
        const f = state.filters;

        // Color buttons
        const colorBtns = Object.entries(COLOR_MAP).map(([key, ci]) => {
            const active = f.colors.includes(key) ? 'active' : '';
            return `<button class="coll-color-btn ${active}" data-color="${key}"
                        style="${active ? `background:${ci.bg};color:${ci.color};border-color:${ci.bg}` : ''}"
                        onclick="Collection.toggleColor('${key}')" title="${key}">${ci.label}</button>`;
        }).join('');

        // Type checkboxes
        const typeChecks = CARD_TYPES.map(t => {
            const checked = f.types.includes(t) ? 'checked' : '';
            return `<label class="coll-check-label">
                <input type="checkbox" data-type="${t}" ${checked}
                    onchange="Collection.toggleType('${t}')"> ${t}
            </label>`;
        }).join('');

        // Toggles
        const toggles = [
            { key: 'isLegendary',   label: 'Legendary' },
            { key: 'isBasic',       label: 'Basics' },
            { key: 'isGameChanger', label: 'Game Changers' },
            { key: 'highSalt',      label: 'High Salt' },
        ].map(({ key, label }) => {
            const active = f[key] ? 'active' : '';
            return `<button class="coll-toggle-btn ${active}" data-key="${key}"
                        onclick="Collection.toggleFilter('${key}')">${label}</button>`;
        }).join('');

        // Finish radios
        const finishes = [
            { value: '',       label: 'All' },
            { value: 'NORMAL', label: 'Normal' },
            { value: 'FOIL',   label: 'Foil' },
            { value: 'ETCHED', label: 'Etched' },
        ].map(({ value, label }) => {
            const checked = f.finish === value ? 'checked' : '';
            return `<label class="coll-radio-label">
                <input type="radio" name="coll-finish" value="${value}" ${checked}
                    onchange="Collection.setFinish('${value}')"> ${label}
            </label>`;
        }).join('');

        // Category chips
        const catChips = CATEGORY_SUGGESTIONS.map(cat => {
            const active = f.category.includes(cat) ? 'active' : '';
            return `<button class="coll-cat-filter-btn ${active}" data-cat="${escapeAttr(cat)}"
                        onclick="Collection.toggleCategoryFilter('${escapeAttr(cat)}')">${escapeHtml(cat)}</button>`;
        }).join('');

        // Rarity buttons
        const RARITIES = [
            { value: 'common',   label: 'C', title: 'Common' },
            { value: 'uncommon', label: 'U', title: 'Uncommon' },
            { value: 'rare',     label: 'R', title: 'Rare' },
            { value: 'mythic',   label: 'M', title: 'Mythic' },
        ];
        const rarityBtns = RARITIES.map(r => {
            const active = f.rarity.includes(r.value) ? 'active' : '';
            return `<button class="coll-rarity-btn coll-rarity-${r.value} ${active}"
                        title="${r.title}" onclick="Collection.toggleRarity('${r.value}')">${r.label}</button>`;
        }).join('');

        // Set filter chips (show selected sets)
        const setChips = f.setCode.map(code => {
            const found = state.cachedSets.find(s => s.code === code);
            const label = found ? found.name : code;
            return `<span class="coll-set-chip">${escapeHtml(label)} <button onclick="Collection.removeSetFilter('${escapeAttr(code)}')">&times;</button></span>`;
        }).join('');

        // Keyword filter chips
        const kwChips = f.keyword.map(kw =>
            `<span class="coll-kw-chip">${escapeHtml(kw)} <button onclick="Collection.removeKeywordFilter('${escapeAttr(kw)}')">&times;</button></span>`
        ).join('');

        return `
        <div class="coll-filter-section">
            <div class="coll-filter-label">Color Identity</div>
            <div class="coll-color-btns">${colorBtns}</div>
        </div>

        <div class="coll-filter-section">
            <div class="coll-filter-label">Card Type</div>
            <div class="coll-type-checks">${typeChecks}</div>
        </div>

        <div class="coll-filter-section">
            <div class="coll-filter-label">Rarity</div>
            <div class="coll-rarity-btns">${rarityBtns}</div>
        </div>

        <div class="coll-filter-section">
            <div class="coll-filter-label">Properties</div>
            <div class="coll-toggle-btns">${toggles}</div>
        </div>

        <div class="coll-filter-section">
            <div class="coll-filter-label">Finish</div>
            <div class="coll-finish-radios">${finishes}</div>
        </div>

        <div class="coll-filter-section">
            <div class="coll-filter-label">CMC Range</div>
            <div class="coll-range-inputs">
                <input type="number" class="coll-range-input" id="coll-cmc-min" placeholder="Min"
                       value="${f.cmcMin ?? ''}" min="0" step="1"
                       onchange="Collection.setCmcRange()">
                <span class="coll-range-sep">&ndash;</span>
                <input type="number" class="coll-range-input" id="coll-cmc-max" placeholder="Max"
                       value="${f.cmcMax ?? ''}" min="0" step="1"
                       onchange="Collection.setCmcRange()">
            </div>
        </div>

        <div class="coll-filter-section">
            <div class="coll-filter-label">Power / Toughness</div>
            <div class="coll-range-row">
                <div class="coll-range-group">
                    <span class="coll-range-sublabel">Pow</span>
                    <div class="coll-range-inputs">
                        <input type="number" class="coll-range-input" id="coll-pow-min" placeholder="Min"
                               value="${f.powerMin ?? ''}" min="0" step="1"
                               onchange="Collection.setPowerRange()">
                        <span class="coll-range-sep">&ndash;</span>
                        <input type="number" class="coll-range-input" id="coll-pow-max" placeholder="Max"
                               value="${f.powerMax ?? ''}" min="0" step="1"
                               onchange="Collection.setPowerRange()">
                    </div>
                </div>
                <div class="coll-range-group">
                    <span class="coll-range-sublabel">Tgh</span>
                    <div class="coll-range-inputs">
                        <input type="number" class="coll-range-input" id="coll-tgh-min" placeholder="Min"
                               value="${f.toughMin ?? ''}" min="0" step="1"
                               onchange="Collection.setToughRange()">
                        <span class="coll-range-sep">&ndash;</span>
                        <input type="number" class="coll-range-input" id="coll-tgh-max" placeholder="Max"
                               value="${f.toughMax ?? ''}" min="0" step="1"
                               onchange="Collection.setToughRange()">
                    </div>
                </div>
            </div>
        </div>

        <div class="coll-filter-section">
            <div class="coll-filter-label">Price Range ($)</div>
            <div class="coll-range-inputs">
                <input type="number" class="coll-range-input" id="coll-price-min" placeholder="Min"
                       value="${f.priceMin ?? ''}" min="0" step="0.01"
                       onchange="Collection.setPriceRange()">
                <span class="coll-range-sep">&ndash;</span>
                <input type="number" class="coll-range-input" id="coll-price-max" placeholder="Max"
                       value="${f.priceMax ?? ''}" min="0" step="0.01"
                       onchange="Collection.setPriceRange()">
            </div>
        </div>

        <div class="coll-filter-section">
            <div class="coll-filter-label">EDHREC Rank</div>
            <div class="coll-range-inputs">
                <input type="number" class="coll-range-input" id="coll-edhrec-min" placeholder="Min"
                       value="${f.edhrecMin ?? ''}" min="0" step="1"
                       onchange="Collection.setEdhrecRange()">
                <span class="coll-range-sep">&ndash;</span>
                <input type="number" class="coll-range-input" id="coll-edhrec-max" placeholder="Max"
                       value="${f.edhrecMax ?? ''}" min="0" step="1"
                       onchange="Collection.setEdhrecRange()">
            </div>
        </div>

        <div class="coll-filter-section">
            <div class="coll-filter-label">Owned Quantity</div>
            <div class="coll-range-inputs">
                <input type="number" class="coll-range-input" id="coll-qty-min" placeholder="Min"
                       value="${f.qtyMin ?? ''}" min="1" step="1"
                       onchange="Collection.setQtyRange()">
                <span class="coll-range-sep">&ndash;</span>
                <input type="number" class="coll-range-input" id="coll-qty-max" placeholder="Max"
                       value="${f.qtyMax ?? ''}" min="1" step="1"
                       onchange="Collection.setQtyRange()">
            </div>
        </div>

        <div class="coll-filter-section">
            <div class="coll-filter-label">Set</div>
            <div class="coll-set-filter">
                <input type="text" class="coll-set-input" id="coll-set-input"
                       placeholder="Type set name or code..." autocomplete="off"
                       oninput="Collection.onSetInput(this.value)"
                       onfocus="Collection.onSetInput(this.value)">
                <div class="coll-set-dropdown" id="coll-set-dropdown"></div>
                <div class="coll-set-chips">${setChips}</div>
            </div>
        </div>

        <div class="coll-filter-section">
            <div class="coll-filter-label">Keywords</div>
            <div class="coll-kw-filter">
                <input type="text" class="coll-kw-input" id="coll-kw-input"
                       placeholder="Type keyword (e.g. Flying)..." autocomplete="off"
                       oninput="Collection.onKwInput(this.value)"
                       onfocus="Collection.onKwInput(this.value)">
                <div class="coll-kw-dropdown" id="coll-kw-dropdown"></div>
                <div class="coll-kw-chips">${kwChips}</div>
            </div>
        </div>

        <div class="coll-filter-section">
            <div class="coll-filter-label">Category</div>
            <div class="coll-cat-filter-btns">${catChips}</div>
        </div>

        <div class="coll-filter-section">
            <button class="coll-reset-btn" onclick="Collection.resetFilters()">Reset Filters</button>
        </div>`;
    }

    // ── Column Visibility ──────────────────────────────────────
    function colVis(key) {
        return state.preferences.visibleColumns.includes(key) ? '' : 'display:none;';
    }

    function toggleColumn(key) {
        const cols = state.preferences.visibleColumns;
        const idx = cols.indexOf(key);
        if (idx >= 0) {
            if (cols.length <= 1) return; // keep at least 1 column
            cols.splice(idx, 1);
        } else {
            cols.push(key);
        }
        savePreferences();
        renderTable();
        applyColumnVisibility();
    }

    function renderColumnPanel() {
        const panel = document.getElementById('coll-col-panel');
        if (!panel) return;
        const cols = COLUMNS.map(col => {
            const checked = state.preferences.visibleColumns.includes(col.key) ? 'checked' : '';
            return `<label class="coll-col-toggle-item">
                <input type="checkbox" ${checked} onchange="Collection.toggleColumn('${col.key}')">
                ${escapeHtml(col.label)}
            </label>`;
        }).join('');
        panel.innerHTML = `
            <div class="coll-col-panel-inner">
                <div class="coll-col-panel-hdr">Columns <button class="coll-col-close" onclick="Collection.closeColumnPanel()">×</button></div>
                ${cols}
                <button class="coll-col-reset" onclick="Collection.resetColumns()">Reset Defaults</button>
            </div>`;
        panel.style.display = 'block';
    }

    function openColumnPanel() {
        const panel = document.getElementById('coll-col-panel');
        if (!panel) return;
        if (panel.style.display === 'block') {
            panel.style.display = 'none';
        } else {
            renderColumnPanel();
        }
    }

    function closeColumnPanel() {
        const panel = document.getElementById('coll-col-panel');
        if (panel) panel.style.display = 'none';
    }

    function resetColumns() {
        state.preferences.visibleColumns = ['quantity','name','mana_cost','type_line','color_identity','cmc','power_toughness','rarity','set_code','tcg_price','edhrec_rank','salt_score','category','finish','oracle_text'];
        savePreferences();
        renderTable();
        renderColumnPanel();
    }
    function applyColumnVisibility() {
        let styleEl = document.getElementById('coll-col-vis-style');
        if (!styleEl) {
            styleEl = document.createElement('style');
            styleEl.id = 'coll-col-vis-style';
            document.head.appendChild(styleEl);
        }
        const hidden = COLUMNS.filter(col => !state.preferences.visibleColumns.includes(col.key));
        styleEl.textContent = hidden.map(col =>
            `.coll-th-${col.key}, .coll-td-${col.key} { display: none !important; }`
        ).join('\n');
    }


    // ── Table Header ────────────────────────────────────────

    const COLUMNS = [
        { key: 'quantity',      label: 'Qty',       sortable: true },
        { key: 'name',          label: 'Name',      sortable: true },
        { key: 'mana_cost',     label: 'Mana',      sortable: false },
        { key: 'type_line',     label: 'Type',      sortable: true },
        { key: 'color_identity',label: 'Colors',    sortable: false },
        { key: 'cmc',           label: 'CMC',       sortable: true },
        { key: 'power_toughness',label: 'P/T',      sortable: false },
        { key: 'rarity',        label: 'Rarity',    sortable: true },
        { key: 'set_code',      label: 'Set',       sortable: true },
        { key: 'tcg_price',     label: 'Price',     sortable: true },
        { key: 'edhrec_rank',   label: 'EDHREC',    sortable: true },
        { key: 'salt_score',    label: 'Salt',      sortable: true },
        { key: 'is_game_changer',label: 'GC',       sortable: false },
        { key: 'category',      label: 'Category',  sortable: true },
        { key: 'finish',        label: 'Finish',    sortable: true },
        { key: 'oracle_text',   label: 'Oracle Text', sortable: false },
    ];

    function renderTableHeaderHtml() {
        const visibleCols = COLUMNS.filter(col => state.preferences.visibleColumns.includes(col.key));
        const headers = visibleCols.map(col => {            if (!col.sortable) {
                return `<th class="coll-th coll-th-${col.key}">${col.label}</th>`;
            }
            const isActive = state.sortField === col.key;
            const dir = isActive ? state.sortDir : '';
            const arrow = isActive ? (dir === 'asc' ? ' ▲' : ' ▼') : '';
            const activeClass = isActive ? ' coll-th-active' : '';
            return `<th class="coll-th coll-th-${col.key} coll-th-sortable${activeClass}"
                        onclick="Collection.setSort('${col.key}')">${col.label}${arrow}</th>`;
        }).join('');
        return `<thead><tr><th class="coll-th-select"><input type="checkbox" id="coll-select-all" onclick="Collection.toggleSelectAll(this.checked)" title="Select all"></th>${headers}</tr></thead>`;
    }

    // ── Table Body ──────────────────────────────────────────

    function renderTable() {
        const tbody = document.getElementById('coll-tbody');
        if (!tbody) return;

        // Re-render header (sort indicators may have changed)
        const table = document.getElementById('coll-table');
        if (table) {
            const oldThead = table.querySelector('thead');
            if (oldThead) {
                oldThead.outerHTML = renderTableHeaderHtml();
            }
        }

        if (state.loading) {
            tbody.innerHTML = `<tr><td colspan="${state.preferences.visibleColumns.length}" class="coll-empty">Loading…</td></tr>`;
            return;
        }

        if (state.items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="${state.preferences.visibleColumns.length}" class="coll-empty">
                <div class="coll-empty-state">
                    <div class="coll-empty-icon">🃏</div>
                    <div>No cards in collection</div>
                    <button class="coll-import-btn" onclick="Collection.openImport()">Import Cards</button>
                </div>
            </td></tr>`;
            return;
        }

        tbody.innerHTML = state.items.map(card => {
            const saltCls = saltClass(card.saltScore);
            const oracleTrunc = truncate(card.oracleText || '', 60);
            const gcIcon = card.isGameChanger ? '<span class="coll-gc-star" title="Game Changer">★</span>' : '';
            const legIcon = card.isLegendary  ? '<span class="coll-legendary-icon" title="Legendary">◆</span>' : '';
            const basicIcon = card.isBasic    ? '<span class="coll-basic-icon" title="Basic">⬡</span>' : '';

            const manaCost = renderManaCost(card.manaCost || card.mana_cost || '');
            const pt = (card.power || card.toughness)
                ? `${escapeHtml(card.power || '—')}/${escapeHtml(card.toughness || '—')}`
                : '—';
            const rarity = card.rarity ? `<span class="coll-rarity coll-rarity-${escapeAttr(card.rarity)}">${escapeHtml(card.rarity)}</span>` : '—';
            const setName = escapeHtml(card.setName || card.set_name || '');
            const edhrecRank = (card.edhrecRank || card.edhrec_rank) ? `#${card.edhrecRank || card.edhrec_rank}` : '—';

            return `<tr class="coll-row" onclick="Collection.openDrawer(${card.id})" data-id="${card.id}" data-img-url="${card.imageUrl || ''}">
                    <td class="coll-td coll-td-select" onclick="event.stopPropagation()"><input type="checkbox" class="coll-row-check" data-id="${card.id}" ${state.selectedRows.has(card.id) ? 'checked' : ''} onchange="Collection.toggleRowSelect(${card.id}, this.checked)"></td>
                <td class="coll-td coll-td-quantity" style="${colVis('quantity')}">${escapeHtml(card.quantity ?? 1)}</td>
                <td class="coll-td coll-td-name" style="${colVis('name')}">
                    <span class="coll-card-name">${escapeHtml(card.name)}</span>
                    ${legIcon}${basicIcon}
                </td>
                <td class="coll-td coll-td-mana" style="${colVis('mana_cost')}">${manaCost}</td>
                <td class="coll-td coll-td-type" style="${colVis('type_line')}">${escapeHtml(card.typeLine || card.type_line || '')}</td>
                <td class="coll-td coll-td-colors" style="${colVis('color_identity')}">${renderColorPips(card.colorIdentity || card.color_identity)}</td>
                <td class="coll-td coll-td-cmc" style="${colVis('cmc')}">${card.cmc ?? '—'}</td>
                <td class="coll-td coll-td-pt" style="${colVis('power_toughness')}">${pt}</td>
                <td class="coll-td coll-td-rarity" style="${colVis('rarity')}">${rarity}</td>
                <td class="coll-td coll-td-set" style="${colVis('set_code')}" title="${setName}">${setName}</td>
                <td class="coll-td coll-td-price" style="${colVis('tcg_price')}">${formatPrice(card.tcgPrice || card.tcg_price)}</td>
                <td class="coll-td coll-td-edhrec" style="${colVis('edhrec_rank')}">${edhrecRank}</td>
                <td class="coll-td coll-td-salt ${saltCls}" style="${colVis('salt_score')}" title="Salt: ${card.saltScore ?? card.salt_score ?? '?'}">${(card.saltScore ?? card.salt_score) != null ? Number(card.saltScore ?? card.salt_score).toFixed(2) : '—'}</td>
                <td class="coll-td coll-td-gc" style="${colVis('is_game_changer')}">${gcIcon}</td>
                <td class="coll-td coll-td-category" style="${colVis('category')}">${renderCategoryChips(card.category || [], card.id)}</td>
                <td class="coll-td coll-td-finish" style="${colVis('finish')}">${renderFinishBadge(card.finish)}</td>
                <td class="coll-td coll-td-oracle" style="${colVis('oracle_text')}" title="${escapeAttr(card.oracleText || card.oracle_text || '')}">${escapeHtml(oracleTrunc)}</td>
            </tr>`;
        }).join('');
                CollCardPreview.attachAll();
    }

    // ── Pagination ──────────────────────────────────────────

    function renderPagination() {
        const el = document.getElementById('coll-pagination');
        if (!el) return;
        const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
        const prevDisabled = state.page <= 1 ? 'disabled' : '';
        const nextDisabled = state.page >= totalPages ? 'disabled' : '';

        el.innerHTML = `
        <div class="coll-page-info">
            Page ${state.page} of ${totalPages}
            <span class="coll-total-label">(${state.total} total)</span>
        </div>
        <div class="coll-page-controls">
            <button class="coll-page-btn" onclick="Collection.setPage(${state.page - 1})" ${prevDisabled}>← Prev</button>
            <button class="coll-page-btn" onclick="Collection.setPage(${state.page + 1})" ${nextDisabled}>Next →</button>
        </div>
        <div class="coll-page-size">
            Show:
            <select onchange="Collection.setPageSize(parseInt(this.value,10))">
                ${[25, 50, 100].map(n =>
                    `<option value="${n}" ${state.pageSize === n ? 'selected' : ''}>${n}</option>`
                ).join('')}
            </select>
        </div>`;
    }

    function renderCountBadge() {
        const el = document.getElementById('coll-count');
        if (el) el.textContent = `${state.total.toLocaleString()} card${state.total !== 1 ? 's' : ''}`;
    }

    // ── Sort / Page / Filter Actions ─────────────────────────

    function setSort(field) {
        if (state.sortField === field) {
            state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
            state.sortField = field;
            state.sortDir = 'asc';
        }
        state.page = 1;
        savePreferences();
        pushUrlState();
        fetchCollection();
    }

    function setPage(p) {
        const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
        state.page = Math.max(1, Math.min(p, totalPages));
        pushUrlState();
        fetchCollection();
    }

    function setPageSize(n) {
        state.pageSize = n;
        state.page = 1;
        savePreferences();
        pushUrlState();
        fetchCollection();
    }

    function toggleColor(color) {
        const idx = state.filters.colors.indexOf(color);
        if (idx >= 0) {
            state.filters.colors.splice(idx, 1);
        } else {
            state.filters.colors.push(color);
        }
        state.page = 1;
        pushUrlState();
        refreshFiltersPanel();
        fetchCollection();
    }

    function toggleType(type) {
        const idx = state.filters.types.indexOf(type);
        if (idx >= 0) {
            state.filters.types.splice(idx, 1);
        } else {
            state.filters.types.push(type);
        }
        state.page = 1;
        pushUrlState();
        fetchCollection();
    }

    function toggleFilter(key) {
        state.filters[key] = !state.filters[key];
        state.page = 1;
        pushUrlState();
        refreshFiltersPanel();
        fetchCollection();
    }

    function setFinish(value) {
        state.filters.finish = value;
        state.page = 1;
        pushUrlState();
        fetchCollection();
    }

    function setCmcRange() {
        const minEl = document.getElementById('coll-cmc-min');
        const maxEl = document.getElementById('coll-cmc-max');
        state.filters.cmcMin = minEl?.value !== '' ? parseFloat(minEl.value) : null;
        state.filters.cmcMax = maxEl?.value !== '' ? parseFloat(maxEl.value) : null;
        state.page = 1;
        pushUrlState();
        fetchCollection();
    }

    function setPriceRange() {
        const minEl = document.getElementById('coll-price-min');
        const maxEl = document.getElementById('coll-price-max');
        state.filters.priceMin = minEl?.value !== '' ? parseFloat(minEl.value) : null;
        state.filters.priceMax = maxEl?.value !== '' ? parseFloat(maxEl.value) : null;
        state.page = 1;
        pushUrlState();
        fetchCollection();
    }

    function toggleCategoryFilter(cat) {
        const idx = state.filters.category.indexOf(cat);
        if (idx >= 0) {
            state.filters.category.splice(idx, 1);
        } else {
            state.filters.category.push(cat);
        }
        state.page = 1;
        pushUrlState();
        refreshFiltersPanel();
        fetchCollection();
    }

    // ── New filter action handlers ────────────────────────────

    function toggleRarity(value) {
        const idx = state.filters.rarity.indexOf(value);
        if (idx >= 0) state.filters.rarity.splice(idx, 1);
        else state.filters.rarity.push(value);
        state.page = 1;
        pushUrlState();
        refreshFiltersPanel();
        fetchCollection();
    }

    function setPowerRange() {
        const minEl = document.getElementById('coll-pow-min');
        const maxEl = document.getElementById('coll-pow-max');
        state.filters.powerMin = minEl?.value !== '' ? parseFloat(minEl.value) : null;
        state.filters.powerMax = maxEl?.value !== '' ? parseFloat(maxEl.value) : null;
        state.page = 1;
        pushUrlState();
        fetchCollection();
    }

    function setToughRange() {
        const minEl = document.getElementById('coll-tgh-min');
        const maxEl = document.getElementById('coll-tgh-max');
        state.filters.toughMin = minEl?.value !== '' ? parseFloat(minEl.value) : null;
        state.filters.toughMax = maxEl?.value !== '' ? parseFloat(maxEl.value) : null;
        state.page = 1;
        pushUrlState();
        fetchCollection();
    }

    function setEdhrecRange() {
        const minEl = document.getElementById('coll-edhrec-min');
        const maxEl = document.getElementById('coll-edhrec-max');
        state.filters.edhrecMin = minEl?.value !== '' ? parseInt(minEl.value) : null;
        state.filters.edhrecMax = maxEl?.value !== '' ? parseInt(maxEl.value) : null;
        state.page = 1;
        pushUrlState();
        fetchCollection();
    }

    function setQtyRange() {
        const minEl = document.getElementById('coll-qty-min');
        const maxEl = document.getElementById('coll-qty-max');
        state.filters.qtyMin = minEl?.value !== '' ? parseInt(minEl.value) : null;
        state.filters.qtyMax = maxEl?.value !== '' ? parseInt(maxEl.value) : null;
        state.page = 1;
        pushUrlState();
        fetchCollection();
    }

    // Set autocomplete
    async function loadSetsCache() {
        if (state.cachedSets.length) return;
        try {
            const res = await fetch(API_BASE + '/api/collection/sets');
            if (res.ok) state.cachedSets = await res.json();
        } catch (e) { /* ignore */ }
    }

    function onSetInput(val) {
        const dd = document.getElementById('coll-set-dropdown');
        if (!dd) return;
        if (!val || val.length < 1) { dd.innerHTML = ''; dd.style.display = 'none'; return; }
        const q = val.toLowerCase();
        const matches = state.cachedSets
            .filter(s => !state.filters.setCode.includes(s.code))
            .filter(s => s.code.toLowerCase().includes(q) || (s.name || '').toLowerCase().includes(q))
            .slice(0, 12);
        if (!matches.length) { dd.innerHTML = ''; dd.style.display = 'none'; return; }
        dd.style.display = 'block';
        dd.innerHTML = matches.map(s =>
            `<div class="coll-set-dd-item" onclick="Collection.addSetFilter('${escapeAttr(s.code)}')">
                <span class="coll-set-dd-code">${escapeHtml(s.code)}</span>
                <span class="coll-set-dd-name">${escapeHtml(s.name || '')}</span>
            </div>`
        ).join('');
    }

    function addSetFilter(code) {
        if (!state.filters.setCode.includes(code)) {
            state.filters.setCode.push(code);
            state.page = 1;
            pushUrlState();
            refreshFiltersPanel();
            fetchCollection();
        }
        const dd = document.getElementById('coll-set-dropdown');
        if (dd) { dd.innerHTML = ''; dd.style.display = 'none'; }
    }

    function removeSetFilter(code) {
        state.filters.setCode = state.filters.setCode.filter(c => c !== code);
        state.page = 1;
        pushUrlState();
        refreshFiltersPanel();
        fetchCollection();
    }

    // Keyword autocomplete
    async function loadKeywordsCache() {
        if (state.cachedKeywords.length) return;
        try {
            const res = await fetch(API_BASE + '/api/collection/keywords');
            if (res.ok) state.cachedKeywords = await res.json();
        } catch (e) { /* ignore */ }
    }

    function onKwInput(val) {
        const dd = document.getElementById('coll-kw-dropdown');
        if (!dd) return;
        if (!val || val.length < 1) { dd.innerHTML = ''; dd.style.display = 'none'; return; }
        const q = val.toLowerCase();
        const matches = state.cachedKeywords
            .filter(k => !state.filters.keyword.includes(k))
            .filter(k => k.toLowerCase().includes(q))
            .slice(0, 12);
        if (!matches.length) { dd.innerHTML = ''; dd.style.display = 'none'; return; }
        dd.style.display = 'block';
        dd.innerHTML = matches.map(k =>
            `<div class="coll-kw-dd-item" onclick="Collection.addKeywordFilter('${escapeAttr(k)}')">
                ${escapeHtml(k)}
            </div>`
        ).join('');
    }

    function addKeywordFilter(kw) {
        if (!state.filters.keyword.includes(kw)) {
            state.filters.keyword.push(kw);
            state.page = 1;
            pushUrlState();
            refreshFiltersPanel();
            fetchCollection();
        }
        const dd = document.getElementById('coll-kw-dropdown');
        if (dd) { dd.innerHTML = ''; dd.style.display = 'none'; }
    }

    function removeKeywordFilter(kw) {
        state.filters.keyword = state.filters.keyword.filter(k => k !== kw);
        state.page = 1;
        pushUrlState();
        refreshFiltersPanel();
        fetchCollection();
    }

    function resetFilters() {
        state.filters = {
            colors: [], types: [], isLegendary: false, isBasic: false,
            isGameChanger: false, highSalt: false, finish: '',
            cmcMin: null, cmcMax: null, priceMin: null, priceMax: null,
            category: [], rarity: [], setCode: [],
            powerMin: null, powerMax: null, toughMin: null, toughMax: null,
            keyword: [], edhrecMin: null, edhrecMax: null,
            qtyMin: null, qtyMax: null,
        };
        state.page = 1;
        state.search = '';
        const searchEl = document.getElementById('coll-search');
        if (searchEl) searchEl.value = '';
        pushUrlState();
        refreshFiltersPanel();
        fetchCollection();
    }

    function refreshFiltersPanel() {
        const panel = document.getElementById('coll-filters');
        if (panel) panel.innerHTML = renderFiltersHtml();
    }

    // ── Detail Drawer ────────────────────────────────────────

    async function openDrawer(cardId) {
        state.selectedCard = null;
        state.edhrecData = null;
        state.drawerTab = 'overview';

        const drawer = document.getElementById('coll-drawer');
        const backdrop = document.getElementById('coll-drawer-backdrop');
        const inner = document.getElementById('coll-drawer-inner');
        if (!drawer) return;

        drawer.classList.add('open');
        if (backdrop) backdrop.classList.add('open');
        state.drawerOpen = true;

        inner.innerHTML = `<div class="coll-drawer-loading"><div class="coll-spinner"></div></div>`;

        try {
            const card = await fetchCardDetail(cardId);
            state.selectedCard = card;
            renderDrawer();
        } catch (err) {
            inner.innerHTML = `<div class="coll-drawer-error">Failed to load card: ${escapeHtml(err.message)}</div>`;
        }
    }

    function closeDrawer() {
        const drawer = document.getElementById('coll-drawer');
        const backdrop = document.getElementById('coll-drawer-backdrop');
        if (drawer) drawer.classList.remove('open');
        if (backdrop) backdrop.classList.remove('open');
        state.drawerOpen = false;
        state.selectedCard = null;
        closeCategoryPopover();
    }

    function renderDrawer() {
        const inner = document.getElementById('coll-drawer-inner');
        if (!inner || !state.selectedCard) return;
        const card = state.selectedCard;

        const tabContent = renderDrawerTabContent();

        inner.innerHTML = `
        <div class="coll-drawer-header">
            <div class="coll-drawer-header-top">
                <span class="coll-drawer-card-name">${escapeHtml(card.name)}</span>
                <button class="coll-drawer-close" onclick="Collection.closeDrawer()">✕</button>
            </div>
            <div class="coll-drawer-meta">
                ${renderColorPips(card.colorIdentity)}
                <span class="coll-drawer-type">${escapeHtml(card.typeLine || '')}</span>
                ${card.isLegendary ? '<span class="coll-legendary-icon" title="Legendary">◆ Legendary</span>' : ''}
            </div>
        </div>

        <div class="coll-drawer-body">
            <div class="coll-drawer-image-wrap">
                ${card.imageUrl
                    ? `<img class="coll-drawer-image" src="${escapeAttr(card.imageUrl)}" alt="${escapeAttr(card.name)}" loading="lazy">`
                    : `<div class="coll-drawer-no-image">No Image</div>`}
            </div>

            <div class="coll-drawer-tabs">
                <button class="coll-tab-btn ${state.drawerTab === 'overview' ? 'active' : ''}"
                        onclick="Collection.switchDrawerTab('overview')">Overview</button>
                <button class="coll-tab-btn ${state.drawerTab === 'edhrec' ? 'active' : ''}"
                        onclick="Collection.switchDrawerTab('edhrec')">EDHREC</button>
                <button class="coll-tab-btn ${state.drawerTab === 'decks' ? 'active' : ''}"
                        onclick="Collection.switchDrawerTab('decks')">Sample Decks</button>
            </div>

            <div class="coll-drawer-tab-content" id="coll-drawer-tab-content">
                ${tabContent}
            </div>
        </div>`;
    }

    function renderDrawerTabContent() {
        if (state.drawerTab === 'overview') return renderOverviewTab();
        if (state.drawerTab === 'edhrec')   return renderEdhrecTab();
        if (state.drawerTab === 'decks')    return renderDecksTab();
        return '';
    }

    function renderOverviewTab() {
        const card = state.selectedCard;
        if (!card) return '';

        const categories = Array.isArray(card.category) ? card.category : [];
        const tags = card.tags ? card.tags.split(',').map(t => t.trim()).filter(Boolean) : [];

        const catChips = categories.map(cat =>
            `<span class="coll-drawer-cat-chip">${escapeHtml(cat)}
                <button class="coll-chip-remove" onclick="Collection.removeDrawerCategory('${escapeAttr(cat)}')">×</button>
            </span>`
        ).join('');

        const catSuggestions = CATEGORY_SUGGESTIONS.filter(s => !categories.includes(s)).map(s =>
            `<button class="coll-cat-suggest-btn" onclick="Collection.addDrawerCategory('${escapeAttr(s)}')">${escapeHtml(s)}</button>`
        ).join('');

        const _mc = card.manaCost || card.mana_cost || '';
        const _pw = card.power || '';
        const _tg = card.toughness || '';
        const _pt = (_pw || _tg) ? `${_pw || '—'}/${_tg || '—'}` : '';
        const _rr = card.rarity || '';
        const _sn = card.setName || card.set_name || '';
        const _er = card.edhrecRank || card.edhrec_rank || 0;

        return `
        <div class="coll-overview-grid">
            <div class="coll-overview-row"><span class="coll-ov-label">Mana Cost</span><span>${renderManaCost(_mc)}</span></div>
            <div class="coll-overview-row"><span class="coll-ov-label">CMC</span><span>${card.cmc ?? '—'}</span></div>
            ${_pt ? `<div class="coll-overview-row"><span class="coll-ov-label">P/T</span><span>${escapeHtml(_pt)}</span></div>` : ''}
            <div class="coll-overview-row"><span class="coll-ov-label">Rarity</span><span class="coll-rarity coll-rarity-${escapeAttr(_rr)}">${escapeHtml(_rr || '—')}</span></div>
            <div class="coll-overview-row"><span class="coll-ov-label">Set</span>
                <span>${escapeHtml(_sn || card.setCode || card.set_code || '')} ${card.collectorNumber || card.collector_number ? `#${escapeHtml(card.collectorNumber || card.collector_number)}` : ''}</span>
            </div>
            <div class="coll-overview-row"><span class="coll-ov-label">Price</span><span>${formatPrice(card.tcgPrice || card.tcg_price)}</span></div>
            ${_er ? `<div class="coll-overview-row"><span class="coll-ov-label">EDHREC Rank</span><span>#${_er}</span></div>` : ''}
            <div class="coll-overview-row"><span class="coll-ov-label">Salt</span>
                <span class="${saltClass(card.saltScore ?? card.salt_score)}">${(card.saltScore ?? card.salt_score) != null ? Number(card.saltScore ?? card.salt_score).toFixed(2) : '—'}</span>
            </div>
            <div class="coll-overview-row"><span class="coll-ov-label">Game Changer</span>
                <span>${(card.isGameChanger || card.is_game_changer) ? '★ Yes' : 'No'}</span>
            </div>
            <div class="coll-overview-row"><span class="coll-ov-label">Finish</span><span>${renderFinishBadge(card.finish)}</span></div>
            ${card.keywords && card.keywords.length
                ? `<div class="coll-overview-row"><span class="coll-ov-label">Keywords</span><span>${escapeHtml(card.keywords.join(', '))}</span></div>`
                : ''}
        </div>

        ${card.oracleText
            ? `<div class="coll-oracle-text">${escapeHtml(card.oracleText).replace(/\n/g, '<br>')}</div>`
            : ''}

        <div class="coll-drawer-section">
            <div class="coll-drawer-section-label">Finish</div>
            <select class="coll-finish-select" id="coll-drawer-finish"
                    onchange="Collection.saveCardEdits()">
                <option value="NORMAL"  ${card.finish === 'NORMAL'  || !card.finish ? 'selected' : ''}>Normal</option>
                <option value="FOIL"    ${card.finish === 'FOIL'   ? 'selected' : ''}>Foil</option>
                <option value="ETCHED"  ${card.finish === 'ETCHED' ? 'selected' : ''}>Etched</option>
            </select>
        </div>

        <div class="coll-drawer-section">
            <div class="coll-drawer-section-label">Categories</div>
            <div class="coll-drawer-cat-chips" id="coll-drawer-cat-chips">${catChips}</div>
            <div class="coll-cat-suggestions">${catSuggestions}</div>
            <div class="coll-cat-add-row">
                <input type="text" id="coll-drawer-cat-input" class="coll-cat-input"
                       placeholder="Add custom category…" autocomplete="off"
                       onkeydown="if(event.key==='Enter'){Collection.addDrawerCategoryFromInput();event.preventDefault()}" />
                <button class="coll-cat-add-btn" onclick="Collection.addDrawerCategoryFromInput()">Add</button>
            </div>
        </div>

        <div class="coll-drawer-section">
            <div class="coll-drawer-section-label">Tags</div>
            <div class="coll-drawer-tags" id="coll-drawer-tags">
                ${tags.map(tag =>
                    `<span class="coll-drawer-tag-chip">${escapeHtml(tag)}
                        <button class="coll-chip-remove" onclick="Collection.removeDrawerTag('${escapeAttr(tag)}')">×</button>
                    </span>`
                ).join('')}
            </div>
            <div class="coll-tag-add-row">
                <input type="text" id="coll-drawer-tag-input" class="coll-cat-input"
                       placeholder="Add tag…" autocomplete="off"
                       onkeydown="if(event.key==='Enter'){Collection.addDrawerTagFromInput();event.preventDefault()}" />
                <button class="coll-cat-add-btn" onclick="Collection.addDrawerTagFromInput()">Add</button>
            </div>
        </div>

        <div class="coll-drawer-section">
            <div class="coll-drawer-section-label">Notes</div>
            <textarea id="coll-drawer-notes" class="coll-notes-textarea" rows="4"
                      placeholder="Notes about this card in your collection…"
                      onblur="Collection.saveCardEdits()">${escapeHtml(card.notes || '')}</textarea>
        </div>

        <div class="coll-drawer-save-row">
            <button class="coll-save-btn" onclick="Collection.saveCardEdits()">Save Changes</button>
            <span class="coll-save-status" id="coll-save-status"></span>
        </div>`;
    }

    function renderEdhrecTab() {
        if (state.edhrecLoading) {
            return `<div class="coll-edhrec-loading"><div class="coll-spinner"></div><span>Loading EDHREC data…</span></div>`;
        }
        if (!state.edhrecData) {
            return `<div class="coll-edhrec-prompt">
                <p>Fetch EDHREC recommendations for this card.</p>
                <button class="coll-edhrec-fetch-btn" onclick="Collection.loadEdhrecTab()">Load EDHREC Data</button>
            </div>`;
        }

        const data = state.edhrecData;
        const recs = data.recommendations || [];

        const links = data.links || {};
        const linksHtml = [
            links.edhrecPage    && `<a class="coll-edhrec-link" href="${escapeAttr(links.edhrecPage)}" target="_blank" rel="noopener">EDHREC Page</a>`,
            links.archidektSearchUri && `<a class="coll-edhrec-link" href="${escapeAttr(links.archidektSearchUri)}" target="_blank" rel="noopener">Archidekt Search</a>`,
            links.moxfieldSearchUri  && `<a class="coll-edhrec-link" href="${escapeAttr(links.moxfieldSearchUri)}" target="_blank" rel="noopener">Moxfield Search</a>`,
        ].filter(Boolean).join('');

        if (recs.length === 0) {
            return `<div class="coll-edhrec-empty">
                <p>No EDHREC recommendations found.</p>
                ${linksHtml ? `<div class="coll-edhrec-links">${linksHtml}</div>` : ''}
            </div>`;
        }

        const recRows = recs.map(rec => `
            <div class="coll-edhrec-rec">
                <div class="coll-edhrec-rec-name">${escapeHtml(rec.name || '')}</div>
                <div class="coll-edhrec-rec-meta">
                    ${rec.role     ? `<span class="coll-edhrec-role">${escapeHtml(rec.role)}</span>` : ''}
                    ${rec.synergy  != null ? `<span class="coll-edhrec-synergy" title="Synergy score">${Number(rec.synergy).toFixed(0)}%</span>` : ''}
                    ${rec.inclusion != null ? `<span class="coll-edhrec-inclusion" title="Inclusion rate">${Number(rec.inclusion).toFixed(0)}%</span>` : ''}
                </div>
            </div>`).join('');

        return `
        <div class="coll-edhrec-recs">${recRows}</div>
        ${linksHtml ? `<div class="coll-edhrec-links">${linksHtml}</div>` : ''}`;
    }

    function renderDecksTab() {
        const card = state.selectedCard;
        if (!card) return '';

        const name = encodeURIComponent(card.name);
        const archidektUrl = `https://www.archidekt.com/search?q=${name}&format=commander`;
        const moxfieldUrl  = `https://www.moxfield.com/search?q=${name}`;
        const edhrecUrl    = `https://edhrec.com/cards/${name.toLowerCase().replace(/\s+/g, '-')}`;

        return `
        <div class="coll-decks-tab">
            <p class="coll-decks-hint">Search for decks featuring <strong>${escapeHtml(card.name)}</strong>:</p>
            <div class="coll-decks-links">
                <a class="coll-deck-link" href="${escapeAttr(archidektUrl)}" target="_blank" rel="noopener">
                    🏗️ Search Archidekt
                </a>
                <a class="coll-deck-link" href="${escapeAttr(moxfieldUrl)}" target="_blank" rel="noopener">
                    📚 Search Moxfield
                </a>
                <a class="coll-deck-link" href="${escapeAttr(edhrecUrl)}" target="_blank" rel="noopener">
                    📊 View on EDHREC
                </a>
            </div>
        </div>`;
    }

    function switchDrawerTab(tab) {
        state.drawerTab = tab;
        if (tab === 'edhrec' && !state.edhrecData && !state.edhrecLoading) {
            loadEdhrecTab();
            return;
        }
        const content = document.getElementById('coll-drawer-tab-content');
        if (content) content.innerHTML = renderDrawerTabContent();
        // Update tab button states
        document.querySelectorAll('.coll-tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.textContent.toLowerCase().includes(tab));
        });
    }

    async function loadEdhrecTab() {
        if (!state.selectedCard) return;
        state.edhrecLoading = true;
        state.edhrecData = null;
        const content = document.getElementById('coll-drawer-tab-content');
        if (content) content.innerHTML = renderEdhrecTab();

        try {
            const data = await fetchEdhrecData(state.selectedCard.id);
            state.edhrecData = data;
        } catch (err) {
            state.edhrecData = { error: err.message, recommendations: [], links: {} };
        } finally {
            state.edhrecLoading = false;
        }

        if (content) content.innerHTML = renderEdhrecTab();
    }

    // ── Drawer Editing ───────────────────────────────────────

    function addDrawerCategory(cat) {
        if (!state.selectedCard) return;
        const categories = Array.isArray(state.selectedCard.category) ? [...state.selectedCard.category] : [];
        if (!categories.includes(cat)) {
            categories.push(cat);
            state.selectedCard.category = categories;
            refreshDrawerCategories();
            saveCardEdits();
        }
    }

    function removeDrawerCategory(cat) {
        if (!state.selectedCard) return;
        state.selectedCard.category = (state.selectedCard.category || []).filter(c => c !== cat);
        refreshDrawerCategories();
        saveCardEdits();
    }

    function addDrawerCategoryFromInput() {
        const input = document.getElementById('coll-drawer-cat-input');
        if (!input) return;
        const val = input.value.trim();
        if (val) {
            addDrawerCategory(val);
            input.value = '';
        }
    }

    function refreshDrawerCategories() {
        const card = state.selectedCard;
        if (!card) return;
        const categories = Array.isArray(card.category) ? card.category : [];
        const chipsEl = document.getElementById('coll-drawer-cat-chips');
        if (chipsEl) {
            chipsEl.innerHTML = categories.map(cat =>
                `<span class="coll-drawer-cat-chip">${escapeHtml(cat)}
                    <button class="coll-chip-remove" onclick="Collection.removeDrawerCategory('${escapeAttr(cat)}')">×</button>
                </span>`
            ).join('');
        }
        // Refresh suggestions
        const suggestEl = document.querySelector('.coll-cat-suggestions');
        if (suggestEl) {
            const catSuggestions = CATEGORY_SUGGESTIONS.filter(s => !categories.includes(s)).map(s =>
                `<button class="coll-cat-suggest-btn" onclick="Collection.addDrawerCategory('${escapeAttr(s)}')">${escapeHtml(s)}</button>`
            ).join('');
            suggestEl.innerHTML = catSuggestions;
        }
    }

    function addDrawerTagFromInput() {
        const input = document.getElementById('coll-drawer-tag-input');
        if (!input || !state.selectedCard) return;
        const val = input.value.trim();
        if (!val) return;
        const tagsStr = state.selectedCard.tags || '';
        const tags = tagsStr.split(',').map(t => t.trim()).filter(Boolean);
        if (!tags.includes(val)) {
            tags.push(val);
            state.selectedCard.tags = tags.join(', ');
            refreshDrawerTags();
            saveCardEdits();
        }
        input.value = '';
    }

    function removeDrawerTag(tag) {
        if (!state.selectedCard) return;
        const tagsStr = state.selectedCard.tags || '';
        const tags = tagsStr.split(',').map(t => t.trim()).filter(t => t && t !== tag);
        state.selectedCard.tags = tags.join(', ');
        refreshDrawerTags();
        saveCardEdits();
    }

    function refreshDrawerTags() {
        const card = state.selectedCard;
        if (!card) return;
        const tags = (card.tags || '').split(',').map(t => t.trim()).filter(Boolean);
        const tagsEl = document.getElementById('coll-drawer-tags');
        if (tagsEl) {
            tagsEl.innerHTML = tags.map(tag =>
                `<span class="coll-drawer-tag-chip">${escapeHtml(tag)}
                    <button class="coll-chip-remove" onclick="Collection.removeDrawerTag('${escapeAttr(tag)}')">×</button>
                </span>`
            ).join('');
        }
    }

    async function saveCardEdits() {
        if (!state.selectedCard) return;
        const card = state.selectedCard;
        const notesEl  = document.getElementById('coll-drawer-notes');
        const finishEl = document.getElementById('coll-drawer-finish');
        const statusEl = document.getElementById('coll-save-status');

        const payload = {
            category: card.category || [],
            tags:     card.tags || '',
            notes:    notesEl?.value  ?? card.notes ?? '',
            finish:   finishEl?.value ?? card.finish ?? 'NORMAL',
        };

        if (statusEl) statusEl.textContent = 'Saving…';
        try {
            const updated = await patchCard(card.id, payload);
            state.selectedCard = { ...card, ...updated };
            if (statusEl) {
                statusEl.textContent = 'Saved ✓';
                statusEl.className = 'coll-save-status saved';
                setTimeout(() => { if (statusEl) { statusEl.textContent = ''; statusEl.className = 'coll-save-status'; } }, 2000);
            }
            // Refresh table row category
            refreshTableRow(card.id);
        } catch (err) {
            if (statusEl) {
                statusEl.textContent = `Error: ${err.message}`;
                statusEl.className = 'coll-save-status error';
            }
        }
    }

    function updateCategory(cardId, categories) {
        const card = state.items.find(c => c.id === cardId);
        if (card) {
            card.category = categories;
            patchCard(cardId, { category: categories }).catch(err =>
                console.error('[Collection] updateCategory error:', err)
            );
            refreshTableRow(cardId);
        }
    }

    function refreshTableRow(cardId) {
        const row = document.querySelector(`.coll-row[data-id="${cardId}"]`);
        if (!row) return;
        const card = state.items.find(c => c.id === cardId);
        if (!card && state.selectedCard?.id === cardId) {
            // update from drawer
            const updated = state.selectedCard;
            const catTd = row.querySelector('.coll-td-category');
            if (catTd) catTd.innerHTML = renderCategoryChips(updated.category || [], cardId);
            return;
        }
        if (!card) return;
        const catTd = row.querySelector('.coll-td-category');
        if (catTd) catTd.innerHTML = renderCategoryChips(card.category || [], cardId);
    }

    // ── Category Popover (inline table) ──────────────────────

    let popoverCardId = null;

    function openCategoryPopover(cardId, chipEl) {
        popoverCardId = cardId;
        const card = state.items.find(c => c.id === cardId);
        const categories = Array.isArray(card?.category) ? [...card.category] : [];

        const popover = document.getElementById('coll-cat-popover');
        if (!popover) return;

        const chipRect = chipEl.getBoundingClientRect();
        popover.style.display = 'block';
        popover.style.top  = (chipRect.bottom + window.scrollY + 4) + 'px';
        popover.style.left = (chipRect.left  + window.scrollX)      + 'px';

        const catChips = categories.map(cat =>
            `<span class="coll-popover-chip">${escapeHtml(cat)}
                <button class="coll-chip-remove" onclick="Collection.popoverRemoveCat('${escapeAttr(cat)}')">×</button>
            </span>`
        ).join('');

        const catSuggestions = CATEGORY_SUGGESTIONS.filter(s => !categories.includes(s)).map(s =>
            `<button class="coll-popover-suggest-btn" onclick="Collection.popoverAddCat('${escapeAttr(s)}')">${escapeHtml(s)}</button>`
        ).join('');

        popover.innerHTML = `
        <div class="coll-popover-header">
            <span>Edit Categories</span>
            <button class="coll-popover-close" onclick="Collection.closeCategoryPopover()">✕</button>
        </div>
        <div class="coll-popover-chips" id="coll-popover-chips">${catChips}</div>
        <div class="coll-popover-suggestions">${catSuggestions}</div>
        <div class="coll-popover-add-row">
            <input type="text" id="coll-popover-input" class="coll-cat-input" placeholder="Custom…" autocomplete="off"
                   onkeydown="if(event.key==='Enter'){Collection.popoverAddCatFromInput();event.preventDefault()}" />
            <button class="coll-cat-add-btn" onclick="Collection.popoverAddCatFromInput()">Add</button>
        </div>`;
    }

    function closeCategoryPopover() {
        const popover = document.getElementById('coll-cat-popover');
        if (popover) popover.style.display = 'none';
        popoverCardId = null;
    }

    function popoverAddCat(cat) {
        if (popoverCardId == null) return;
        const card = state.items.find(c => c.id === popoverCardId);
        if (!card) return;
        if (!Array.isArray(card.category)) card.category = [];
        if (!card.category.includes(cat)) {
            card.category.push(cat);
            updateCategory(popoverCardId, card.category);
            openCategoryPopover(popoverCardId, document.querySelector(`.coll-row[data-id="${popoverCardId}"] .coll-cat-chip`) || document.getElementById('coll-cat-popover'));
        }
    }

    function popoverRemoveCat(cat) {
        if (popoverCardId == null) return;
        const card = state.items.find(c => c.id === popoverCardId);
        if (!card) return;
        card.category = (card.category || []).filter(c => c !== cat);
        updateCategory(popoverCardId, card.category);
        // Re-render popover chips
        const chipsEl = document.getElementById('coll-popover-chips');
        if (chipsEl) {
            chipsEl.innerHTML = card.category.map(c =>
                `<span class="coll-popover-chip">${escapeHtml(c)}
                    <button class="coll-chip-remove" onclick="Collection.popoverRemoveCat('${escapeAttr(c)}')">×</button>
                </span>`
            ).join('');
        }
    }

    function popoverAddCatFromInput() {
        const input = document.getElementById('coll-popover-input');
        if (!input) return;
        const val = input.value.trim();
        if (val) {
            popoverAddCat(val);
            input.value = '';
        }
    }

    // ── Import Flow ──────────────────────────────────────────

    function openImport() {
        state.importStep = 1;
        state.importSource = '';
        state.importContent = '';
        state.importMapping = {};
        state.importHeaders = [];
        state.importMode = 'MERGE';
        state.importMissingFinishNormal = true;
        const modal = document.getElementById('coll-import-modal');
        if (modal) modal.classList.add('active');
        renderImportStep();
    }

    function closeImport() {
        const modal = document.getElementById('coll-import-modal');
        if (modal) modal.classList.remove('active');
        state.importStep = 0;
    }

    function importNext() {
        if (state.importStep === 1) {
            if (!state.importSource) {
                alert('Please select a source type.');
                return;
            }
            state.importStep = 2;
        } else if (state.importStep === 2) {
            if (!state.importContent.trim()) {
                alert('Please provide import content.');
                return;
            }
            if (state.importSource !== 'TEXT') {
                // Parse CSV headers
                const lines = state.importContent.split('\n');
                if (lines.length > 0) {
                    state.importHeaders = parseCSVLine(lines[0]);
                    buildDefaultMapping();
                }
                state.importStep = 3;
            } else {
                state.importStep = 4;
            }
        } else if (state.importStep === 3) {
            state.importStep = 4;
        }
        renderImportStep();
    }

    function importPrev() {
        if (state.importStep > 1) {
            if (state.importStep === 4 && state.importSource !== 'TEXT') {
                state.importStep = 3;
            } else if (state.importStep === 4 && state.importSource === 'TEXT') {
                state.importStep = 2;
            } else {
                state.importStep--;
            }
            renderImportStep();
        }
    }

    function parseCSVLine(line) {
        const result = [];
        let cur = '';
        let inQuote = false;
        for (let i = 0; i < line.length; i++) {
            const ch = line[i];
            if (ch === '"') {
                inQuote = !inQuote;
            } else if (ch === ',' && !inQuote) {
                result.push(cur.trim());
                cur = '';
            } else {
                cur += ch;
            }
        }
        result.push(cur.trim());
        return result;
    }

    function buildDefaultMapping() {
        const preset = state.importSource === 'MOXFIELD'  ? MOXFIELD_DEFAULTS
                     : state.importSource === 'ARCHIDEKT' ? ARCHIDEKT_DEFAULTS
                     : {};
        state.importMapping = {};
        state.importHeaders.forEach(header => {
            state.importMapping[header] = preset[header] || 'IGNORE';
        });
    }

    function renderImportStep() {
        const body = document.getElementById('coll-import-body');
        if (!body) return;

        const stepLabels = ['', 'Source', 'Content', 'Mapping', 'Options'];
        const steps = [1,2,3,4].filter(n => !(n === 3 && state.importSource === 'TEXT'));
        const stepIndicator = steps.map(n => {
            const active = n === state.importStep ? ' active' : '';
            const done   = n < state.importStep   ? ' done'   : '';
            return `<span class="coll-step-dot${active}${done}">${n}</span>`;
        }).join('<span class="coll-step-sep">—</span>');

        let content = '';
        if (state.importStep === 1) content = renderImportStep1();
        if (state.importStep === 2) content = renderImportStep2();
        if (state.importStep === 3) content = renderImportStep3();
        if (state.importStep === 4) content = renderImportStep4();

        const showPrev = state.importStep > 1;
        const isLastStep = state.importStep === 4;

        body.innerHTML = `
        <div class="coll-modal-header">
            <h3>Import Cards — Step ${state.importStep}: ${stepLabels[state.importStep]}</h3>
            <button class="coll-modal-close" onclick="Collection.closeImport()">✕</button>
        </div>
        <div class="coll-import-steps">${stepIndicator}</div>
        <div class="coll-import-step-content">${content}</div>
        <div class="coll-import-footer">
            ${showPrev ? `<button class="coll-btn-secondary" onclick="Collection.importPrev()">← Back</button>` : '<span></span>'}
            ${isLastStep
                ? `<button class="coll-btn-primary" onclick="Collection.submitImport()">Import</button>`
                : `<button class="coll-btn-primary" onclick="Collection.importNext()">Next →</button>`}
        </div>
        <div class="coll-import-status" id="coll-import-status"></div>`;
    }

    function renderImportStep1() {
        const sources = [
            { value: 'GENERIC_CSV', label: 'Generic CSV',  desc: 'Any CSV with column mapping' },
            { value: 'MOXFIELD',    label: 'Moxfield CSV', desc: 'Moxfield export format (auto-mapped)' },
            { value: 'ARCHIDEKT',   label: 'Archidekt CSV',desc: 'Archidekt export format (auto-mapped)' },
            { value: 'TEXT',        label: 'Plain Text',   desc: '1 Card Name (SET) per line' },
        ];
        return `<div class="coll-source-list">
            ${sources.map(s => {
                const checked = state.importSource === s.value ? 'checked' : '';
                return `<label class="coll-source-option ${state.importSource === s.value ? 'selected' : ''}">
                    <input type="radio" name="coll-import-source" value="${s.value}" ${checked}
                        onchange="Collection.setImportSource('${s.value}')">
                    <div class="coll-source-info">
                        <span class="coll-source-name">${s.label}</span>
                        <span class="coll-source-desc">${s.desc}</span>
                    </div>
                </label>`;
            }).join('')}
        </div>`;
    }

    function renderImportStep2() {
        if (state.importSource === 'TEXT') {
            return `<div class="coll-import-textarea-wrap">
                <label class="coll-form-label">Paste card list (one per line):</label>
                <textarea id="coll-import-textarea" class="coll-import-textarea" rows="14"
                    placeholder="3 Sol Ring (CMR)\n1 Arcane Signet\n1 Command Tower (MH3) 123"
                    oninput="Collection.setImportContent(this.value)">${escapeHtml(state.importContent)}</textarea>
                <div class="coll-import-hint">Formats: <code>3 Card Name (SET)</code> · <code>1 Card Name (SET) 123</code> · <code>Card Name</code></div>
            </div>`;
        }
        return `<div class="coll-import-file-wrap">
            <label class="coll-form-label">Upload CSV file:</label>
            <div class="coll-file-drop-zone" id="coll-file-drop">
                <input type="file" id="coll-file-input" accept=".csv,text/csv"
                       onchange="Collection.handleFileSelect(this.files[0])">
                <div class="coll-file-drop-label">
                    ${state.importContent
                        ? `<span class="coll-file-ok">✓ File loaded (${state.importContent.split('\n').length} lines)</span>`
                        : `<span>Click to select or drag &amp; drop a CSV file</span>`}
                </div>
            </div>
            ${state.importContent
                ? `<div class="coll-file-preview">
                    <div class="coll-file-preview-label">Preview (first 3 lines):</div>
                    <pre class="coll-file-preview-text">${escapeHtml(state.importContent.split('\n').slice(0,3).join('\n'))}</pre>
                   </div>`
                : ''}
        </div>`;
    }

    function renderImportStep3() {
        if (state.importHeaders.length === 0) {
            return `<p class="coll-import-warn">No headers detected. Please go back and check your file.</p>`;
        }

        const fieldOptsHtml = FIELD_OPTIONS.map(o =>
            `<option value="${o.value}">${o.label}</option>`
        ).join('');

        const rows = state.importHeaders.map(header => {
            const currentVal = state.importMapping[header] || 'IGNORE';
            const opts = FIELD_OPTIONS.map(o =>
                `<option value="${o.value}" ${currentVal === o.value ? 'selected' : ''}>${o.label}</option>`
            ).join('');
            return `<tr class="coll-mapping-row">
                <td class="coll-mapping-header">${escapeHtml(header)}</td>
                <td>
                    <select class="coll-mapping-select"
                            onchange="Collection.setImportMapping('${escapeAttr(header)}', this.value)">
                        ${opts}
                    </select>
                </td>
            </tr>`;
        }).join('');

        return `
        <div class="coll-mapping-hint">Map CSV columns to collection fields. Pre-filled for ${escapeHtml(state.importSource)} format.</div>
        <table class="coll-mapping-table">
            <thead><tr><th>CSV Column</th><th>Maps To</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
    }

    function renderImportStep4() {
        return `
        <div class="coll-import-options">
            <div class="coll-form-group">
                <div class="coll-form-label">Import Mode</div>
                <label class="coll-radio-label">
                    <input type="radio" name="coll-import-mode" value="MERGE"
                           ${state.importMode === 'MERGE' ? 'checked' : ''}
                           onchange="Collection.setImportMode('MERGE')">
                    <div>
                        <strong>Merge</strong>
                        <span class="coll-mode-desc">Add to existing collection (increase quantity on match)</span>
                    </div>
                </label>
                <label class="coll-radio-label">
                    <input type="radio" name="coll-import-mode" value="REPLACE"
                           ${state.importMode === 'REPLACE' ? 'checked' : ''}
                           onchange="Collection.setImportMode('REPLACE')">
                    <div>
                        <strong>Replace</strong>
                        <span class="coll-mode-desc">Clear collection first, then import</span>
                    </div>
                </label>
            </div>
            <div class="coll-form-group">
                <label class="coll-check-label">
                    <input type="checkbox" id="coll-missing-finish-normal"
                           ${state.importMissingFinishNormal ? 'checked' : ''}
                           onchange="Collection.setMissingFinishNormal(this.checked)">
                    Treat missing/unknown finish as Normal
                </label>
            </div>
            ${state.importMode === 'REPLACE'
                ? `<div class="coll-import-warn">⚠ Replace mode will <strong>permanently delete</strong> your existing collection before importing.</div>`
                : ''}
        </div>`;
    }

    function setImportSource(source) {
        state.importSource = source;
        // re-render step 1 to update selected state
        const body = document.getElementById('coll-import-body');
        if (body) renderImportStep();
    }

    function setImportContent(content) {
        state.importContent = content;
    }

    function setImportMapping(header, field) {
        state.importMapping[header] = field;
    }

    function setImportMode(mode) {
        state.importMode = mode;
        renderImportStep();
    }

    function setMissingFinishNormal(val) {
        state.importMissingFinishNormal = val;
    }

    function handleFileSelect(file) {
        if (!file) return;
        const reader = new FileReader();
        reader.onload = e => {
            state.importContent = e.target.result;
            renderImportStep();
        };
        reader.onerror = () => alert('Failed to read file.');
        reader.readAsText(file);
    }

    async function submitImport() {
        const statusEl = document.getElementById('coll-import-status');
        if (statusEl) statusEl.innerHTML = `<div class="coll-import-progress">Importing… <div class="coll-spinner-inline"></div></div>`;

        const payload = {
            source:  state.importSource,
            mode:    state.importMode,
            content: state.importContent,
            mapping: state.importMapping || {},
        };

        try {
            const res = await fetch(`${API_BASE}/api/collection/import`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json();

            if (!res.ok) {
                let msg = data.detail || data.message || `HTTP ${res.status}`;
                if (typeof msg === 'object') msg = JSON.stringify(msg);
                throw new Error(msg);
            }

            const { importedCount = 0, updatedCount = 0, failedCount = 0, errors = [] } = data;

            let html = `<div class="coll-import-result success">
                <div>✓ Import complete</div>
                <div>${importedCount} added · ${updatedCount} updated · ${failedCount} failed</div>
            </div>`;

            if (errors.length > 0) {
                html += `<div class="coll-import-errors">
                    <div class="coll-import-errors-label">Errors (${errors.length}):</div>
                    <ul>${errors.slice(0, 10).map(e => `<li>${escapeHtml(e)}</li>`).join('')}</ul>
                    ${errors.length > 10 ? `<div>…and ${errors.length - 10} more</div>` : ''}
                </div>`;
            }

            html += `<button class="coll-btn-primary" onclick="Collection.closeImport()">Close</button>`;
            if (statusEl) statusEl.innerHTML = html;

            // Hide footer nav buttons
            const footer = document.querySelector('.coll-import-footer');
            if (footer) footer.style.display = 'none';

            // Refresh collection
            applyColumnVisibility();
    await fetchCollection();

        } catch (err) {
            if (statusEl) {
                const msg = (err && err.message) ? err.message : String(err);
                statusEl.innerHTML = `<div class="coll-import-result error">✗ Import failed: ${escapeHtml(msg)}</div>`;
            }
        }
    }

    // ── Export Flow ──────────────────────────────────────────

    function openExport() {
        state.exportOpen = true;
        const modal = document.getElementById('coll-export-modal');
        if (modal) modal.classList.add('active');
        renderExportModal();
    }

    function closeExport() {
        state.exportOpen = false;
        const modal = document.getElementById('coll-export-modal');
        if (modal) modal.classList.remove('active');
    }

    function renderExportModal() {
        const body = document.getElementById('coll-export-body');
        if (!body) return;
        body.innerHTML = `
        <div class="coll-modal-header">
            <h3>Export Collection</h3>
            <button class="coll-modal-close" onclick="Collection.closeExport()">✕</button>
        </div>
        <div class="coll-export-form">
            <div class="coll-form-group">
                <label class="coll-form-label">Export Format</label>
                <select id="coll-export-format" class="coll-export-select">
                    <option value="INTERNAL_CSV">Internal CSV (all fields)</option>
                    <option value="MOXFIELD_CSV">Moxfield CSV</option>
                    <option value="TEXT">Plain Text</option>
                </select>
            </div>
            <div class="coll-form-group">
                <label class="coll-check-label">
                    <input type="checkbox" id="coll-export-filtered">
                    Export filtered results only (${state.total} matching)
                </label>
            </div>
            <div class="coll-form-group">
                <div class="coll-export-info">Total collection: ${state.total} cards</div>
            </div>
        </div>
        <div class="coll-modal-footer">
            <button class="coll-btn-secondary" onclick="Collection.closeExport()">Cancel</button>
            <button class="coll-btn-primary" onclick="Collection.submitExport()">Download</button>
        </div>`;
    }

    function submitExport() {
        const formatEl = document.getElementById('coll-export-format');
        const filteredEl = document.getElementById('coll-export-filtered');
        const format = formatEl?.value || 'INTERNAL_CSV';
        const useFilters = filteredEl?.checked || false;

        const params = new URLSearchParams();
        params.set('format', format);

        if (useFilters) {
            const f = state.filters;
            if (state.search) params.set('q', state.search);
            if (f.colors.length)    params.set('colors',    f.colors.join(','));
            if (f.types.length)     params.set('types',     f.types.join(','));
            if (f.finish)           params.set('finish',    f.finish);
            if (f.category.length)  params.set('category',  f.category.join(','));
            if (f.isLegendary)      params.set('isLegendary',   'true');
            if (f.isBasic)          params.set('isBasic',        'true');
            if (f.isGameChanger)    params.set('isGameChanger',  'true');
            if (f.highSalt)         params.set('highSalt',       'true');
            if (f.cmcMin != null)   params.set('cmcMin',   f.cmcMin);
            if (f.cmcMax != null)   params.set('cmcMax',   f.cmcMax);
            if (f.priceMin != null) params.set('priceMin', f.priceMin);
            if (f.priceMax != null) params.set('priceMax', f.priceMax);
        }

        const url = `${API_BASE}/api/collection/export?${params.toString()}`;
        const a = document.createElement('a');
        a.href = url;
        a.download = `collection_${format.toLowerCase()}_${new Date().toISOString().slice(0,10)}.${format === 'TEXT' ? 'txt' : 'csv'}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        closeExport();
    }

    // ── Re-enrich ────────────────────────────────────────────

    async function reEnrich() {
        const btn = document.querySelector('.coll-reenrich-btn');
        if (!btn) return;
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Refreshing...';

        try {
            const res = await fetch(`${API_BASE}/api/collection/re-enrich`, { method: 'POST' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const msg = `Refreshed ${data.enrichedCount} of ${data.total} cards`
                + (data.skippedCount > 0 ? ` (${data.skippedCount} skipped)` : '');
            alert(msg);
            fetchCollection(); // reload table
        } catch (err) {
            alert(`Re-enrich failed: ${err.message}`);
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }

    // ── Auto-Classify ────────────────────────────────────────

    async function autoClassify(forceAll = false) {
        const btn = document.querySelector('.coll-autoclassify-btn');
        if (!btn) return;
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Classifying...';

        try {
            const endpoint = forceAll
                ? `${API_BASE}/api/collection/auto-classify-all`
                : `${API_BASE}/api/collection/auto-classify`;
            const res = await fetch(endpoint, { method: 'POST' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const msg = `Classified ${data.classifiedCount} of ${data.total} cards`
                + (data.skippedCount > 0 ? ` (${data.skippedCount} already had categories)` : '');
            alert(msg);
            fetchCollection(); // reload table
        } catch (err) {
            alert(`Auto-classify failed: ${err.message}`);
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }

    // ── Navigation ───────────────────────────────────────────

    function goBack() {
        window.location.href = '/index.html';
    }

    // ── Bulk Row Selection & Quantity Edit ─────────────────────
    function toggleRowSelect(cardId, checked) {
        if (checked) {
            state.selectedRows.add(cardId);
        } else {
            state.selectedRows.delete(cardId);
        }
        updateBulkBar();
    }

    function toggleSelectAll(checked) {
        if (checked) {
            state.items.forEach(c => state.selectedRows.add(c.id));
        } else {
            state.selectedRows.clear();
        }
        // Update all checkboxes
        document.querySelectorAll('.coll-row-check').forEach(cb => {
            cb.checked = checked;
        });
        updateBulkBar();
    }

    function selectAllRows() {
        state.items.forEach(c => state.selectedRows.add(c.id));
        document.querySelectorAll('.coll-row-check').forEach(cb => cb.checked = true);
        const selectAllCb = document.getElementById('coll-select-all');
        if (selectAllCb) selectAllCb.checked = true;
        updateBulkBar();
    }

    function clearSelection() {
        state.selectedRows.clear();
        document.querySelectorAll('.coll-row-check').forEach(cb => cb.checked = false);
        const selectAllCb = document.getElementById('coll-select-all');
        if (selectAllCb) selectAllCb.checked = false;
        updateBulkBar();
    }

    function updateBulkBar() {
        const bar = document.getElementById('coll-bulk-bar');
        const countEl = document.getElementById('coll-bulk-count');
        const n = state.selectedRows.size;
        if (bar) bar.style.display = n > 0 ? 'flex' : 'none';
        if (countEl) countEl.textContent = `${n} selected`;
    }

    async function bulkAdjustQuantity(delta) {
        if (state.selectedRows.size === 0) return;
        const ids = [...state.selectedRows];
        const btn = event.target;
        if (btn) btn.disabled = true;
        let successCount = 0;
        for (const id of ids) {
            const card = state.items.find(c => c.id === id);
            if (!card) continue;
            const newQty = Math.max(0, (card.quantity ?? 1) + delta);
            try {
                await patchCard(id, { quantity: newQty });
                card.quantity = newQty;
                successCount++;
            } catch (e) {
                console.warn('[Bulk] Failed to update card', id, e);
            }
        }
        if (btn) btn.disabled = false;
        renderTable();
        applyColumnVisibility();
    }

    async function bulkSetQuantity() {
        if (state.selectedRows.size === 0) return;
        const input = document.getElementById('coll-bulk-qty-input');
        const newQty = input ? Math.max(0, parseInt(input.value, 10) || 0) : 0;
        const ids = [...state.selectedRows];
        const btn = document.querySelector('.coll-bulk-set-btn');
        if (btn) btn.disabled = true;
        for (const id of ids) {
            const card = state.items.find(c => c.id === id);
            if (!card) continue;
            try {
                await patchCard(id, { quantity: newQty });
                card.quantity = newQty;
            } catch (e) {
                console.warn('[Bulk] Failed to set card', id, e);
            }
        }
        if (btn) btn.disabled = false;
        renderTable();
        applyColumnVisibility();
    }

    // ── Event Binding ────────────────────────────────────────

    function bindEvents() {
        // Search input with debounce
        const searchEl = document.getElementById('coll-search');
        if (searchEl) {
            searchEl.addEventListener('input', e => {
                clearTimeout(searchDebounceTimer);
                searchDebounceTimer = setTimeout(() => {
                    state.search = e.target.value.trim();
                    state.page = 1;
                    pushUrlState();
                    fetchCollection();
                }, DEBOUNCE_MS);
            });
            searchEl.addEventListener('keydown', e => {
                if (e.key === 'Escape') {
                    searchEl.value = '';
                    state.search = '';
                    state.page = 1;
                    pushUrlState();
                    fetchCollection();
                }
            });
        }

        // Close drawer on Escape
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                if (state.drawerOpen) closeDrawer();
                if (state.importStep > 0) closeImport();
                if (state.exportOpen) closeExport();
                closeCategoryPopover();
            }
        });

        // Close popover on outside click
        document.addEventListener('click', e => {
            const popover = document.getElementById('coll-cat-popover');
            if (popover && popover.style.display !== 'none') {
                if (!popover.contains(e.target) && !e.target.classList.contains('coll-cat-chip')) {
                    closeCategoryPopover();
                }
            }
            // Close set/keyword dropdowns on outside click
            const setDD = document.getElementById('coll-set-dropdown');
            const setInput = document.getElementById('coll-set-input');
            if (setDD && setDD.style.display !== 'none' && !setDD.contains(e.target) && e.target !== setInput) {
                setDD.innerHTML = ''; setDD.style.display = 'none';
            }
            const kwDD = document.getElementById('coll-kw-dropdown');
            const kwInput = document.getElementById('coll-kw-input');
            if (kwDD && kwDD.style.display !== 'none' && !kwDD.contains(e.target) && e.target !== kwInput) {
                kwDD.innerHTML = ''; kwDD.style.display = 'none';
            }
        });

        // File drop zone
        const dropZone = document.getElementById('coll-file-drop');
        if (dropZone) {
            dropZone.addEventListener('dragover', e => {
                e.preventDefault();
                dropZone.classList.add('drag-over');
            });
            dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
            dropZone.addEventListener('drop', e => {
                e.preventDefault();
                dropZone.classList.remove('drag-over');
                const file = e.dataTransfer.files[0];
                if (file) handleFileSelect(file);
            });
        }
    }

    // ── Card Scanner ─────────────────────────────────────────

    let scanState = {
        file: null,
        previewUrl: null,
        mode: 'single',
        scanning: false,
        results: [],      // ScanResult dicts from API
        selected: new Set(),  // indices of results selected for add
    };

    function openScan() {
        scanState = { file: null, previewUrl: null, mode: 'single',
                      scanning: false, results: [], selected: new Set(),
                      manualCards: [] };
        const modal = document.getElementById('coll-scan-modal');
        if (modal) modal.classList.add('active');
        renderScanModal();
    }

    function closeScan() {
        const modal = document.getElementById('coll-scan-modal');
        if (modal) modal.classList.remove('active');
        // Revoke object URL to free memory
        if (scanState.previewUrl) {
            URL.revokeObjectURL(scanState.previewUrl);
            scanState.previewUrl = null;
        }
    }

    function renderScanModal() {
        const body = document.getElementById('coll-scan-body');
        if (!body) return;

        const hasResults = scanState.results.length > 0;
        const hasFile = scanState.file !== null;

        let content = '';

        if (hasResults) {
            content = renderScanResults();
        } else {
            content = renderScanUpload();
        }

        body.innerHTML = `
        <div class="coll-modal-header">
            <h2>Scan from Image</h2>
            <button class="coll-modal-close" onclick="Collection.closeScan()">\u2715</button>
        </div>
        <div class="coll-scan-content">${content}</div>
        <div class="coll-scan-status" id="coll-scan-status"></div>`;
    }

    function renderScanUpload() {
        const preview = scanState.previewUrl
            ? '<img class="coll-scan-preview-img" src="' + escapeAttr(scanState.previewUrl) + '" alt="Preview" />'
            : '';

        const singleChk = scanState.mode === 'single' ? 'checked' : '';
        const multiChk  = scanState.mode === 'multi'  ? 'checked' : '';
        const scanDisabled = scanState.file ? '' : 'disabled';
        const scanningCls = scanState.scanning ? ' scanning' : '';

        return `
        <div class="coll-scan-upload-area">
            <div class="coll-scan-dropzone" id="coll-scan-dropzone">
                ${preview || '<div class="coll-scan-dropzone-text">Drop card image here or click to browse</div>'}
                <input type="file" id="coll-scan-file" accept="image/*"
                       onchange="Collection.handleScanFile(this)" style="display:none" />
            </div>
            <div class="coll-scan-options">
                <div class="coll-scan-mode">
                    <label class="coll-radio-label">
                        <input type="radio" name="scan-mode" value="single" ${singleChk}
                               onchange="Collection.setScanMode('single')" />
                        Single card
                    </label>
                    <label class="coll-radio-label">
                        <input type="radio" name="scan-mode" value="multi" ${multiChk}
                               onchange="Collection.setScanMode('multi')" />
                        Multiple cards
                    </label>
                </div>
                <div class="coll-scan-hint">
                    Single: one card per photo. Multi: detects multiple cards in one image.
                </div>
            </div>
        </div>
        <div class="coll-scan-footer">
            <button class="coll-btn-secondary" onclick="Collection.closeScan()">Cancel</button>
            <button class="coll-btn-primary${scanningCls}" ${scanDisabled}
                    onclick="Collection.submitScan()">
                ${scanState.scanning ? '<span class="coll-spinner-inline"></span> Scanning...' : 'Scan Image'}
            </button>
        </div>`;
    }

    function renderScanResults() {
        const results = scanState.results;
        const selectedCount = scanState.selected.size;
        const manualCount = scanState.manualCards ? scanState.manualCards.length : 0;
        const totalAdd = selectedCount + manualCount;

        const rows = results.map((r, i) => {
            const checked = scanState.selected.has(i) ? 'checked' : '';
            const confCls = 'coll-scan-conf-' + (r.confidence || 'low');
            const confLabel = (r.confidence || 'low').charAt(0).toUpperCase() + (r.confidence || 'low').slice(1);

            if (r.error && !r.matched_name) {
                return `<div class="coll-scan-result-row coll-scan-error">
                    <div class="coll-scan-result-err-wrap">
                        <span class="coll-scan-result-err">${escapeHtml(r.error)}</span>
                        <div class="coll-scan-manual-row">
                            <input type="text" class="coll-scan-manual-input" data-err-idx="${i}"
                                   placeholder="Type card name..." autocomplete="off"
                                   onkeydown="if(event.key==='Enter')Collection.scanManualLookup(${i})" />
                            <button class="coll-btn-sm" onclick="Collection.scanManualLookup(${i})">Look up</button>
                        </div>
                    </div>
                </div>`;
            }

            const imgHtml = r.image_uri
                ? '<img class="coll-scan-result-img" src="' + escapeAttr(r.image_uri) + '" alt="' + escapeAttr(r.matched_name) + '" />'
                : '<div class="coll-scan-result-img-placeholder">No image</div>';

            return `<div class="coll-scan-result-row">
                <label class="coll-scan-result-check">
                    <input type="checkbox" ${checked}
                           onchange="Collection.toggleScanResult(${i})" />
                </label>
                ${imgHtml}
                <div class="coll-scan-result-info">
                    <div class="coll-scan-result-name">${escapeHtml(r.matched_name || r.raw_ocr)}</div>
                    <div class="coll-scan-result-meta">
                        <span class="${confCls}">${confLabel}</span>
                        ${r.set_code ? ' &middot; ' + escapeHtml(r.set_code.toUpperCase()) : ''}
                        ${r.collector_number ? ' #' + escapeHtml(r.collector_number) : ''}
                        ${r.rarity ? ' &middot; ' + escapeHtml(r.rarity.charAt(0).toUpperCase() + r.rarity.slice(1)) : ''}
                    </div>
                </div>
                <div class="coll-scan-result-qty">
                    <label>Qty</label>
                    <input type="number" min="1" value="1" class="coll-scan-qty-input"
                           data-scan-idx="${i}" />
                </div>
            </div>`;
        }).join('');

        // Manual cards added via name lookup
        const manualRows = (scanState.manualCards || []).map((mc, mi) => {
            return `<div class="coll-scan-result-row coll-scan-manual-added">
                <label class="coll-scan-result-check">
                    <input type="checkbox" checked disabled />
                </label>
                ${mc.image_uri
                    ? '<img class="coll-scan-result-img" src="' + escapeAttr(mc.image_uri) + '" alt="' + escapeAttr(mc.name) + '" />'
                    : '<div class="coll-scan-result-img-placeholder">No image</div>'}
                <div class="coll-scan-result-info">
                    <div class="coll-scan-result-name">${escapeHtml(mc.name)}</div>
                    <div class="coll-scan-result-meta">
                        <span class="coll-scan-conf-high">Manual</span>
                        ${mc.set_code ? ' &middot; ' + escapeHtml(mc.set_code.toUpperCase()) : ''}
                    </div>
                </div>
                <div class="coll-scan-result-qty">
                    <label>Qty</label>
                    <input type="number" min="1" value="1" class="coll-scan-manual-qty"
                           data-manual-idx="${mi}" />
                </div>
                <button class="coll-btn-sm coll-scan-remove-manual" onclick="Collection.scanRemoveManual(${mi})"
                        title="Remove">\u2715</button>
            </div>`;
        }).join('');

        return `
        <div class="coll-scan-results-wrap">
            <div class="coll-scan-results-header">
                <span>${results.length} card${results.length !== 1 ? 's' : ''} detected</span>
                <button class="coll-btn-link" onclick="Collection.scanSelectAll()">Select All</button>
                <button class="coll-btn-link" onclick="Collection.scanDeselectAll()">Deselect All</button>
            </div>
            <div class="coll-scan-results-list">
                ${rows}
                ${manualRows}
            </div>
            <div class="coll-scan-manual-add">
                <input type="text" id="coll-scan-manual-name" class="coll-scan-manual-input coll-scan-manual-input-bottom"
                       placeholder="Add card by name..." autocomplete="off"
                       onkeydown="if(event.key==='Enter')Collection.scanManualAdd()" />
                <button class="coll-btn-sm" onclick="Collection.scanManualAdd()">Add</button>
            </div>
        </div>
        <div class="coll-scan-footer">
            <button class="coll-btn-secondary" onclick="Collection.scanBack()">Scan Another</button>
            <button class="coll-btn-primary" ${totalAdd === 0 ? 'disabled' : ''}
                    onclick="Collection.submitScanAdd()">
                Add ${totalAdd} Card${totalAdd !== 1 ? 's' : ''} to Collection
            </button>
        </div>`;
    }

    function handleScanFile(input) {
        const file = input.files && input.files[0];
        if (!file) return;
        _setScanFile(file);
    }

    function _setScanFile(file) {
        if (scanState.previewUrl) URL.revokeObjectURL(scanState.previewUrl);
        scanState.file = file;
        scanState.previewUrl = URL.createObjectURL(file);
        scanState.results = [];
        scanState.selected = new Set();
        renderScanModal();
    }

    function setScanMode(mode) {
        scanState.mode = mode;
    }

    async function submitScan() {
        if (!scanState.file || scanState.scanning) return;
        scanState.scanning = true;
        renderScanModal();

        const formData = new FormData();
        formData.append('file', scanState.file);
        formData.append('mode', scanState.mode);

        try {
            const resp = await fetch(API_BASE + '/api/collection/scan', {
                method: 'POST',
                body: formData,
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({ detail: resp.statusText }));
                throw new Error(err.detail || resp.statusText);
            }
            const data = await resp.json();
            scanState.results = data.results || [];
            // Auto-select all high/medium confidence matches
            scanState.selected = new Set();
            scanState.results.forEach((r, i) => {
                if (r.matched_name && (r.confidence === 'high' || r.confidence === 'medium')) {
                    scanState.selected.add(i);
                }
            });
        } catch (e) {
            const statusEl = document.getElementById('coll-scan-status');
            if (statusEl) statusEl.innerHTML = '<div class="coll-scan-error-msg">Scan failed: ' + escapeHtml(e.message) + '</div>';
        } finally {
            scanState.scanning = false;
            renderScanModal();
        }
    }

    function toggleScanResult(idx) {
        if (scanState.selected.has(idx)) {
            scanState.selected.delete(idx);
        } else {
            scanState.selected.add(idx);
        }
        renderScanModal();
    }

    function scanSelectAll() {
        scanState.results.forEach((r, i) => {
            if (r.matched_name) scanState.selected.add(i);
        });
        renderScanModal();
    }

    function scanDeselectAll() {
        scanState.selected.clear();
        renderScanModal();
    }

    function scanBack() {
        scanState.results = [];
        scanState.selected = new Set();
        scanState.manualCards = [];
        renderScanModal();
    }

    async function scanManualLookup(errIdx) {
        const input = document.querySelector('input.coll-scan-manual-input[data-err-idx="' + errIdx + '"]');
        if (!input || !input.value.trim()) return;
        const name = input.value.trim();
        input.disabled = true;

        try {
            const lookupResp = await fetch('https://api.scryfall.com/cards/named?fuzzy=' + encodeURIComponent(name));
            if (!lookupResp.ok) {
                const err = await lookupResp.json().catch(() => ({}));
                throw new Error(err.details || 'Card not found on Scryfall');
            }
            const card = await lookupResp.json();
            const imageUris = card.image_uris || (card.card_faces && card.card_faces[0] ? card.card_faces[0].image_uris : {}) || {};

            // Replace the error result with a matched result
            scanState.results[errIdx] = {
                raw_ocr: name,
                matched_name: card.name,
                set_code: card.set || '',
                scryfall_id: card.id || '',
                confidence: 'high',
                image_uri: imageUris.normal || imageUris.small || '',
                error: '',
            };
            scanState.selected.add(errIdx);
            renderScanModal();
        } catch (e) {
            input.disabled = false;
            input.style.borderColor = 'var(--lab-danger, #f85149)';
            input.placeholder = e.message || 'Not found, try again';
            input.value = '';
        }
    }

    async function scanManualAdd() {
        const input = document.getElementById('coll-scan-manual-name');
        if (!input || !input.value.trim()) return;
        const name = input.value.trim();
        input.disabled = true;

        try {
            const lookupResp = await fetch('https://api.scryfall.com/cards/named?fuzzy=' + encodeURIComponent(name));
            if (!lookupResp.ok) {
                const err = await lookupResp.json().catch(() => ({}));
                throw new Error(err.details || 'Card not found on Scryfall');
            }
            const card = await lookupResp.json();
            const imageUris = card.image_uris || (card.card_faces && card.card_faces[0] ? card.card_faces[0].image_uris : {}) || {};

            if (!scanState.manualCards) scanState.manualCards = [];
            scanState.manualCards.push({
                name: card.name,
                set_code: card.set || '',
                image_uri: imageUris.normal || imageUris.small || '',
            });
            renderScanModal();
        } catch (e) {
            input.disabled = false;
            input.style.borderColor = 'var(--lab-danger, #f85149)';
            input.placeholder = e.message || 'Not found, try again';
            input.value = '';
        }
    }

    function scanRemoveManual(idx) {
        if (scanState.manualCards) {
            scanState.manualCards.splice(idx, 1);
            renderScanModal();
        }
    }

    async function submitScanAdd() {
        const cards = [];
        // OCR-matched cards
        scanState.selected.forEach(idx => {
            const r = scanState.results[idx];
            if (!r || !r.matched_name) return;
            const qtyInput = document.querySelector('input.coll-scan-qty-input[data-scan-idx="' + idx + '"]');
            const qty = qtyInput ? parseInt(qtyInput.value, 10) || 1 : 1;
            cards.push({
                name: r.matched_name,
                set_code: r.set_code || '',
                collector_number: r.collector_number || '',
                quantity: qty,
            });
        });
        // Manual cards
        (scanState.manualCards || []).forEach((mc, mi) => {
            const qtyInput = document.querySelector('input.coll-scan-manual-qty[data-manual-idx="' + mi + '"]');
            const qty = qtyInput ? parseInt(qtyInput.value, 10) || 1 : 1;
            cards.push({
                name: mc.name,
                set_code: mc.set_code || '',
                quantity: qty,
            });
        });

        if (cards.length === 0) return;

        const statusEl = document.getElementById('coll-scan-status');
        if (statusEl) statusEl.innerHTML = '<div class="coll-scan-progress">Adding cards... <span class="coll-spinner-inline"></span></div>';

        try {
            const resp = await fetch(API_BASE + '/api/collection/scan/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cards }),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({ detail: resp.statusText }));
                throw new Error(err.detail || resp.statusText);
            }
            const data = await resp.json();
            let msg = '';
            if (data.importedCount) msg += data.importedCount + ' added';
            if (data.updatedCount) msg += (msg ? ', ' : '') + data.updatedCount + ' updated';
            if (data.failedCount)  msg += (msg ? ', ' : '') + data.failedCount + ' failed';
            if (statusEl) statusEl.innerHTML = '<div class="coll-scan-success">' + escapeHtml(msg || 'Done') + '</div>';

            // Refresh collection after short delay
            setTimeout(() => {
                closeScan();
                fetchCollection();
            }, 1500);
        } catch (e) {
            if (statusEl) statusEl.innerHTML = '<div class="coll-scan-error-msg">Failed: ' + escapeHtml(e.message) + '</div>';
        }
    }

    // Bind scan dropzone click + drag events after render
    function _bindScanDropzone() {
        const dropzone = document.getElementById('coll-scan-dropzone');
        if (!dropzone) return;
        dropzone.addEventListener('click', () => {
            const input = document.getElementById('coll-scan-file');
            if (input) input.click();
        });
        dropzone.addEventListener('dragover', e => {
            e.preventDefault();
            dropzone.classList.add('drag-over');
        });
        dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
        dropzone.addEventListener('drop', e => {
            e.preventDefault();
            dropzone.classList.remove('drag-over');
            const file = e.dataTransfer.files[0];
            if (file) _setScanFile(file);
        });
    }

    // Patch renderScanModal to rebind dropzone after DOM update
    const _origRenderScanModal = renderScanModal;
    renderScanModal = function() {
        _origRenderScanModal();
        setTimeout(_bindScanDropzone, 0);
    };

    // ── Public API ───────────────────────────────────────────
    return {
        init,
        goBack,
        // Import
        openImport,
        closeImport,
        importNext,
        importPrev,
        submitImport,
        setImportSource,
        setImportContent,
        setImportMapping,
        setImportMode,
        setMissingFinishNormal,
        handleFileSelect,
        // Export
        openExport,
        closeExport,
        submitExport,
        // Scan
        openScan,
        closeScan,
        handleScanFile,
        setScanMode,
        submitScan,
        toggleScanResult,
        scanSelectAll,
        scanDeselectAll,
        scanBack,
        submitScanAdd,
        scanManualLookup,
        scanManualAdd,
        scanRemoveManual,
        // Drawer
        openDrawer,
        closeDrawer,
        switchDrawerTab,
        loadEdhrecTab,
        saveCardEdits,
        addDrawerCategory,
        removeDrawerCategory,
        addDrawerCategoryFromInput,
        addDrawerTagFromInput,
        removeDrawerTag,
        // Filters
        toggleColor,
        toggleType,
        toggleFilter,
        setFinish,
        setCmcRange,
        setPriceRange,
        toggleCategoryFilter,
        toggleRarity,
        setPowerRange,
        setToughRange,
        setEdhrecRange,
        setQtyRange,
        onSetInput,
        addSetFilter,
        removeSetFilter,
        onKwInput,
        addKeywordFilter,
        removeKeywordFilter,
        resetFilters,
        // Sort / page
        setSort,
        setSortFromBar,
        toggleSortDir,
        setPage,
        setPageSize,
        // Category inline
        updateCategory,
        openCategoryPopover,
        closeCategoryPopover,
        popoverAddCat,
        popoverRemoveCat,
        popoverAddCatFromInput,
        reEnrich,
        autoClassify,
        toggleStats,
        // Column visibility
        toggleColumn,
        openColumnPanel,
        closeColumnPanel,
        resetColumns,
        // Bulk selection & quantity
        toggleRowSelect,
        toggleSelectAll,
        selectAllRows,
        clearSelection,
        bulkAdjustQuantity,
        bulkSetQuantity,
    };
})();
