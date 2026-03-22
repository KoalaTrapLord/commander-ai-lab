/**
 * Commander AI Lab — Distillation Loop Dashboard
 * Manages distillation pipeline controls, status polling, and chart rendering.
 */

const API_BASE = '';  // Same origin

// ═══════════════════════════════════════════
// State
// ═══════════════════════════════════════════

let pollingInterval = null;
let isRunning = false;
let generationsData = [];

// ═══════════════════════════════════════════
// Init
// ═══════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    refreshAll();
});

async function refreshAll() {
    const btn = document.getElementById('btn-refresh');
    const icon = document.getElementById('refresh-icon');
    btn.disabled = true;
    icon.style.display = 'inline-block';
    icon.style.animation = 'spin 0.8s linear infinite';
    try {
        await refreshStatus();
        await loadHistory();
    } finally {
        btn.disabled = false;
        icon.style.animation = '';
    }
}

// ═══════════════════════════════════════════
// Status Polling
// ═══════════════════════════════════════════

async function refreshStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/ml/distill/status`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        updateUI(data);

        if (data.running && !pollingInterval) {
            startPolling();
        }
    } catch (err) {
        console.error('Failed to fetch distillation status:', err);
    }
}

function startPolling() {
    if (pollingInterval) clearInterval(pollingInterval);
    pollingInterval = setInterval(pollStatus, 3000);
}

function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

async function pollStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/ml/distill/status`);
        const data = await res.json();
        updateUI(data);

        if (!data.running && data.phase !== 'idle') {
            stopPolling();
            isRunning = false;
            updateButtons(false);
            // Refresh history when done
            loadHistory();
        }
    } catch (err) {
        console.error('Poll failed:', err);
    }
}

// ═══════════════════════════════════════════
// UI Updates
// ═══════════════════════════════════════════

function updateUI(data) {
    // Status card
    const statusVal = document.getElementById('val-status');
    const statusSub = document.getElementById('sub-status');
    const statusCard = document.getElementById('card-status');
    const phase = data.phase || 'idle';

    statusCard.className = 'status-card stat-card';
    if (phase === 'running' || phase === 'starting') {
        statusVal.textContent = 'Running';
        statusSub.textContent = data.current_step || 'in progress';
        statusCard.classList.add('active');
    } else if (phase === 'done') {
        statusVal.textContent = 'Complete';
        statusSub.textContent = 'finished';
        statusCard.classList.add('success');
    } else if (phase === 'error') {
        statusVal.textContent = 'Error';
        statusSub.textContent = data.error ? data.error.substring(0, 40) : 'failed';
        statusCard.classList.add('error-state');
    } else {
        statusVal.textContent = 'Idle';
        statusSub.textContent = 'not running';
    }

    // Generation card
    document.getElementById('val-generation').textContent =
        data.generation > 0 ? data.generation : '--';
    document.getElementById('sub-generation').textContent =
        data.max_iterations > 0 ? `of ${data.max_iterations}` : 'of --';

    if (data.generation > 0) {
        document.getElementById('card-generation').classList.add('active');
    }

    // Win rate and passed cards from generations data
    const gens = data.generations || [];
    if (gens.length > 0) {
        const bestWR = Math.max(...gens.map(g => g.ppo_best_win_rate || 0));
        document.getElementById('val-winrate').textContent =
            bestWR > 0 ? (bestWR * 100).toFixed(1) + '%' : '--';
        if (bestWR > 0) {
            document.getElementById('card-winrate').classList.add('active');
        }

        const passed = gens.filter(g => g.status === 'passed').length;
        document.getElementById('val-passed').textContent = passed;
        document.getElementById('sub-passed').textContent =
            `of ${gens.length} generations`;
        if (passed > 0) {
            document.getElementById('card-passed').classList.add('success');
        }

        generationsData = gens;
        renderWinRateChart(gens);
        renderCompositionChart(gens);
        renderHistoryTable(gens);
    }

    // Progress section
    const progressEl = document.getElementById('distill-progress');
    if (phase !== 'idle') {
        progressEl.classList.remove('hidden');
        updateProgress(data);
    }

    // Button states
    updateButtons(data.running);
    isRunning = data.running;
}

function updateProgress(data) {
    const phaseBadge = document.getElementById('progress-phase');
    const message = document.getElementById('progress-message');
    const bar = document.getElementById('progress-bar');
    const detail = document.getElementById('progress-detail');

    const phase = data.phase || 'idle';
    phaseBadge.textContent = phase.toUpperCase();
    phaseBadge.className = 'phase-badge ' + phase;

    message.textContent = data.message || '';

    bar.className = 'progress-bar progress-fill';
    if (phase === 'done') {
        bar.style.width = '100%';
        bar.classList.add('done');
    } else if (phase === 'error') {
        bar.style.width = '100%';
        bar.classList.add('error');
    } else if (data.max_iterations > 0 && data.generation > 0) {
        const pct = Math.min(100, (data.generation / data.max_iterations) * 100);
        bar.style.width = pct + '%';
    } else if (phase === 'starting') {
        bar.style.width = '3%';
    }

    if (phase === 'running' && data.generation > 0) {
        detail.textContent = `Generation ${data.generation} / ${data.max_iterations}`;
    } else if (phase === 'done' && data.result) {
        const r = data.result;
        detail.textContent = `${r.generations_run} generations | Best WR: ${(r.best_win_rate * 100).toFixed(1)}% | ${r.converged ? 'Converged' : 'Max reached'} | ${r.total_time_s}s`;
    } else if (phase === 'error') {
        detail.textContent = data.error || 'Unknown error';
        detail.style.color = 'var(--lab-error, var(--error))';
    } else {
        detail.textContent = '';
        detail.style.color = '';
    }
}

function updateButtons(running) {
    const startBtn = document.getElementById('btn-start');
    const stopBtn = document.getElementById('btn-stop');

    if (running) {
        startBtn.disabled = true;
        startBtn.innerHTML = '<span class="btn-icon">&#8987;</span> Running...';
        stopBtn.disabled = false;
    } else {
        startBtn.disabled = false;
        startBtn.innerHTML = '<span class="btn-icon">&#9654;</span> Start Distillation';
        stopBtn.disabled = true;
    }
}

// ═══════════════════════════════════════════
// Controls
// ═══════════════════════════════════════════

async function startDistillation() {
    const body = {
        maxIterations: parseInt(document.getElementById('param-iterations').value) || 10,
        convergenceWindow: parseInt(document.getElementById('param-conv-window').value) || 3,
        convergenceThreshold: 0.01,
        supervisedEpochs: parseInt(document.getElementById('param-sup-epochs').value) || 30,
        supervisedLr: parseFloat(document.getElementById('param-sup-lr').value) || 1e-3,
        ppoIterations: parseInt(document.getElementById('param-ppo-iters').value) || 50,
        ppoEpisodesPerIter: parseInt(document.getElementById('param-ppo-episodes').value) || 64,
        ppoLr: parseFloat(document.getElementById('param-ppo-lr').value) || 3e-4,
        opponent: document.getElementById('param-opponent').value,
        playstyle: document.getElementById('param-playstyle').value,
        minWinRate: parseFloat(document.getElementById('param-min-wr').value) || 0.30,
    };

    const btn = document.getElementById('btn-start');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">&#8987;</span> Starting...';

    try {
        const res = await fetch(`${API_BASE}/api/ml/distill/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        isRunning = true;
        document.getElementById('distill-progress').classList.remove('hidden');
        updateButtons(true);
        startPolling();

    } catch (err) {
        alert('Failed to start distillation: ' + err.message);
        btn.disabled = false;
        btn.innerHTML = '<span class="btn-icon">&#9654;</span> Start Distillation';
    }
}

async function stopDistillation() {
    try {
        const res = await fetch(`${API_BASE}/api/ml/distill/stop`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'stopping') {
            document.getElementById('progress-message').textContent =
                'Stop signal sent — finishing current generation...';
        }
    } catch (err) {
        alert('Failed to stop: ' + err.message);
    }
}

// ═══════════════════════════════════════════
// History Loading
// ═══════════════════════════════════════════

async function loadHistory() {
    try {
        const res = await fetch(`${API_BASE}/api/ml/distill/history`);
        if (!res.ok) return;
        const data = await res.json();

        if (data.generations && data.generations.length > 0) {
            generationsData = data.generations;
            renderWinRateChart(data.generations);
            renderCompositionChart(data.generations);
            renderHistoryTable(data.generations);

            // Update summary cards from history
            const bestWR = Math.max(...data.generations.map(g => g.ppo_best_win_rate || 0));
            if (bestWR > 0) {
                document.getElementById('val-winrate').textContent = (bestWR * 100).toFixed(1) + '%';
                document.getElementById('card-winrate').classList.add('active');
            }
            const passed = data.generations.filter(g => g.status === 'passed').length;
            if (passed > 0 || data.generations.length > 0) {
                document.getElementById('val-passed').textContent = passed;
                document.getElementById('sub-passed').textContent =
                    `of ${data.generations.length} generations`;
            }
        }
    } catch (err) {
        console.error('Failed to load history:', err);
    }
}

// ═══════════════════════════════════════════
// Chart Rendering (Canvas-based, no deps)
// ═══════════════════════════════════════════

function renderWinRateChart(generations) {
    const canvas = document.getElementById('winrate-canvas');
    const empty = document.getElementById('winrate-empty');

    if (!generations || generations.length === 0) {
        canvas.style.display = 'none';
        empty.style.display = '';
        return;
    }

    canvas.style.display = 'block';
    empty.style.display = 'none';

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    const w = rect.width;
    const h = 260;

    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const pad = { top: 30, right: 30, bottom: 40, left: 55 };
    const cw = w - pad.left - pad.right;
    const ch = h - pad.top - pad.bottom;

    const winRates = generations.map(g => (g.ppo_best_win_rate || 0) * 100);
    const maxY = Math.max(100, Math.ceil(Math.max(...winRates) / 10) * 10);
    const minY = 0;

    // Grid lines
    ctx.strokeStyle = '#222533';
    ctx.lineWidth = 1;
    const ySteps = 5;
    for (let i = 0; i <= ySteps; i++) {
        const y = pad.top + (ch / ySteps) * i;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(pad.left + cw, y);
        ctx.stroke();

        // Y axis labels
        const val = maxY - (maxY - minY) * (i / ySteps);
        ctx.fillStyle = '#8b90a0';
        ctx.font = '11px Inter, sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText(val.toFixed(0) + '%', pad.left - 8, y + 4);
    }

    // X axis labels
    ctx.textAlign = 'center';
    ctx.fillStyle = '#8b90a0';
    for (let i = 0; i < generations.length; i++) {
        const x = pad.left + (cw / Math.max(1, generations.length - 1)) * i;
        ctx.fillText('Gen ' + generations[i].generation, x, h - 8);
    }

    if (generations.length < 2) {
        // Single point
        const x = pad.left + cw / 2;
        const y = pad.top + ch - (winRates[0] / maxY) * ch;
        ctx.fillStyle = '#5b9ef0';
        ctx.beginPath();
        ctx.arc(x, y, 5, 0, Math.PI * 2);
        ctx.fill();
        return;
    }

    // Line
    ctx.strokeStyle = '#5b9ef0';
    ctx.lineWidth = 2.5;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.beginPath();
    for (let i = 0; i < winRates.length; i++) {
        const x = pad.left + (cw / (winRates.length - 1)) * i;
        const y = pad.top + ch - (winRates[i] / maxY) * ch;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Area fill
    ctx.globalAlpha = 0.1;
    ctx.fillStyle = '#5b9ef0';
    ctx.beginPath();
    for (let i = 0; i < winRates.length; i++) {
        const x = pad.left + (cw / (winRates.length - 1)) * i;
        const y = pad.top + ch - (winRates[i] / maxY) * ch;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.lineTo(pad.left + cw, pad.top + ch);
    ctx.lineTo(pad.left, pad.top + ch);
    ctx.closePath();
    ctx.fill();
    ctx.globalAlpha = 1;

    // Points
    for (let i = 0; i < winRates.length; i++) {
        const x = pad.left + (cw / (winRates.length - 1)) * i;
        const y = pad.top + ch - (winRates[i] / maxY) * ch;
        const gen = generations[i];

        // Dot color based on status
        ctx.fillStyle = gen.status === 'passed' ? '#4ade80' :
                         gen.status === 'failed' ? '#f87171' : '#5b9ef0';
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fill();

        // White center
        ctx.fillStyle = '#12141c';
        ctx.beginPath();
        ctx.arc(x, y, 2, 0, Math.PI * 2);
        ctx.fill();
    }

    // Legend
    ctx.font = '11px Inter, sans-serif';
    const legendX = pad.left + 10;
    const legendY = pad.top + 15;

    ctx.fillStyle = '#4ade80';
    ctx.beginPath();
    ctx.arc(legendX, legendY, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#8b90a0';
    ctx.textAlign = 'left';
    ctx.fillText('Passed', legendX + 10, legendY + 4);

    ctx.fillStyle = '#f87171';
    ctx.beginPath();
    ctx.arc(legendX + 70, legendY, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#8b90a0';
    ctx.fillText('Failed', legendX + 80, legendY + 4);
}

function renderCompositionChart(generations) {
    const canvas = document.getElementById('composition-canvas');
    const empty = document.getElementById('composition-empty');

    if (!generations || generations.length === 0) {
        canvas.style.display = 'none';
        empty.style.display = '';
        return;
    }

    canvas.style.display = 'block';
    empty.style.display = 'none';

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    const w = rect.width;
    const h = 220;

    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const pad = { top: 30, right: 30, bottom: 40, left: 55 };
    const cw = w - pad.left - pad.right;
    const ch = h - pad.top - pad.bottom;

    const barWidth = Math.min(40, cw / generations.length - 8);

    // Find max dataset size for scaling
    const maxDataset = Math.max(...generations.map(g => (g.forge_samples || 0) + (g.ppo_samples || 0)), 1);

    // Y axis
    ctx.strokeStyle = '#222533';
    ctx.lineWidth = 1;
    const ySteps = 4;
    for (let i = 0; i <= ySteps; i++) {
        const y = pad.top + (ch / ySteps) * i;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(pad.left + cw, y);
        ctx.stroke();

        const val = maxDataset - (maxDataset * i / ySteps);
        ctx.fillStyle = '#8b90a0';
        ctx.font = '11px Inter, sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText(formatNumber(val), pad.left - 8, y + 4);
    }

    // Bars
    for (let i = 0; i < generations.length; i++) {
        const g = generations[i];
        const forge = g.forge_samples || 0;
        const ppo = g.ppo_samples || 0;
        const total = forge + ppo;

        const x = pad.left + (cw / generations.length) * i + (cw / generations.length - barWidth) / 2;

        // Forge bar (bottom)
        const forgeH = (forge / maxDataset) * ch;
        ctx.fillStyle = '#5b9ef0';
        ctx.beginPath();
        roundedRect(ctx, x, pad.top + ch - forgeH, barWidth, forgeH, 3);
        ctx.fill();

        // PPO bar (stacked on top)
        const ppoH = (ppo / maxDataset) * ch;
        ctx.fillStyle = '#a78bfa';
        ctx.beginPath();
        roundedRect(ctx, x, pad.top + ch - forgeH - ppoH, barWidth, ppoH, 3);
        ctx.fill();

        // X label
        ctx.fillStyle = '#8b90a0';
        ctx.font = '11px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('G' + g.generation, x + barWidth / 2, h - 8);
    }

    // Legend
    ctx.font = '11px Inter, sans-serif';
    const legendX = pad.left + 10;
    const legendY = pad.top + 12;

    ctx.fillStyle = '#5b9ef0';
    ctx.fillRect(legendX, legendY - 5, 10, 10);
    ctx.fillStyle = '#8b90a0';
    ctx.textAlign = 'left';
    ctx.fillText('Forge', legendX + 16, legendY + 4);

    ctx.fillStyle = '#a78bfa';
    ctx.fillRect(legendX + 65, legendY - 5, 10, 10);
    ctx.fillStyle = '#8b90a0';
    ctx.fillText('PPO', legendX + 81, legendY + 4);
}

function roundedRect(ctx, x, y, w, h, r) {
    if (h <= 0) return;
    r = Math.min(r, h / 2, w / 2);
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
}

function formatNumber(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return Math.round(n).toString();
}

// ═══════════════════════════════════════════
// History Table
// ═══════════════════════════════════════════

function renderHistoryTable(generations) {
    const container = document.getElementById('history-table-container');
    const empty = document.getElementById('history-empty');

    if (!generations || generations.length === 0) {
        container.innerHTML = '';
        container.appendChild(empty);
        empty.style.display = '';
        return;
    }

    let html = '<table class="data-table distill-history-table">';
    html += '<thead><tr>';
    html += '<th>Gen</th>';
    html += '<th>Status</th>';
    html += '<th>Win Rate</th>';
    html += '<th>Supervised Acc</th>';
    html += '<th>PPO Decisions</th>';
    html += '<th>Gate</th>';
    html += '<th>Retries</th>';
    html += '</tr></thead><tbody>';

    for (const g of generations) {
        const statusClass = g.status === 'passed' ? 'tag-green' :
                           g.status === 'failed' ? 'tag-red' :
                           g.status === 'running' ? 'tag-blue' : 'tag-yellow';

        const wrPct = g.ppo_best_win_rate > 0 ? (g.ppo_best_win_rate * 100).toFixed(1) + '%' : '--';
        const supAcc = g.supervised_val_acc > 0 ? (g.supervised_val_acc * 100).toFixed(1) + '%' : '--';
        const decisions = g.ppo_decisions_exported > 0 ? g.ppo_decisions_exported.toLocaleString() : '--';
        const gateIcon = g.gate_accepted ? '&#9989;' : (g.status === 'running' ? '&#8987;' : '&#10060;');

        html += `<tr>
            <td style="font-weight:600;color:var(--accent);">${g.generation}</td>
            <td><span class="tag ${statusClass}">${g.status}</span></td>
            <td style="font-variant-numeric:tabular-nums;">${wrPct}</td>
            <td style="font-variant-numeric:tabular-nums;">${supAcc}</td>
            <td style="font-variant-numeric:tabular-nums;">${decisions}</td>
            <td style="text-align:center;">${gateIcon}</td>
            <td style="text-align:center;color:var(--text-secondary);">${g.retries || 0}</td>
        </tr>`;
    }

    html += '</tbody></table>';
    container.innerHTML = html;
}

// ═══════════════════════════════════════════
// Window Resize Handler (redraw charts)
// ═══════════════════════════════════════════

let resizeTimeout = null;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
        if (generationsData.length > 0) {
            renderWinRateChart(generationsData);
            renderCompositionChart(generationsData);
        }
    }, 200);
});
