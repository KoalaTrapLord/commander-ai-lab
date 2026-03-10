/**
 * Commander AI Lab — ML Training Dashboard
 * Manages training pipeline, data status, and evaluation display.
 */

const API_BASE = '';  // Same origin

// ═══════════════════════════════════════════
// State
// ═══════════════════════════════════════════

let pollingInterval = null;
let isTraining = false;

// ═══════════════════════════════════════════
// Init
// ═══════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    refreshDataStatus();
    refreshTrainingStatus();
});

// ═══════════════════════════════════════════
// Data Status
// ═══════════════════════════════════════════

async function refreshDataStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/ml/data/status`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderDataStatus(data);
    } catch (err) {
        console.error('Failed to fetch data status:', err);
    }
}

function renderDataStatus(data) {
    // Status cards
    const totalDecisions = data.totalDecisions || 0;
    document.getElementById('val-decisions').textContent = totalDecisions.toLocaleString();
    document.getElementById('sub-decisions').textContent =
        data.decisionFiles.length > 0
            ? `${data.decisionFiles.length} file${data.decisionFiles.length !== 1 ? 's' : ''}`
            : 'no decision logs';

    const cardData = document.getElementById('card-data');
    cardData.classList.toggle('active', totalDecisions > 0);

    // Dataset card
    const trainData = data.datasets.train;
    if (trainData) {
        document.getElementById('val-dataset').textContent = trainData.samples.toLocaleString();
        document.getElementById('sub-dataset').textContent =
            `${trainData.features} features`;
        document.getElementById('card-dataset').classList.add('active');
    } else {
        document.getElementById('val-dataset').textContent = '--';
        document.getElementById('sub-dataset').textContent = 'not built';
    }

    // Model card
    if (data.checkpoints.length > 0) {
        const latest = data.checkpoints[data.checkpoints.length - 1];
        const sizeKB = (latest.size / 1024).toFixed(0);
        document.getElementById('val-model').textContent = `${sizeKB} KB`;
        document.getElementById('sub-model').textContent = latest.name;
        document.getElementById('card-model').classList.add('active');
    } else {
        document.getElementById('val-model').textContent = '--';
        document.getElementById('sub-model').textContent = 'no checkpoint';
    }

    // Server card
    if (data.policyLoaded) {
        document.getElementById('val-server').textContent = 'Online';
        document.getElementById('sub-server').textContent = 'ready for inference';
        document.getElementById('card-server').classList.add('success');
    } else {
        document.getElementById('val-server').textContent = 'Offline';
        document.getElementById('sub-server').textContent = 'not loaded';
        document.getElementById('card-server').classList.remove('success');
    }

    // Data files list
    renderDataFiles(data);

    // Eval results
    if (data.evalResults) {
        renderEvaluation(data.evalResults);
    }

    // Checkpoints
    renderCheckpoints(data.checkpoints);
}

function renderDataFiles(data) {
    const container = document.getElementById('data-files-list');

    if (data.decisionFiles.length === 0 && Object.keys(data.datasets).length === 0) {
        container.innerHTML = '<div class="empty-state">No training data found. Run batch simulations with ML logging enabled to generate decision data.</div>';
        return;
    }

    let html = '';

    // Decision log files
    for (const f of data.decisionFiles) {
        const sizeKB = (f.size / 1024).toFixed(1);
        html += `
            <div class="file-row">
                <span class="file-name">${f.name}</span>
                <span class="file-meta">
                    <span>${f.decisions.toLocaleString()} decisions</span>
                    <span>${sizeKB} KB</span>
                </span>
            </div>`;
    }

    // Dataset splits
    for (const [split, info] of Object.entries(data.datasets)) {
        const badgeClass = split === 'train' ? 'badge-train' : split === 'val' ? 'badge-val' : 'badge-test';
        const sizeKB = (info.size / 1024).toFixed(1);
        html += `
            <div class="file-row">
                <span class="file-name">${split}.npz <span class="badge ${badgeClass}">${split}</span></span>
                <span class="file-meta">
                    <span>${(info.samples || 0).toLocaleString()} samples</span>
                    <span>${sizeKB} KB</span>
                </span>
            </div>`;
    }

    container.innerHTML = html;
}

function renderCheckpoints(checkpoints) {
    const container = document.getElementById('checkpoint-list');
    if (!checkpoints || checkpoints.length === 0) {
        container.innerHTML = '<div class="empty-state">No checkpoints found. Train a model to generate checkpoints.</div>';
        return;
    }

    let html = '';
    for (const ckpt of checkpoints.reverse()) {
        const sizeKB = (ckpt.size / 1024).toFixed(0);
        const date = new Date(ckpt.modified);
        const timeStr = date.toLocaleString();
        html += `
            <div class="ckpt-row">
                <span class="ckpt-name">${ckpt.name}</span>
                <span class="ckpt-meta">
                    <span>${sizeKB} KB</span>
                    <span>${timeStr}</span>
                </span>
            </div>`;
    }
    container.innerHTML = html;
}

// ═══════════════════════════════════════════
// Evaluation Display
// ═══════════════════════════════════════════

function renderEvaluation(results) {
    const container = document.getElementById('eval-results');
    if (!results) {
        container.innerHTML = '<div class="empty-state">No evaluation results yet. Train a model first.</div>';
        return;
    }

    const accuracy = results.accuracy || 0;
    const accClass = accuracy >= 0.5 ? 'good' : accuracy >= 0.3 ? 'ok' : 'bad';
    const samples = results.total_samples || 0;
    const topK = results.top_3_accuracy || 0;

    let html = `
        <div class="eval-summary">
            <div class="eval-metric">
                <div class="eval-metric-label">Test Accuracy</div>
                <div class="eval-metric-value ${accClass}">${(accuracy * 100).toFixed(1)}%</div>
            </div>
            <div class="eval-metric">
                <div class="eval-metric-label">Top-3 Accuracy</div>
                <div class="eval-metric-value">${(topK * 100).toFixed(1)}%</div>
            </div>
            <div class="eval-metric">
                <div class="eval-metric-label">Test Samples</div>
                <div class="eval-metric-value">${samples.toLocaleString()}</div>
            </div>
        </div>`;

    // Per-class accuracy
    if (results.per_class_accuracy) {
        html += '<h3 style="margin-top: 16px; margin-bottom: 8px; font-size: 14px; color: #fff;">Per-Action Accuracy</h3>';
        html += '<table class="class-table"><thead><tr><th>Action</th><th>Accuracy</th><th style="width: 40%"></th><th>Support</th></tr></thead><tbody>';

        const actions = results.per_class_accuracy;
        for (const [action, acc] of Object.entries(actions)) {
            const pct = (acc * 100).toFixed(1);
            const barColor = acc >= 0.5 ? 'var(--lab-success)' : acc >= 0.3 ? 'var(--lab-warning)' : 'var(--lab-error)';
            const support = results.per_class_support ? (results.per_class_support[action] || '--') : '--';
            html += `
                <tr>
                    <td style="color: var(--lab-accent); font-weight: 600;">${action}</td>
                    <td>${pct}%</td>
                    <td>
                        <div class="acc-bar-bg">
                            <div class="acc-bar" style="width: ${pct}%; background: ${barColor};"></div>
                        </div>
                    </td>
                    <td style="color: var(--lab-text-dim);">${support}</td>
                </tr>`;
        }
        html += '</tbody></table>';
    }

    // Confusion matrix
    if (results.confusion_matrix && results.class_names) {
        html += '<h3 style="margin-top: 16px; margin-bottom: 8px; font-size: 14px; color: #fff;">Confusion Matrix</h3>';
        html += '<div class="confusion-matrix"><table>';
        html += '<tr><th></th>';
        for (const name of results.class_names) {
            const short = name.replace('cast_', '').replace('activate_', 'act_').substring(0, 8);
            html += `<th>${short}</th>`;
        }
        html += '</tr>';

        const matrix = results.confusion_matrix;
        for (let i = 0; i < matrix.length; i++) {
            const shortName = results.class_names[i].replace('cast_', '').replace('activate_', 'act_').substring(0, 8);
            html += `<tr><td class="row-label">${shortName}</td>`;
            const rowMax = Math.max(...matrix[i]);
            for (let j = 0; j < matrix[i].length; j++) {
                const val = matrix[i][j];
                const intensity = rowMax > 0 ? val / rowMax : 0;
                let bg = 'transparent';
                if (i === j) {
                    bg = `rgba(63, 185, 80, ${intensity * 0.4})`;
                } else if (val > 0) {
                    bg = `rgba(248, 81, 73, ${intensity * 0.3})`;
                }
                html += `<td style="background: ${bg};">${val}</td>`;
            }
            html += '</tr>';
        }
        html += '</table></div>';
    }

    container.innerHTML = html;
}

// ═══════════════════════════════════════════
// Training Control
// ═══════════════════════════════════════════

async function startTraining() {
    const epochs = parseInt(document.getElementById('param-epochs').value) || 50;
    const lr = parseFloat(document.getElementById('param-lr').value) || 0.001;
    const batchSize = parseInt(document.getElementById('param-batch').value) || 256;
    const patience = parseInt(document.getElementById('param-patience').value) || 10;
    const rebuild = document.getElementById('param-rebuild').checked;

    const btn = document.getElementById('btn-train');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">&#8987;</span> Starting...';

    try {
        const res = await fetch(`${API_BASE}/api/ml/train`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ epochs, lr, batchSize, patience, rebuildDataset: rebuild }),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        isTraining = true;
        showProgress();
        startPolling();

    } catch (err) {
        alert('Failed to start training: ' + err.message);
        btn.disabled = false;
        btn.innerHTML = '<span class="btn-icon">&#9654;</span> Start Training';
    }
}

async function reloadModel() {
    try {
        const res = await fetch(`${API_BASE}/api/ml/reload`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            alert('Policy model reloaded successfully.');
            refreshDataStatus();
        } else {
            alert('Model reload failed. Check if a checkpoint exists.');
        }
    } catch (err) {
        alert('Reload failed: ' + err.message);
    }
}

// ═══════════════════════════════════════════
// Progress Polling
// ═══════════════════════════════════════════

function showProgress() {
    document.getElementById('train-progress').classList.remove('hidden');
}

function hideProgress() {
    // Keep visible so user can see final result
}

function startPolling() {
    if (pollingInterval) clearInterval(pollingInterval);
    pollingInterval = setInterval(pollTrainingStatus, 2000);
}

function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

async function refreshTrainingStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/ml/train/status`);
        const data = await res.json();

        if (data.running) {
            isTraining = true;
            showProgress();
            updateProgress(data);
            startPolling();
        } else if (data.phase === 'done' || data.phase === 'error') {
            showProgress();
            updateProgress(data);
        }
    } catch (err) {
        // Silently fail on initial check
    }
}

async function pollTrainingStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/ml/train/status`);
        const data = await res.json();
        updateProgress(data);

        if (!data.running) {
            stopPolling();
            isTraining = false;

            const btn = document.getElementById('btn-train');
            btn.disabled = false;
            btn.innerHTML = '<span class="btn-icon">&#9654;</span> Start Training';

            // Refresh all data
            refreshDataStatus();
        }
    } catch (err) {
        console.error('Poll failed:', err);
    }
}

// ═══════════════════════════════════════════
// PPO Training
// ═══════════════════════════════════════════

let ppoPollingInterval = null;

async function startPPO() {
    const iterations = parseInt(document.getElementById('ppo-iterations').value) || 100;
    const episodesPerIter = parseInt(document.getElementById('ppo-episodes').value) || 64;
    const lr = parseFloat(document.getElementById('ppo-lr').value) || 3e-4;
    const opponent = document.getElementById('ppo-opponent').value;
    const loadSupervised = document.getElementById('ppo-load-supervised').checked
        ? 'ml/models/checkpoints/best_policy.pt' : '';

    const btn = document.getElementById('btn-ppo');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">&#8987;</span> Starting...';

    try {
        const res = await fetch(`${API_BASE}/api/ml/train/ppo`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ iterations, episodesPerIter, lr, opponent, loadSupervised }),
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        document.getElementById('ppo-progress').classList.remove('hidden');
        startPPOPolling();
    } catch (err) {
        alert('Failed to start PPO: ' + err.message);
        btn.disabled = false;
        btn.innerHTML = '<span class="btn-icon">&#9654;</span> Start PPO Training';
    }
}

function startPPOPolling() {
    if (ppoPollingInterval) clearInterval(ppoPollingInterval);
    ppoPollingInterval = setInterval(pollPPOStatus, 2000);
}

async function pollPPOStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/ml/train/ppo/status`);
        const data = await res.json();
        updatePPOProgress(data);

        if (!data.running && data.phase !== 'idle') {
            clearInterval(ppoPollingInterval);
            ppoPollingInterval = null;
            const btn = document.getElementById('btn-ppo');
            btn.disabled = false;
            btn.innerHTML = '<span class="btn-icon">&#9654;</span> Start PPO Training';
            refreshDataStatus();
        }
    } catch (err) { console.error('PPO poll error:', err); }
}

function updatePPOProgress(data) {
    const phase = data.phase || 'idle';
    const phaseEl = document.getElementById('ppo-progress-phase');
    phaseEl.textContent = phase.toUpperCase();
    phaseEl.className = 'phase-badge ' + phase;

    document.getElementById('ppo-progress-message').textContent = data.message || '';

    const bar = document.getElementById('ppo-progress-bar');
    bar.className = 'progress-bar';
    if (phase === 'done') {
        bar.style.width = '100%';
        bar.classList.add('done');
    } else if (phase === 'error') {
        bar.style.width = '100%';
        bar.classList.add('error');
    } else if (data.total_iterations > 0) {
        bar.style.width = Math.min(100, (data.iteration / data.total_iterations) * 100) + '%';
    }

    const detail = document.getElementById('ppo-progress-detail');
    if (data.metrics) {
        const m = data.metrics;
        detail.textContent = `Win Rate: ${((m.win_rate||0)*100).toFixed(0)}% | Policy Loss: ${(m.policy_loss||0).toFixed(4)} | Entropy: ${(m.entropy||0).toFixed(3)}`;
    } else if (phase === 'done' && data.result) {
        detail.textContent = `Best Win Rate: ${((data.result.best_win_rate||0)*100).toFixed(0)}% | ${data.result.total_steps} total steps`;
    } else if (phase === 'error') {
        detail.textContent = data.error || '';
        detail.style.color = 'var(--lab-error)';
    } else {
        detail.textContent = '';
    }
}

// ═══════════════════════════════════════════
// Tournament
// ═══════════════════════════════════════════

let tourneyPollingInterval = null;

async function startTournament() {
    const episodes = parseInt(document.getElementById('tourney-episodes').value) || 50;
    const playstyle = document.getElementById('tourney-style').value;

    const btn = document.getElementById('btn-tourney');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">&#8987;</span> Running...';

    try {
        const res = await fetch(`${API_BASE}/api/ml/tournament`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ episodes, playstyle }),
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        document.getElementById('tourney-progress').classList.remove('hidden');
        startTourneyPolling();
    } catch (err) {
        alert('Failed to start tournament: ' + err.message);
        btn.disabled = false;
        btn.innerHTML = '<span class="btn-icon">&#127942;</span> Run Tournament';
    }
}

function startTourneyPolling() {
    if (tourneyPollingInterval) clearInterval(tourneyPollingInterval);
    tourneyPollingInterval = setInterval(pollTourneyStatus, 2000);
}

async function pollTourneyStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/ml/tournament/status`);
        const data = await res.json();

        const phase = data.phase || 'idle';
        const phaseEl = document.getElementById('tourney-progress-phase');
        phaseEl.textContent = phase.toUpperCase();
        phaseEl.className = 'phase-badge ' + phase;
        document.getElementById('tourney-progress-message').textContent = data.message || '';

        const bar = document.getElementById('tourney-progress-bar');
        bar.className = 'progress-bar';
        if (phase === 'done') {
            bar.style.width = '100%';
            bar.classList.add('done');
        } else if (phase === 'error') {
            bar.style.width = '100%';
            bar.classList.add('error');
        } else if (phase === 'running') {
            bar.style.width = '50%';
        }

        if (!data.running && data.phase !== 'idle') {
            clearInterval(tourneyPollingInterval);
            tourneyPollingInterval = null;
            const btn = document.getElementById('btn-tourney');
            btn.disabled = false;
            btn.innerHTML = '<span class="btn-icon">&#127942;</span> Run Tournament';

            if (data.result) {
                renderTournamentResults(data.result);
            }
            document.getElementById('tourney-progress').classList.add('hidden');
        }
    } catch (err) { console.error('Tournament poll error:', err); }
}

function renderTournamentResults(data) {
    const container = document.getElementById('tourney-results');
    if (!data || !data.win_rates) {
        container.innerHTML = '<div class="empty-state">No results available.</div>';
        return;
    }

    // Sort by win rate
    const sorted = Object.entries(data.win_rates)
        .sort((a, b) => (b[1].win_rate || 0) - (a[1].win_rate || 0));

    let html = '<h3 style="font-size:14px;color:#fff;margin-bottom:8px;">Leaderboard</h3>';
    html += '<table class="class-table"><thead><tr><th>Rank</th><th>Policy</th><th>Win Rate</th><th>Wins</th><th>Losses</th><th>Draws</th></tr></thead><tbody>';

    sorted.forEach(([name, stats], i) => {
        const wr = ((stats.win_rate || 0) * 100).toFixed(1);
        const wrColor = stats.win_rate >= 0.6 ? 'var(--lab-success)' : stats.win_rate >= 0.4 ? 'var(--lab-warning)' : 'var(--lab-error)';
        const medal = i === 0 ? '&#129351;' : i === 1 ? '&#129352;' : i === 2 ? '&#129353;' : (i+1);
        html += `<tr>
            <td style="text-align:center;">${medal}</td>
            <td style="color:var(--lab-accent);font-weight:600;">${name}</td>
            <td style="color:${wrColor};font-weight:700;">${wr}%</td>
            <td>${stats.wins}</td>
            <td>${stats.losses}</td>
            <td>${stats.draws}</td>
        </tr>`;
    });
    html += '</tbody></table>';

    // Win matrix
    if (data.win_matrix && data.policies) {
        html += '<h3 style="font-size:14px;color:#fff;margin:16px 0 8px;">Head-to-Head Wins</h3>';
        html += '<div class="confusion-matrix"><table><tr><th></th>';
        data.policies.forEach(p => html += `<th>${p}</th>`);
        html += '</tr>';
        data.policies.forEach(row => {
            html += `<tr><td class="row-label">${row}</td>`;
            data.policies.forEach(col => {
                if (row === col) {
                    html += '<td style="color:var(--lab-text-dim);">-</td>';
                } else {
                    const val = data.win_matrix[row]?.[col] || 0;
                    html += `<td>${val}</td>`;
                }
            });
            html += '</tr>';
        });
        html += '</table></div>';
    }

    html += `<div style="margin-top:12px;font-size:12px;color:var(--lab-text-dim);">${data.total_matches} total matches in ${(data.total_time_s||0).toFixed(1)}s</div>`;
    container.innerHTML = html;
}

// Load tournament results on page load
async function loadTournamentResults() {
    try {
        const res = await fetch(`${API_BASE}/api/ml/tournament/results`);
        const data = await res.json();
        if (!data.error) {
            renderTournamentResults(data);
        }
    } catch (err) { /* ignore */ }
}

// Also check PPO status on load
async function checkPPOStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/ml/train/ppo/status`);
        const data = await res.json();
        if (data.running) {
            document.getElementById('ppo-progress').classList.remove('hidden');
            updatePPOProgress(data);
            startPPOPolling();
        } else if (data.phase === 'done' || data.phase === 'error') {
            document.getElementById('ppo-progress').classList.remove('hidden');
            updatePPOProgress(data);
        }
    } catch (err) { /* ignore */ }
}

// Add to init
const _origDOMLoaded = document.addEventListener;
document.addEventListener('DOMContentLoaded', () => {
    // These are called after the original DOMContentLoaded handler
    setTimeout(() => {
        checkPPOStatus();
        loadTournamentResults();
    }, 500);
});

function updateProgress(data) {
    const phaseBadge = document.getElementById('progress-phase');
    const message = document.getElementById('progress-message');
    const bar = document.getElementById('progress-bar');
    const detail = document.getElementById('progress-detail');

    // Phase badge
    const phase = data.phase || 'idle';
    phaseBadge.textContent = phase.toUpperCase();
    phaseBadge.className = 'phase-badge ' + phase;

    // Message
    message.textContent = data.message || '';

    // Progress bar
    bar.className = 'progress-bar';
    if (phase === 'done') {
        bar.style.width = '100%';
        bar.classList.add('done');
    } else if (phase === 'error') {
        bar.style.width = '100%';
        bar.classList.add('error');
    } else if (phase === 'training' && data.total_epochs > 0) {
        const pct = Math.min(100, (data.current_epoch / data.total_epochs) * 100);
        bar.style.width = pct + '%';
    } else if (phase === 'building') {
        bar.style.width = '15%';
    } else if (phase === 'evaluating') {
        bar.style.width = '90%';
    } else if (phase === 'starting') {
        bar.style.width = '5%';
    }

    // Detail
    if (phase === 'training' && data.total_epochs > 0) {
        detail.textContent = `Epoch ${data.current_epoch} / ${data.total_epochs}`;
    } else if (phase === 'done' && data.result) {
        const r = data.result;
        const valAcc = r.training?.best_val_accuracy;
        const testAcc = r.evaluation?.accuracy;
        let parts = [];
        if (valAcc !== undefined) parts.push(`Val: ${(valAcc * 100).toFixed(1)}%`);
        if (testAcc !== undefined) parts.push(`Test: ${(testAcc * 100).toFixed(1)}%`);
        if (r.device) parts.push(`Device: ${r.device}`);
        detail.textContent = parts.join('  |  ');
    } else if (phase === 'error') {
        detail.textContent = data.error || 'Unknown error';
        detail.style.color = 'var(--lab-error)';
    } else {
        detail.textContent = '';
        detail.style.color = '';
    }

    // Update train button
    const btn = document.getElementById('btn-train');
    if (data.running) {
        btn.disabled = true;
        btn.innerHTML = '<span class="btn-icon">&#8987;</span> Training...';
    }
}
