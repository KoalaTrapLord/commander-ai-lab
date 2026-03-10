/**
 * Commander AI Lab — Auto Deck Generator UI
 * ═══════════════════════════════════════════
 *
 * Endpoints consumed:
 *   GET   /api/deck-generator/config           — default ratios + source list
 *   GET   /api/deck-generator/commander-search  — autocomplete commanders
 *   POST  /api/deck-generator/preview           — generate preview deck
 *   POST  /api/deck-generator/commit            — save deck to Deck Builder
 */

const DeckGenerator = (() => {
    'use strict';

    const API_BASE = window.location.origin;
    const DEBOUNCE_MS = 350;

    const COLOR_MAP = {
        W: { label: 'W', cls: 'dg-pip-W' },
        U: { label: 'U', cls: 'dg-pip-U' },
        B: { label: 'B', cls: 'dg-pip-B' },
        R: { label: 'R', cls: 'dg-pip-R' },
        G: { label: 'G', cls: 'dg-pip-G' },
        C: { label: 'C', cls: 'dg-pip-C' },
    };

    const TYPE_ORDER = ['Creature', 'Instant', 'Sorcery', 'Artifact', 'Enchantment', 'Planeswalker', 'Land', 'Other'];
    const TYPE_ICONS = {
        'Creature': '🐉',
        'Instant': '⚡',
        'Sorcery': '🌀',
        'Artifact': '🔧',
        'Enchantment': '✨',
        'Planeswalker': '🌟',
        'Land': '🏔',
        'Other': '🃏',
    };

    // ── State ──────────────────────────────────────────────
    let state = {
        commander: null,         // { name, scryfall_id, color_identity, type_line, mana_cost, image_url }
        config: null,            // from /api/deck-generator/config
        sourceToggles: {},       // { archidekt: true, edhrec: true, ... }
        ratios: {},              // { target_land_count: 37, ... }
        previewResult: null,     // last preview result
        isLoading: false,
    };

    let searchTimeout = null;

    // ── DOM refs ────────────────────────────────────────────
    const $ = (id) => document.getElementById(id);

    // ── Init ────────────────────────────────────────────────
    async function init() {
        await loadConfig();
        bindEvents();
        checkQueryParams();
    }

    async function loadConfig() {
        try {
            const resp = await fetch(API_BASE + '/api/deck-generator/config');
            state.config = await resp.json();

            // Initialize ratios from defaults
            const defaults = state.config.defaults;
            state.ratios = { ...defaults };

            // Render source toggles
            renderSourceToggles(state.config.sources);

            // Render ratio sliders
            renderRatioSliders(defaults);

            // Initialize source toggles state
            for (const src of state.config.sources) {
                state.sourceToggles[src.id] = src.enabled;
            }
        } catch (e) {
            console.error('Failed to load config:', e);
            toast('Failed to load generator config', 'error');
        }
    }

    function bindEvents() {
        // Commander search
        const input = $('dg-commander-input');
        input.addEventListener('input', () => {
            clearTimeout(searchTimeout);
            const q = input.value.trim();
            if (q.length < 2) {
                hideDropdown();
                return;
            }
            searchTimeout = setTimeout(() => searchCommander(q), DEBOUNCE_MS);
        });

        input.addEventListener('focus', () => {
            const q = input.value.trim();
            if (q.length >= 2) {
                searchCommander(q);
            }
        });

        // Close dropdown on outside click
        document.addEventListener('click', (e) => {
            const wrap = document.querySelector('.dg-commander-search-wrap');
            if (wrap && !wrap.contains(e.target)) {
                hideDropdown();
            }
        });

        // Clear commander
        $('dg-commander-clear').addEventListener('click', clearCommander);

        // Preview button
        $('dg-preview-btn').addEventListener('click', generatePreview);

        // Save button
        $('dg-save-btn').addEventListener('click', commitDeck);

        // Regenerate button
        $('dg-regenerate-btn').addEventListener('click', generatePreview);
    }

    function checkQueryParams() {
        const params = new URLSearchParams(window.location.search);
        const name = params.get('commander');
        const sid = params.get('scryfall_id');

        if (sid || name) {
            // Pre-fill commander from query params
            const input = $('dg-commander-input');
            if (name) input.value = name;

            // If we have a scryfall_id, resolve directly
            if (sid) {
                fetch(API_BASE + '/api/deck-generator/commander-search?q=' + encodeURIComponent(name || 'a'))
                    .then(r => r.json())
                    .then(data => {
                        const match = data.results.find(r => r.scryfall_id === sid);
                        if (match) selectCommander(match);
                    })
                    .catch(() => {});
            } else if (name) {
                searchCommander(name);
            }
        }
    }

    // ── Commander Search ────────────────────────────────────
    function positionDropdown() {
        const input = $('dg-commander-input');
        const dropdown = $('dg-commander-dropdown');
        const rect = input.getBoundingClientRect();
        dropdown.style.top = (rect.bottom + 4) + 'px';
        dropdown.style.left = rect.left + 'px';
        dropdown.style.width = rect.width + 'px';
    }

    async function searchCommander(q) {
        const dropdown = $('dg-commander-dropdown');
        dropdown.innerHTML = '<div class="dg-dropdown-loading">Searching...</div>';
        dropdown.classList.add('open');
        positionDropdown();

        try {
            const resp = await fetch(API_BASE + '/api/deck-generator/commander-search?q=' + encodeURIComponent(q));
            const data = await resp.json();
            renderDropdown(data.results || []);
        } catch (e) {
            dropdown.innerHTML = '<div class="dg-dropdown-empty">Search failed</div>';
        }
    }

    function renderDropdown(results) {
        const dropdown = $('dg-commander-dropdown');

        if (results.length === 0) {
            dropdown.innerHTML = '<div class="dg-dropdown-empty">No legendary creatures found</div>';
            return;
        }

        dropdown.innerHTML = results.map(r => {
            const colors = (r.color_identity || [])
                .map(c => {
                    const info = COLOR_MAP[c];
                    return info ? '<span class="dg-color-pip ' + info.cls + '">' + info.label + '</span>' : '';
                })
                .join('');

            const badge = r.in_collection
                ? '<span class="dg-dropdown-item-badge dg-badge-owned">Owned</span>'
                : '<span class="dg-dropdown-item-badge dg-badge-scryfall">Scryfall</span>';

            const imgSrc = r.image_url
                ? r.image_url.replace('version=normal', 'version=small')
                : '';
            const imgTag = imgSrc
                ? '<img class="dg-dropdown-item-img" src="' + imgSrc + '" alt="" loading="lazy" />'
                : '<div class="dg-dropdown-item-img" style="background:var(--lab-surface)"></div>';

            return '<div class="dg-dropdown-item" data-idx="' + results.indexOf(r) + '">'
                + imgTag
                + '<div class="dg-dropdown-item-info">'
                + '  <div class="dg-dropdown-item-name">' + escHtml(r.name) + '</div>'
                + '  <div class="dg-dropdown-item-type">' + escHtml(r.type_line || '') + '</div>'
                + '</div>'
                + '<div style="display:flex;gap:3px;align-items:center">' + colors + '</div>'
                + badge
                + '</div>';
        }).join('');

        // Bind click handlers
        dropdown.querySelectorAll('.dg-dropdown-item').forEach(el => {
            el.addEventListener('click', () => {
                const idx = parseInt(el.dataset.idx, 10);
                selectCommander(results[idx]);
                hideDropdown();
            });
        });
    }

    function selectCommander(cmdr) {
        state.commander = cmdr;

        // Update UI
        $('dg-commander-input').style.display = 'none';
        const sel = $('dg-commander-selected');
        sel.style.display = 'block';

        $('dg-commander-name').textContent = cmdr.name;
        $('dg-commander-type').textContent = cmdr.type_line || '';

        const colorsEl = $('dg-commander-colors');
        colorsEl.innerHTML = (cmdr.color_identity || [])
            .map(c => {
                const info = COLOR_MAP[c];
                return info ? '<span class="dg-color-pip ' + info.cls + '">' + info.label + '</span>' : '';
            })
            .join('');

        const img = $('dg-commander-img');
        if (cmdr.image_url) {
            img.src = cmdr.image_url.replace('version=normal', 'version=small');
            img.style.display = 'block';
        } else {
            img.style.display = 'none';
        }

        // Enable preview button
        $('dg-preview-btn').disabled = false;
    }

    function clearCommander() {
        state.commander = null;
        $('dg-commander-input').style.display = '';
        $('dg-commander-input').value = '';
        $('dg-commander-selected').style.display = 'none';
        $('dg-preview-btn').disabled = true;
    }

    function hideDropdown() {
        $('dg-commander-dropdown').classList.remove('open');
    }

    // ── Source Toggles ──────────────────────────────────────
    function renderSourceToggles(sources) {
        const container = $('dg-source-toggles');
        container.innerHTML = sources.map(src => {
            const checked = src.enabled ? 'checked' : '';
            const exp = src.experimental
                ? '<span class="dg-source-exp">Beta</span>'
                : '';
            return '<label class="dg-toggle-row">'
                + '<span class="dg-source-label">' + escHtml(src.name) + ' ' + exp + '</span>'
                + '<input type="checkbox" class="dg-toggle-check" data-source="' + src.id + '" ' + checked + ' />'
                + '<span class="dg-toggle-track"><span class="dg-toggle-thumb"></span></span>'
                + '</label>';
        }).join('');

        // Bind change events
        container.querySelectorAll('.dg-toggle-check').forEach(cb => {
            cb.addEventListener('change', () => {
                state.sourceToggles[cb.dataset.source] = cb.checked;
            });
        });
    }

    // ── Ratio Sliders ───────────────────────────────────────
    function renderRatioSliders(defaults) {
        const container = $('dg-ratio-list');
        const types = [
            { key: 'target_land_count', label: 'Lands', max: 50 },
            { key: 'target_creature_count', label: 'Creatures', max: 50 },
            { key: 'target_instant_count', label: 'Instants', max: 25 },
            { key: 'target_sorcery_count', label: 'Sorceries', max: 25 },
            { key: 'target_artifact_count', label: 'Artifacts', max: 25 },
            { key: 'target_enchantment_count', label: 'Enchantments', max: 25 },
            { key: 'target_planeswalker_count', label: 'Planeswalkers', max: 10 },
        ];

        container.innerHTML = types.map(t => {
            const val = defaults[t.key] || 0;
            return '<div class="dg-ratio-row">'
                + '<span class="dg-ratio-label">' + t.label + '</span>'
                + '<input type="range" class="dg-ratio-slider" data-key="' + t.key + '" min="0" max="' + t.max + '" value="' + val + '" />'
                + '<input type="number" class="dg-ratio-value" data-key="' + t.key + '" min="0" max="' + t.max + '" value="' + val + '" />'
                + '</div>';
        }).join('');

        // Sync slider <-> input
        container.querySelectorAll('.dg-ratio-slider').forEach(slider => {
            const key = slider.dataset.key;
            const numInput = container.querySelector('.dg-ratio-value[data-key="' + key + '"]');

            slider.addEventListener('input', () => {
                numInput.value = slider.value;
                state.ratios[key] = parseInt(slider.value, 10);
                updateTotalHint();
            });

            numInput.addEventListener('input', () => {
                slider.value = numInput.value;
                state.ratios[key] = parseInt(numInput.value, 10) || 0;
                updateTotalHint();
            });
        });

        updateTotalHint();
    }

    function updateTotalHint() {
        const total = Object.keys(state.ratios)
            .filter(k => k.startsWith('target_'))
            .reduce((sum, k) => sum + (parseInt(state.ratios[k], 10) || 0), 0);

        const hint = $('dg-total-hint');
        // +1 for commander
        const withCmdr = total + 1;
        hint.textContent = withCmdr + ' / 100';

        if (withCmdr > 100) {
            hint.classList.add('dg-over');
        } else {
            hint.classList.remove('dg-over');
        }
    }

    // ── Preview Generation ──────────────────────────────────
    async function generatePreview() {
        if (!state.commander) {
            toast('Select a commander first', 'error');
            return;
        }

        setLoading(true);

        const body = {
            commander_name: state.commander.name,
            commander_scryfall_id: state.commander.scryfall_id || '',
            color_identity: state.commander.color_identity || [],
            sources: {
                use_archidekt: !!state.sourceToggles.archidekt,
                use_edhrec: !!state.sourceToggles.edhrec,
                use_moxfield: !!state.sourceToggles.moxfield,
                use_mtggoldfish: !!state.sourceToggles.mtggoldfish,
            },
            only_cards_in_collection: !!$('dg-only-owned').checked,
            allow_proxies: !!$('dg-allow-proxies').checked,
            deck_name: $('dg-deck-name').value.trim() || '',
        };

        // Add ratio targets
        for (const [key, val] of Object.entries(state.ratios)) {
            if (key.startsWith('target_')) {
                body[key] = parseInt(val, 10) || 0;
            }
        }

        try {
            const resp = await fetch(API_BASE + '/api/deck-generator/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || 'Preview generation failed');
            }

            state.previewResult = await resp.json();
            renderResults(state.previewResult);
            toast('Deck generated: ' + (state.previewResult.stats?.total || 0) + ' cards', 'success');
        } catch (e) {
            toast(e.message || 'Preview failed', 'error');
            setLoading(false);
        }
    }

    function setLoading(loading) {
        state.isLoading = loading;
        $('dg-empty-state').style.display = 'none';
        $('dg-loading').style.display = loading ? 'flex' : 'none';
        $('dg-results').style.display = loading ? 'none' : 'none';
        $('dg-preview-btn').disabled = loading || !state.commander;
    }

    // ── Render Results ──────────────────────────────────────
    function renderResults(result) {
        $('dg-loading').style.display = 'none';
        $('dg-results').style.display = 'block';
        $('dg-preview-btn').disabled = false;

        renderStatsBar(result);
        renderCardGroups(result);
    }

    function renderStatsBar(result) {
        const stats = result.stats || {};
        const container = $('dg-stats-bar');

        container.innerHTML = [
            chipHtml('Total', stats.total || 0, ''),
            chipHtml('Owned', stats.owned || 0, 'dg-stat-owned'),
            chipHtml('Proxy', stats.proxy || 0, 'dg-stat-proxy'),
            chipHtml('Lands', stats.land || 0, ''),
            chipHtml('Nonland', stats.nonland || 0, ''),
        ].join('');
    }

    function chipHtml(label, num, cls) {
        return '<div class="dg-stat-chip ' + cls + '">'
            + '<span class="dg-stat-num">' + num + '</span>'
            + '<span class="dg-stat-label">' + label + '</span>'
            + '</div>';
    }

    function renderCardGroups(result) {
        const container = $('dg-card-groups');
        const cards = result.cards || [];
        const commander = result.commander;

        // Group cards by card_type
        const groups = {};
        for (const card of cards) {
            const ct = card.card_type || 'Other';
            if (!groups[ct]) groups[ct] = [];
            groups[ct].push(card);
        }

        // Sort groups by TYPE_ORDER
        const sortedTypes = TYPE_ORDER.filter(t => groups[t] && groups[t].length > 0);
        // Add any types not in TYPE_ORDER
        for (const t of Object.keys(groups)) {
            if (!sortedTypes.includes(t)) sortedTypes.push(t);
        }

        let html = '';

        // Commander section
        if (commander) {
            html += '<div class="dg-card-group">'
                + '<div class="dg-group-header">'
                + '<span class="dg-group-title">⚔ Commander</span>'
                + '<span class="dg-group-count">1</span>'
                + '</div>'
                + '<div class="dg-group-body">'
                + '<div class="dg-card-row">'
                + '<span class="dg-card-row-mana">' + escHtml(commander.mana_cost || '') + '</span>'
                + '<span class="dg-card-row-name" style="font-weight:600;color:#fff">' + escHtml(commander.name) + '</span>'
                + '<span class="dg-card-row-source dg-src-collection">Commander</span>'
                + '</div>'
                + '</div>'
                + '</div>';
        }

        // Card type groups
        for (const type of sortedTypes) {
            const groupCards = groups[type];
            if (!groupCards || groupCards.length === 0) continue;

            // Sort cards by score (name as fallback)
            groupCards.sort((a, b) => (a.name || '').localeCompare(b.name || ''));

            const icon = TYPE_ICONS[type] || '🃏';
            const target = result.targets?.[type];
            const countLabel = target !== undefined
                ? groupCards.length + ' / ' + target
                : String(groupCards.length);

            html += '<div class="dg-card-group">'
                + '<div class="dg-group-header" data-type="' + type + '">'
                + '<span class="dg-group-title">' + icon + ' ' + escHtml(type) + '</span>'
                + '<span class="dg-group-count">' + countLabel + '</span>'
                + '</div>'
                + '<div class="dg-group-body" data-group="' + type + '">';

            for (const card of groupCards) {
                html += renderCardRow(card);
            }

            html += '</div></div>';
        }

        container.innerHTML = html;

        // Bind collapse toggles
        container.querySelectorAll('.dg-group-header').forEach(header => {
            header.addEventListener('click', () => {
                const type = header.dataset.type;
                if (!type) return;
                const body = container.querySelector('.dg-group-body[data-group="' + type + '"]');
                if (body) body.classList.toggle('collapsed');
            });
        });

        // Bind card hover previews
        container.querySelectorAll('.dg-card-row[data-img]').forEach(row => {
            row.addEventListener('mouseenter', showCardPreview);
            row.addEventListener('mousemove', moveCardPreview);
            row.addEventListener('mouseleave', hideCardPreview);
        });
    }

    function renderCardRow(card) {
        const sourceCls = getSourceClass(card.source || '');
        const sourceLabel = getSourceLabel(card.source || '');

        const ownedHtml = card.owned_qty > 0
            ? '<span class="dg-card-row-owned is-owned">x' + card.owned_qty + '</span>'
            : (card.is_proxy
                ? '<span class="dg-card-row-owned is-proxy">Proxy</span>'
                : '<span class="dg-card-row-owned">-</span>');

        const rolesHtml = (card.roles || []).slice(0, 3)
            .map(r => '<span class="dg-role-chip">' + escHtml(r) + '</span>')
            .join('');

        const imgUrl = card.image_url || '';

        return '<div class="dg-card-row" data-img="' + escAttr(imgUrl) + '">'
            + '<span class="dg-card-row-mana">' + formatMana(card.mana_cost || '') + '</span>'
            + '<span class="dg-card-row-name">' + escHtml(card.name) + '</span>'
            + '<span class="dg-card-row-roles">' + rolesHtml + '</span>'
            + '<span class="dg-card-row-source ' + sourceCls + '">' + sourceLabel + '</span>'
            + ownedHtml
            + '</div>';
    }

    function getSourceClass(source) {
        const s = source.toLowerCase();
        if (s.includes('collection')) return 'dg-src-collection';
        if (s.includes('edhrec')) return 'dg-src-edhrec';
        if (s.includes('archidekt')) return 'dg-src-archidekt';
        if (s.includes('moxfield')) return 'dg-src-moxfield';
        if (s.includes('mtggoldfish')) return 'dg-src-mtggoldfish';
        if (s.includes('template')) return 'dg-src-template';
        return 'dg-src-collection';
    }

    function getSourceLabel(source) {
        const s = source.toLowerCase();
        if (s.includes('collection') && s.includes('+')) {
            const parts = source.split('+');
            return parts[parts.length - 1];
        }
        if (s === 'collection') return 'Owned';
        if (s.includes('edhrec')) return 'EDHREC';
        if (s.includes('archidekt')) return 'Archidekt';
        if (s.includes('moxfield')) return 'Moxfield';
        if (s.includes('mtggoldfish')) return 'Goldfish';
        if (s.includes('template')) return 'Template';
        return source || 'Owned';
    }

    // ── Card Preview ────────────────────────────────────────
    let previewEl = null;

    function ensurePreviewEl() {
        if (!previewEl) {
            previewEl = document.createElement('div');
            previewEl.className = 'dg-card-preview';
            previewEl.innerHTML = '<img src="" alt="" />';
            document.body.appendChild(previewEl);
        }
        return previewEl;
    }

    function showCardPreview(e) {
        const imgUrl = e.currentTarget.dataset.img;
        if (!imgUrl) return;
        const el = ensurePreviewEl();
        el.querySelector('img').src = imgUrl;
        el.classList.add('visible');
        positionPreview(e);
    }

    function moveCardPreview(e) {
        positionPreview(e);
    }

    function hideCardPreview() {
        if (previewEl) previewEl.classList.remove('visible');
    }

    function positionPreview(e) {
        if (!previewEl) return;
        const x = e.clientX + 16;
        const y = e.clientY - 80;
        previewEl.style.left = Math.min(x, window.innerWidth - 260) + 'px';
        previewEl.style.top = Math.max(8, Math.min(y, window.innerHeight - 360)) + 'px';
    }

    // ── Commit Deck ─────────────────────────────────────────
    async function commitDeck() {
        if (!state.commander) {
            toast('No commander selected', 'error');
            return;
        }

        $('dg-save-btn').disabled = true;
        $('dg-save-btn').textContent = 'Saving...';

        const body = {
            commander_name: state.commander.name,
            commander_scryfall_id: state.commander.scryfall_id || '',
            color_identity: state.commander.color_identity || [],
            sources: {
                use_archidekt: !!state.sourceToggles.archidekt,
                use_edhrec: !!state.sourceToggles.edhrec,
                use_moxfield: !!state.sourceToggles.moxfield,
                use_mtggoldfish: !!state.sourceToggles.mtggoldfish,
            },
            only_cards_in_collection: !!$('dg-only-owned').checked,
            allow_proxies: !!$('dg-allow-proxies').checked,
            deck_name: $('dg-deck-name').value.trim() || '',
        };

        for (const [key, val] of Object.entries(state.ratios)) {
            if (key.startsWith('target_')) {
                body[key] = parseInt(val, 10) || 0;
            }
        }

        try {
            const resp = await fetch(API_BASE + '/api/deck-generator/commit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || 'Save failed');
            }

            const result = await resp.json();
            toast('Deck saved: ' + (result.deck_name || 'Unknown'), 'success');

            // Navigate to deck builder with the new deck
            setTimeout(() => {
                window.location.href = 'deckbuilder.html?deck_id=' + result.deck_id;
            }, 1200);
        } catch (e) {
            toast(e.message || 'Save failed', 'error');
        } finally {
            $('dg-save-btn').disabled = false;
            $('dg-save-btn').innerHTML = '<span class="dg-btn-icon">💾</span> Save to Deck Builder';
        }
    }

    // ── Toast ───────────────────────────────────────────────
    function toast(msg, type) {
        type = type || 'info';
        const container = $('dg-toast-container');
        const el = document.createElement('div');
        el.className = 'dg-toast dg-toast-' + type;
        el.textContent = msg;
        container.appendChild(el);
        setTimeout(() => el.remove(), 3000);
    }

    // ── Helpers ─────────────────────────────────────────────
    function escHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function escAttr(str) {
        return str.replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function formatMana(cost) {
        if (!cost) return '';
        // Simple mana cost formatting — keep symbols readable
        return escHtml(cost.replace(/[{}]/g, ''));
    }

    // ── Public API ──────────────────────────────────────────
    return { init };
})();

document.addEventListener('DOMContentLoaded', () => {
    DeckGenerator.init();
});
