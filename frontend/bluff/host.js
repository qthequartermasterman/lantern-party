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
  listEl.innerHTML = '';
  scores.forEach((s, i) => {
    const li = document.createElement('li');
    li.className = 'score-row';
    const rankEl = document.createElement('span');
    rankEl.className = 'score-rank' + (i === 0 ? ' top' : '');
    rankEl.textContent = String(i + 1);
    const nameEl = document.createElement('span');
    nameEl.className = 'score-name';
    nameEl.textContent = s.name;
    const ptsEl = document.createElement('span');
    ptsEl.className = 'score-pts';
    ptsEl.textContent = s.score.toLocaleString();
    li.appendChild(rankEl);
    li.appendChild(nameEl);
    li.appendChild(ptsEl);
    listEl.appendChild(li);
  });
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
  grid.innerHTML = '';
  data.players.forEach(p => {
    const tile = document.createElement('div');
    tile.classList.add('player-tile');
    if (p.ready) tile.classList.add('ready');
    const nameEl = document.createElement('div');
    nameEl.className = 'pname';
    nameEl.textContent = p.name;
    const statusEl = document.createElement('div');
    statusEl.className = 'pstatus';
    statusEl.textContent = p.ready ? '✓ Ready' : 'Waiting…';
    tile.appendChild(nameEl);
    tile.appendChild(statusEl);
    grid.appendChild(tile);
  });
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
  grid.innerHTML = '';
  data.choices.forEach(c => {
    const card = document.createElement('div');
    card.className = 'choice-card';
    const idxEl = document.createElement('div');
    idxEl.className = 'choice-idx';
    idxEl.textContent = `Choice ${c.index + 1}`;
    const textEl = document.createElement('div');
    textEl.className = 'choice-text';
    textEl.textContent = c.text;
    card.appendChild(idxEl);
    card.appendChild(textEl);
    grid.appendChild(card);
  });

  document.getElementById('next-btn').classList.remove('visible');
  show('voting-screen');
}

// ── Revealing ─────────────────────────────────────────────────────────
function handleReveal(data) {
  document.getElementById('reveal-prompt').innerHTML = highlightPrompt(data.prompt);

  const grid = document.getElementById('reveal-choice-grid');
  grid.innerHTML = '';
  data.choices.forEach(c => {
    const isTruth = c.is_truth;
    const card = document.createElement('div');
    card.className = 'choice-card' + (isTruth ? ' is-truth' : '');
    if (isTruth) {
      const badge = document.createElement('div');
      badge.className = 'truth-badge';
      badge.textContent = '✓ Truth';
      card.appendChild(badge);
    }
    const textEl = document.createElement('div');
    textEl.className = 'choice-text';
    textEl.textContent = c.text;
    card.appendChild(textEl);
    const footer = document.createElement('div');
    footer.className = 'choice-footer';
    if (isTruth) {
      const votesSpan = document.createElement('span');
      votesSpan.className = 'choice-votes';
      votesSpan.textContent = `${c.votes} vote${c.votes !== 1 ? 's' : ''}`;
      footer.appendChild(votesSpan);
    } else {
      const submitterSpan = document.createElement('span');
      submitterSpan.className = 'choice-submitter';
      submitterSpan.textContent = c.submitter_name || '?';
      footer.appendChild(submitterSpan);
      if (c.game_provided) {
        const gpBadge = document.createElement('span');
        gpBadge.className = 'game-provided-badge';
        gpBadge.textContent = 'auto';
        footer.appendChild(gpBadge);
      }
      footer.appendChild(document.createTextNode(' · '));
      const votesSpan = document.createElement('span');
      votesSpan.className = 'choice-votes';
      votesSpan.textContent = `${c.votes} vote${c.votes !== 1 ? 's' : ''}`;
      footer.appendChild(votesSpan);
      footer.appendChild(document.createTextNode(' · ❤️ '));
      const likesSpan = document.createElement('span');
      likesSpan.id = `likes-${c.index}`;
      likesSpan.textContent = String(c.likes || 0);
      footer.appendChild(likesSpan);
    }
    card.appendChild(footer);
    grid.appendChild(card);
  });

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
