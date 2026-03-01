/* Bluff & Baffle – Host JavaScript */

// ── Utilities ───────────────────────────────────────────────────────
const partyCode = window.location.pathname.split('/').pop().toUpperCase();
document.getElementById('party-code-display').textContent = partyCode;
document.getElementById('lobby-code').textContent = partyCode;

function show(screenId) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(screenId).classList.add('active');
}

function renderScores(scores, listEl) {
  listEl.innerHTML = scores.map((s, i) => `
    <li class="score-row">
      <span class="score-rank ${i === 0 ? 'top' : ''}">${i + 1}</span>
      <span class="score-name">${s.name}</span>
      <span class="score-pts">${s.score.toLocaleString()}</span>
    </li>`).join('');
}

function highlightPrompt(prompt) {
  return prompt.replace(/_____/g, '<span class="q-blank">_____</span>');
}

// ── WebSocket ────────────────────────────────────────────────────────
const proto = location.protocol === 'https:' ? 'wss' : 'ws';
const ws = new WebSocket(`${proto}://${location.host}/ws/${partyCode}/host`);

let timerInterval = null;
let localTimer = 0;

function startLocalTimer(seconds) {
  clearInterval(timerInterval);
  localTimer = seconds;
  updateTimerDisplay();
  timerInterval = setInterval(() => {
    localTimer = Math.max(0, localTimer - 1);
    updateTimerDisplay();
    if (localTimer === 0) clearInterval(timerInterval);
  }, 1000);
}

function updateTimerDisplay() {
  const el = document.getElementById('timer-bar');
  el.textContent = localTimer > 0 ? `⏱ ${localTimer}s` : '';
  el.className = localTimer > 0 && localTimer <= 10 ? 'urgent' : '';
}

ws.addEventListener('message', e => {
  let msg;
  try { msg = JSON.parse(e.data); } catch { return; }
  const { type, data } = msg;

  if (type === 'timer')          { startLocalTimer(data.seconds_remaining); return; }
  if (type === 'lobby_state')    { handleLobby(data); return; }
  if (type === 'player_joined' || type === 'player_ready') return;
  if (type === 'bluff_question') { handleQuestion(data); return; }
  if (type === 'bluff_voting')   { handleVoting(data); return; }
  if (type === 'bluff_reveal')   { handleReveal(data); return; }
  if (type === 'bluff_scores')   { handleScores(data); return; }
  if (type === 'game_over')      { handleGameOver(data); return; }
  if (type === 'game_state')     { handleGameState(data); return; }
  if (type === 'like_update')    { handleLikeUpdate(data); return; }
});

// ── Lobby ────────────────────────────────────────────────────────────
function handleLobby(data) {
  show('lobby-screen');
  const grid = document.getElementById('player-grid');
  grid.innerHTML = data.players.map(p => `
    <div class="player-tile ${p.ready ? 'ready' : ''}">
      <div class="pname">${p.name}</div>
      <div class="pstatus">${p.ready ? '✓ Ready' : 'Waiting…'}</div>
    </div>`).join('');
  const readyCount = data.players.filter(p => p.ready).length;
  const btn = document.getElementById('start-btn');
  btn.disabled = readyCount < 2;
  btn.textContent = readyCount >= 2
    ? `Start Bluff & Baffle (${readyCount} ready)`
    : 'Need 2+ ready players';
}

document.getElementById('start-btn').addEventListener('click', () => {
  ws.send(JSON.stringify({ type: 'start_game', data: {} }));
});

// ── Game state (reconnection / partial updates) ─────────────────────
function handleGameState(data) {
  if (!data.game || data.game !== 'bluff') return;
  const phase = data.phase;
  if (phase === 'collecting_lies') {
    if (data.lies_received !== undefined) {
      updateProgress('lies-bar', 'lies-count', data.lies_received, data.lies_expected);
    }
    if (data.current_question) {
      renderQuestionCard(data.current_question);
      show('collecting-screen');
    }
  } else if (phase === 'voting') {
    if (data.votes_received !== undefined) {
      updateProgress('votes-bar', 'votes-count', data.votes_received, data.votes_expected);
    }
  } else if (phase === 'scores') {
    renderScoresScreen(data);
  } else if (phase === 'game_over') {
    handleGameOver(data);
  }
}

function updateProgress(barId, countId, received, expected) {
  const pct = expected > 0 ? (received / expected * 100) : 0;
  document.getElementById(barId).style.width = pct + '%';
  document.getElementById(countId).textContent = `${received}/${expected}`;
}

function renderQuestionCard(q) {
  document.getElementById('collect-category').textContent = q.category || '';
  document.getElementById('collect-prompt').innerHTML = highlightPrompt(q.prompt);
  document.getElementById('round-badge').textContent = `Round ${q.round_num || ''}`;
  document.getElementById('round-badge').className = 'rbadge active';
  document.getElementById('question-badge').textContent = q.question_num
    ? `Q ${q.question_num} / ${q.total_questions}` : '';
}

// ── Collecting lies ──────────────────────────────────────────────────
function handleQuestion(data) {
  document.getElementById('collect-category').textContent = data.category || '';
  document.getElementById('collect-prompt').innerHTML = highlightPrompt(data.prompt);
  document.getElementById('round-badge').textContent = `Round ${data.round_num}`;
  document.getElementById('round-badge').className = 'rbadge active';
  document.getElementById('question-badge').textContent = `Q ${data.question_num} / ${data.total_questions}`;
  updateProgress('lies-bar', 'lies-count', 0, 0);
  show('collecting-screen');
}

// ── Voting ────────────────────────────────────────────────────────────
function handleVoting(data) {
  document.getElementById('vote-category').textContent = data.category || '';
  document.getElementById('vote-prompt').innerHTML = highlightPrompt(data.prompt);
  document.getElementById('vote-round-badge').textContent = 'Voting';
  document.getElementById('vote-q-badge').textContent = '';
  updateProgress('votes-bar', 'votes-count', 0, 0);

  const grid = document.getElementById('vote-choice-grid');
  grid.innerHTML = data.choices.map(c => `
    <div class="choice-card">
      <div class="choice-idx">Choice ${c.index + 1}</div>
      <div class="choice-text">${c.text}</div>
    </div>`).join('');

  document.getElementById('next-btn').classList.remove('visible');
  show('voting-screen');
}

// ── Revealing ─────────────────────────────────────────────────────────
function handleReveal(data) {
  document.getElementById('reveal-prompt').innerHTML = highlightPrompt(data.prompt);

  const grid = document.getElementById('reveal-choice-grid');
  grid.innerHTML = data.choices.map(c => {
    const isTruth = c.is_truth;
    let footer = '';
    if (isTruth) {
      footer = `<div class="choice-footer"><span class="choice-votes">${c.votes} vote${c.votes !== 1 ? 's' : ''}</span></div>`;
    } else {
      const gp = c.game_provided ? `<span class="game-provided-badge">auto</span>` : '';
      footer = `
        <div class="choice-footer">
          <span class="choice-submitter">${c.submitter_name || '?'}${gp}</span>
          &nbsp;·&nbsp;<span class="choice-votes">${c.votes} vote${c.votes !== 1 ? 's' : ''}</span>
          &nbsp;· ❤️ <span id="likes-${c.index}">${c.likes || 0}</span>
        </div>`;
    }
    return `
      <div class="choice-card ${isTruth ? 'is-truth' : ''}">
        ${isTruth ? '<div class="truth-badge">✓ Truth</div>' : ''}
        <div class="choice-text">${c.text}</div>
        ${footer}
      </div>`;
  }).join('');

  const nextBtn = document.getElementById('next-btn');
  nextBtn.classList.add('visible');
  show('revealing-screen');
}

function handleLikeUpdate(data) {
  const el = document.getElementById(`likes-${data.choice_index}`);
  if (el) el.textContent = data.likes;
}

document.getElementById('next-btn').addEventListener('click', () => {
  ws.send(JSON.stringify({ type: 'next', data: {} }));
  document.getElementById('next-btn').classList.remove('visible');
});

// ── Scores ────────────────────────────────────────────────────────────
function handleScores(data) {
  renderScoresScreen(data);
  show('scores-screen');
}

function renderScoresScreen(data) {
  const r = data.round_complete;
  document.getElementById('scores-header').textContent =
    r ? `After Round ${r}` : 'Scores';
  renderScores(data.scores || [], document.getElementById('scores-list'));
}

// ── Game Over ─────────────────────────────────────────────────────────
function handleGameOver(data) {
  const winners = data.winners || [];
  document.getElementById('winners-banner').textContent =
    winners.length === 1 ? `🏆 ${winners[0]} wins!` : `🏆 Tie: ${winners.join(' & ')}`;
  const cup = data.thumbs_cup;
  document.getElementById('thumbs-cup').textContent =
    cup ? `👍 Thumbs Cup: ${cup}` : '';
  renderScores(data.final_scores || [], document.getElementById('final-scores-list'));
  show('gameover-screen');
}
