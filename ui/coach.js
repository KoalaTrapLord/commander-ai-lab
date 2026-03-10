/**
 * Commander AI Lab — Deck Coach UI
 * ═════════════════════════════════
 * Connects to the Python coach API endpoints to provide
 * LLM-powered deck coaching with suggested cuts/adds.
 */

(function () {
    'use strict';

    const API = window.location.origin;

    // ── DOM References ──────────────────────────────────────────

    const deckSelect = document.getElementById('coach-deck-select');
    const powerSlider = document.getElementById('coach-power-level');
    const powerValue = document.getElementById('coach-power-value');
    const metaFocus = document.getElementById('coach-meta-focus');
    const budgetSelect = document.getElementById('coach-budget');
    const runBtn = document.getElementById('coach-run-btn');
    const runHint = document.getElementById('coach-run-hint');
    const progressEl = document.getElementById('coach-progress');
    const progressText = document.getElementById('coach-progress-text');
    const resultsEl = document.getElementById('coach-results');

    // Status
    const statusLlmDot = document.querySelector('#status-llm .status-dot');
    const statusLlmValue = document.getElementById('status-llm-value');
    const statusEmbDot = document.querySelector('#status-embeddings .status-dot');
    const statusEmbValue = document.getElementById('status-embeddings-value');
    const statusRepDot = document.querySelector('#status-reports .status-dot');
    const statusRepValue = document.getElementById('status-reports-value');

    // Results
    const summaryText = document.getElementById('coach-summary-text');
    const metaRow = document.getElementById('coach-meta-row');
    const cutsCount = document.getElementById('coach-cuts-count');
    const cutsBody = document.getElementById('coach-cuts-body');
    const cutsAllCheck = document.getElementById('coach-cuts-all');
    const addsCount = document.getElementById('coach-adds-count');
    const addsBody = document.getElementById('coach-adds-body');
    const addsAllCheck = document.getElementById('coach-adds-all');
    const hintsCard = document.getElementById('coach-hints-card');
    const hintsList = document.getElementById('coach-hints-list');
    const manaCard = document.getElementById('coach-mana-card');
    const manaText = document.getElementById('coach-mana-text');
    const rawText = document.getElementById('coach-raw-text');
    const sessionsList = document.getElementById('coach-sessions-list');
    const genReportsBtn = document.getElementById('generate-reports-btn');

    // ── Init ────────────────────────────────────────────────────

    init();

    async function init() {
        // Power slider
        powerSlider.addEventListener('input', () => {
            powerValue.textContent = powerSlider.value;
        });

        // Deck select enables run button
        deckSelect.addEventListener('change', () => {
            const hasDeck = deckSelect.value !== '';
            runBtn.disabled = !hasDeck;
            runHint.textContent = hasDeck ? 'Ready to analyze' : 'Select a deck to begin';
        });

        // Run button
        runBtn.addEventListener('click', runCoach);

        // Generate reports button
        genReportsBtn.addEventListener('click', generateReports);

        // Select-all checkboxes
        cutsAllCheck.addEventListener('change', () => {
            cutsBody.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.checked = cutsAllCheck.checked;
            });
        });
        addsAllCheck.addEventListener('change', () => {
            addsBody.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.checked = addsAllCheck.checked;
            });
        });

        // Load data
        await Promise.all([
            checkStatus(),
            loadDecks(),
            loadSessions(),
        ]);
    }

    // ── Status Check ────────────────────────────────────────────

    async function checkStatus() {
        try {
            const res = await fetch(API + '/api/coach/status');
            const data = await res.json();

            // LLM
            if (data.llmConnected) {
                setStatus(statusLlmDot, statusLlmValue, 'ok',
                    data.llmModel || 'Connected');
            } else {
                setStatus(statusLlmDot, statusLlmValue, 'error',
                    data.error || 'Not connected');
            }

            // Embeddings
            if (data.embeddingsLoaded) {
                setStatus(statusEmbDot, statusEmbValue, 'ok',
                    data.embeddingCards.toLocaleString() + ' cards');
            } else {
                setStatus(statusEmbDot, statusEmbValue, 'warn',
                    'Not loaded');
            }

            // Reports
            if (data.deckReportsAvailable > 0) {
                setStatus(statusRepDot, statusRepValue, 'ok',
                    data.deckReportsAvailable + ' available');
                genReportsBtn.style.display = 'inline-block';
                genReportsBtn.textContent = 'Rebuild Reports';
            } else {
                setStatus(statusRepDot, statusRepValue, 'warn',
                    'None \u2014 run simulations first');
                genReportsBtn.style.display = 'inline-block';
                genReportsBtn.textContent = 'Generate Reports';
            }
        } catch (e) {
            setStatus(statusLlmDot, statusLlmValue, 'error', 'Service unavailable');
            setStatus(statusEmbDot, statusEmbValue, 'error', '—');
            setStatus(statusRepDot, statusRepValue, 'error', '—');
        }
    }

    function setStatus(dotEl, valueEl, level, text) {
        dotEl.className = 'status-dot status-' + level;
        valueEl.textContent = text;
    }

    // ── Load Decks ──────────────────────────────────────────────

    async function loadDecks() {
        try {
            const res = await fetch(API + '/api/coach/decks');
            const data = await res.json();
            const decks = data.decks || [];

            // Clear existing options (keep placeholder)
            while (deckSelect.options.length > 1) {
                deckSelect.remove(1);
            }

            if (decks.length === 0) {
                const opt = document.createElement('option');
                opt.disabled = true;
                opt.textContent = 'No deck reports available — run simulations first';
                deckSelect.appendChild(opt);
                return;
            }

            decks.sort();
            for (const deckId of decks) {
                const opt = document.createElement('option');
                opt.value = deckId;
                opt.textContent = deckId;
                deckSelect.appendChild(opt);
            }
        } catch (e) {
            console.error('Failed to load decks:', e);
        }
    }

    // ── Load Past Sessions ──────────────────────────────────────

    async function loadSessions() {
        try {
            const res = await fetch(API + '/api/coach/sessions');
            const data = await res.json();
            const sessions = data.sessions || [];

            if (sessions.length === 0) {
                sessionsList.innerHTML = '<p class="coach-empty">No coaching sessions yet. Run the coach to get started.</p>';
                return;
            }

            sessionsList.innerHTML = '';
            for (const s of sessions) {
                const item = document.createElement('div');
                item.className = 'coach-session-item';
                item.onclick = () => loadSession(s.sessionId);

                const timeStr = s.timestamp ? formatTime(s.timestamp) : '';

                item.innerHTML =
                    '<span class="coach-session-deck">' + escHtml(s.deckId) + '</span>' +
                    '<span class="coach-session-summary">' + escHtml(s.summary || '(no summary)') + '</span>' +
                    '<span class="coach-session-meta">' +
                        '<span class="coach-session-cuts">-' + (s.cutsCount || 0) + '</span>' +
                        '<span class="coach-session-adds">+' + (s.addsCount || 0) + '</span>' +
                        '<span class="coach-session-time">' + escHtml(timeStr) + '</span>' +
                    '</span>';

                sessionsList.appendChild(item);
            }
        } catch (e) {
            console.error('Failed to load sessions:', e);
        }
    }

    // ── Generate Reports ─────────────────────────────────────────

    async function generateReports() {
        genReportsBtn.disabled = true;
        genReportsBtn.textContent = 'Generating...';

        try {
            const res = await fetch(API + '/api/coach/reports/generate', {
                method: 'POST',
            });
            const data = await res.json();

            if (data.count > 0) {
                genReportsBtn.textContent = data.count + ' reports generated';
                // Refresh status and deck list
                await checkStatus();
                await loadDecks();
            } else {
                genReportsBtn.textContent = 'No results found';
            }
        } catch (e) {
            genReportsBtn.textContent = 'Error: ' + e.message;
        } finally {
            setTimeout(() => {
                genReportsBtn.disabled = false;
                genReportsBtn.textContent = 'Rebuild Reports';
            }, 3000);
        }
    }

    // ── Run Coach ───────────────────────────────────────────────

    async function runCoach() {
        const deckId = deckSelect.value;
        if (!deckId) return;

        // Gather goals
        const focusAreas = [];
        document.querySelectorAll('.coach-focus-tags input[type="checkbox"]:checked').forEach(cb => {
            focusAreas.push(cb.value);
        });

        const goals = {};
        const pl = parseInt(powerSlider.value);
        if (pl) goals.targetPowerLevel = pl;
        if (metaFocus.value) goals.metaFocus = metaFocus.value;
        if (budgetSelect.value) goals.budget = budgetSelect.value;
        if (focusAreas.length > 0) goals.focusAreas = focusAreas;

        // Show progress
        runBtn.disabled = true;
        progressEl.style.display = 'flex';
        progressText.textContent = 'Analyzing deck and consulting LLM... This may take 30-60 seconds.';
        resultsEl.style.display = 'none';

        // Remove any previous error
        const prevError = document.querySelector('.coach-error');
        if (prevError) prevError.remove();

        try {
            const res = await fetch(API + '/api/coach/decks/' + encodeURIComponent(deckId), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ goals: goals }),
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(err.detail || 'Coach request failed (' + res.status + ')');
            }

            const session = await res.json();
            displaySession(session);

            // Refresh sessions list
            loadSessions();

        } catch (e) {
            const errDiv = document.createElement('div');
            errDiv.className = 'coach-error';
            errDiv.textContent = 'Coach error: ' + e.message;
            document.querySelector('.coach-config').appendChild(errDiv);
        } finally {
            runBtn.disabled = false;
            progressEl.style.display = 'none';
        }
    }

    // ── Load & Display Session ──────────────────────────────────

    async function loadSession(sessionId) {
        try {
            const res = await fetch(API + '/api/coach/sessions/' + encodeURIComponent(sessionId));
            if (!res.ok) throw new Error('Session not found');
            const session = await res.json();
            displaySession(session);

            // Scroll to results
            resultsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch (e) {
            console.error('Failed to load session:', e);
        }
    }

    function displaySession(session) {
        resultsEl.style.display = 'flex';

        // Summary
        summaryText.textContent = session.summary || '(No summary provided)';

        // Meta chips
        metaRow.innerHTML = '';
        if (session.modelUsed) {
            addMetaChip('Model', session.modelUsed);
        }
        if (session.promptTokens) {
            addMetaChip('Prompt', session.promptTokens.toLocaleString() + ' tokens');
        }
        if (session.completionTokens) {
            addMetaChip('Completion', session.completionTokens.toLocaleString() + ' tokens');
        }
        if (session.deckId) {
            addMetaChip('Deck', session.deckId);
        }
        if (session.timestamp) {
            addMetaChip('Time', formatTime(session.timestamp));
        }

        // Cuts table
        const cuts = session.suggestedCuts || [];
        cutsCount.textContent = cuts.length;
        cutsBody.innerHTML = '';
        cutsAllCheck.checked = false;

        for (const cut of cuts) {
            const tr = document.createElement('tr');
            tr.innerHTML =
                '<td><input type="checkbox" /></td>' +
                '<td><span class="coach-card-name">' + escHtml(cut.cardName) + '</span></td>' +
                '<td>' + escHtml(cut.reason) + '</td>' +
                '<td><div class="coach-replacements">' +
                    (cut.replacementOptions || []).map(r =>
                        '<span class="coach-replacement-chip">' + escHtml(r) + '</span>'
                    ).join('') +
                '</div></td>' +
                '<td>' + formatImpact(cut.currentImpactScore) + '</td>';
            cutsBody.appendChild(tr);
        }

        // Adds table
        const adds = session.suggestedAdds || [];
        addsCount.textContent = adds.length;
        addsBody.innerHTML = '';
        addsAllCheck.checked = false;

        for (const add of adds) {
            const tr = document.createElement('tr');
            tr.innerHTML =
                '<td><input type="checkbox" /></td>' +
                '<td><span class="coach-card-name">' + escHtml(add.cardName) + '</span></td>' +
                '<td>' + (add.role ? '<span class="coach-role-badge">' + escHtml(add.role) + '</span>' : '') + '</td>' +
                '<td>' + escHtml(add.reason) + '</td>' +
                '<td><div class="coach-replacements">' +
                    (add.synergyWith || []).map(s =>
                        '<span class="coach-synergy-chip">' + escHtml(s) + '</span>'
                    ).join('') +
                '</div></td>';
            addsBody.appendChild(tr);
        }

        // Hints
        const hints = session.heuristicHints || [];
        if (hints.length > 0) {
            hintsCard.style.display = 'block';
            hintsList.innerHTML = '';
            for (const hint of hints) {
                const li = document.createElement('li');
                li.textContent = hint;
                hintsList.appendChild(li);
            }
        } else {
            hintsCard.style.display = 'none';
        }

        // Mana advice
        if (session.manaBaseAdvice) {
            manaCard.style.display = 'block';
            manaText.textContent = session.manaBaseAdvice;
        } else {
            manaCard.style.display = 'none';
        }

        // Raw text
        rawText.textContent = session.rawTextExplanation || session.summary || '(empty)';
    }

    // ── Helpers ─────────────────────────────────────────────────

    function addMetaChip(label, value) {
        const chip = document.createElement('span');
        chip.className = 'coach-meta-chip';
        chip.innerHTML = '<strong>' + escHtml(label) + ':</strong> ' + escHtml(value);
        metaRow.appendChild(chip);
    }

    function formatImpact(score) {
        if (score === undefined || score === null) {
            return '<span class="coach-impact coach-impact-neutral">—</span>';
        }
        const fixed = score.toFixed(3);
        if (score < -0.01) {
            return '<span class="coach-impact coach-impact-negative">' + fixed + '</span>';
        } else if (score > 0.01) {
            return '<span class="coach-impact coach-impact-positive">+' + fixed + '</span>';
        } else {
            return '<span class="coach-impact coach-impact-neutral">' + fixed + '</span>';
        }
    }

    function formatTime(isoStr) {
        try {
            const d = new Date(isoStr);
            return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch {
            return isoStr;
        }
    }

    function escHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

})();
