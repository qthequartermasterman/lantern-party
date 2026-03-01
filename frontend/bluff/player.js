/* Bluff & Baffle – Player JavaScript */

// ── Setup ─────────────────────────────────────────────────────────────
const partyCode = window.location.pathname.split('/').pop().toUpperCase();
const urlParams = new URLSearchParams(window.location.search);
document.getElementById('join-code-hint').textContent = `Party code: ${partyCode}`;

// Persist playerId
const storageKey = `bluff_pid_${partyCode}`;
const storedPid = sessionStorage.getItem(storageKey);
const actualPid = storedPid || crypto.randomUUID();
if (!storedPid) sessionStorage.setItem(storageKey, actualPid);

let playerName = sessionStorage.getItem('playerName') || '';
let myVoteIndex = null;
let likedChoices = new Set();

function show(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function showError(el, msg) { el.textContent = msg; el.classList.add('visible'); }
function clearError(el) { el.classList.remove('visible'); }

function highlightBlank(txt) {
  return txt.replace(/_____/g, '<span class="blank">_____</span>');
}

// ── Timer ─────────────────────────────────────────────────────────────
let timerInterval = null;
let localTimer = 0;
function startLocalTimer(s) {
  clearInterval(timerInterval);
  localTimer = s;
  updateTimerDisplay();
  timerInterval = setInterval(() => {
    localTimer = Math.max(0, localTimer - 1);
    updateTimerDisplay();
    if (localTimer === 0) clearInterval(timerInterval);
  }, 1000);
}
function updateTimerDisplay() {
  const el = document.getElementById('top-timer');
  el.textContent = localTimer > 0 ? `⏱ ${localTimer}s` : '';
  el.className = (localTimer > 0 && localTimer <= 10) ? 'urgent' : '';
}

// ── WebSocket ─────────────────────────────────────────────────────────
const proto = location.protocol === 'https:' ? 'wss' : 'ws';
const ws = new WebSocket(`${proto}://${location.host}/ws/${partyCode}/player/${actualPid}`);

ws.addEventListener('message', e => {
  let msg;
  try { msg = JSON.parse(e.data); } catch { return; }
  const { type, data } = msg;

  if (type === 'timer')          { startLocalTimer(data.seconds_remaining); return; }
  if (type === 'error')          { handleError(data); return; }
  if (type === 'lobby_state')    { handleLobby(data); return; }
  if (type === 'bluff_question') { handleQuestion(data); return; }
  if (type === 'bluff_voting')   { handleVoting(data); return; }
  if (type === 'bluff_reveal')   { handleReveal(data); return; }
  if (type === 'bluff_scores')   { handleScores(data); return; }
  if (type === 'game_over')      { handleGameOver(data); return; }
  if (type === 'game_state')     { handleGameState(data); return; }
  if (type === 'like_update')    { handleLikeUpdate(data); return; }
});

function send(type, data) {
  ws.send(JSON.stringify({ type, data }));
}

// ── Join ──────────────────────────────────────────────────────────────
if (playerName) document.getElementById('nameInput').value = playerName;

document.getElementById('joinBtn').addEventListener('click', () => {
  const name = document.getElementById('nameInput').value.trim();
  clearError(document.getElementById('joinError'));
  if (!name) { showError(document.getElementById('joinError'), 'Enter your name.'); return; }
  playerName = name;
  sessionStorage.setItem('playerName', name);
  send('join', { name });
});
document.getElementById('nameInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('joinBtn').click();
});

// ── Lobby ─────────────────────────────────────────────────────────────
function handleLobby(data) {
  const me = data.players.find(p => p.id === actualPid);
  if (!me) {
    if (playerName) send('join', { name: playerName });
    return;
  }
  document.getElementById('lobby-name').textContent = `Hey, ${me.name}! 👋`;
  document.getElementById('readyBtn').style.display   = me.ready ? 'none' : 'block';
  document.getElementById('unreadyBtn').style.display = me.ready ? 'block' : 'none';
  show('lobby-screen');
}

document.getElementById('readyBtn').addEventListener('click', () => {
  send('ready', { ready: true });
});
document.getElementById('unreadyBtn').addEventListener('click', () => {
  send('ready', { ready: false });
});

// ── Collecting lies ────────────────────────────────────────────────────
function handleQuestion(data) {
  document.getElementById('collect-meta').textContent =
    `Round ${data.round_num} · Q${data.question_num}/${data.total_questions} · ${data.category || ''}`;
  document.getElementById('collect-prompt').innerHTML = highlightBlank(data.prompt);
  document.getElementById('lieInput').value = '';
  document.getElementById('lieInput').disabled = false;
  document.getElementById('submitLieBtn').disabled = false;
  document.getElementById('lieForMeBtn').disabled = false;
  clearError(document.getElementById('lieError'));
  document.getElementById('collect-submitted').style.display = 'none';
  document.getElementById('collect-form').style.display = 'block';
  myVoteIndex = null;
  likedChoices = new Set();
  show('collecting-screen');
}

document.getElementById('submitLieBtn').addEventListener('click', () => {
  const text = document.getElementById('lieInput').value.trim();
  clearError(document.getElementById('lieError'));
  if (!text) { showError(document.getElementById('lieError'), 'Enter a lie first!'); return; }
  send('submit_lie', { text, lie_for_me: false });
  showSubmitted();
});

document.getElementById('lieForMeBtn').addEventListener('click', () => {
  clearError(document.getElementById('lieError'));
  send('submit_lie', { lie_for_me: true });
  showSubmitted();
});

document.getElementById('lieInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); document.getElementById('submitLieBtn').click(); }
});

function showSubmitted() {
  document.getElementById('collect-form').style.display = 'none';
  document.getElementById('collect-submitted').style.display = 'block';
}

// ── Voting ─────────────────────────────────────────────────────────────
let ownChoiceIndex = null;

function handleVoting(data) {
  ownChoiceIndex = null;
  myVoteIndex = null;

  document.getElementById('vote-meta').textContent = data.category || '';
  document.getElementById('vote-prompt').innerHTML = highlightBlank(data.prompt);

  const list = document.getElementById('vote-list');
  list.innerHTML = '';
  data.choices.forEach(c => {
    const li = document.createElement('li');
    li.className = 'vote-item';
    li.dataset.index = String(c.index);
    li.textContent = c.text;
    list.appendChild(li);
  });

  document.getElementById('vote-submitted').style.display = 'none';
  document.getElementById('vote-list').style.display = 'block';
  show('voting-screen');
}

document.getElementById('vote-list').addEventListener('click', e => {
  const item = e.target.closest('.vote-item');
  if (!item || item.classList.contains('own-answer')) return;
  if (myVoteIndex !== null) return;

  const idx = parseInt(item.dataset.index, 10);
  if (ownChoiceIndex !== null && idx === ownChoiceIndex) return;

  myVoteIndex = idx;
  document.querySelectorAll('.vote-item').forEach(el => el.classList.remove('selected'));
  item.classList.add('selected');
  send('submit_vote', { choice_index: idx });
  setTimeout(() => {
    document.getElementById('vote-submitted').style.display = 'block';
    document.getElementById('vote-list').style.display = 'none';
  }, 500);
});

// ── Revealing ──────────────────────────────────────────────────────────
function handleReveal(data) {
  document.getElementById('reveal-meta').textContent = data.truth ? `Truth: ${data.truth}` : '';
  document.getElementById('reveal-prompt').innerHTML = highlightBlank(data.prompt);

  const list = document.getElementById('reveal-list');
  list.innerHTML = '';
  data.choices.forEach(c => {
    const isTruth = c.is_truth;
    const iVoted = myVoteIndex === c.index;
    const isOwnLie = !isTruth && c.submitter_id === actualPid;

    const li = document.createElement('li');
    li.classList.add('reveal-item');
    if (isTruth) li.classList.add('truth-item');
    if (iVoted && isTruth) li.classList.add('voted-correct');

    if (isTruth) {
      const badge = document.createElement('div');
      badge.className = 'reveal-truth-badge';
      badge.textContent = '✓ Truth';
      li.appendChild(badge);
    }

    const answerDiv = document.createElement('div');
    answerDiv.className = 'reveal-answer';
    answerDiv.textContent = c.text;
    li.appendChild(answerDiv);

    const footerDiv = document.createElement('div');
    footerDiv.className = 'reveal-footer';

    if (isTruth) {
      const span = document.createElement('span');
      span.textContent = iVoted ? '✓ You got it!' : '';
      footerDiv.appendChild(span);
    } else {
      const submitterSpan = document.createElement('span');
      submitterSpan.className = 'reveal-submitter';
      const gp = c.game_provided ? ' (auto)' : '';
      submitterSpan.textContent = (c.submitter_name || '?') + gp + (isOwnLie ? ' (you)' : '');
      footerDiv.appendChild(submitterSpan);

      const votesSpan = document.createElement('span');
      votesSpan.textContent = `${c.votes} vote${c.votes !== 1 ? 's' : ''}`;
      footerDiv.appendChild(votesSpan);

      if (!isOwnLie) {
        const likeBtn = document.createElement('button');
        likeBtn.className = 'like-btn';
        likeBtn.dataset.index = String(c.index);
        likeBtn.appendChild(document.createTextNode('👍 '));
        const likesSpan = document.createElement('span');
        likesSpan.id = `likes-${c.index}`;
        likesSpan.textContent = String(c.likes || 0);
        likeBtn.appendChild(likesSpan);
        footerDiv.appendChild(likeBtn);
      }
    }

    li.appendChild(footerDiv);
    list.appendChild(li);
  });

  show('revealing-screen');
}

document.getElementById('reveal-list').addEventListener('click', e => {
  const btn = e.target.closest('.like-btn');
  if (!btn || btn.disabled) return;
  const idx = parseInt(btn.dataset.index, 10);
  if (likedChoices.has(idx)) return;
  likedChoices.add(idx);
  btn.disabled = true;
  btn.classList.add('liked');
  send('submit_like', { choice_index: idx });
});

function handleLikeUpdate(data) {
  const el = document.getElementById(`likes-${data.choice_index}`);
  if (el) el.textContent = data.likes;
}

// ── Scores ─────────────────────────────────────────────────────────────
function handleScores(data) {
  document.getElementById('scores-title').textContent =
    data.round_complete ? `After Round ${data.round_complete}` : 'Scores';
  const scores = data.scores || [];
  const listEl = document.getElementById('scores-list-p');
  listEl.innerHTML = '';
  scores.forEach((s, i) => {
    const div = document.createElement('div');
    div.className = 'score-row';
    const rankEl = document.createElement('span');
    rankEl.className = 'score-rank' + (i === 0 ? ' top' : '');
    rankEl.textContent = String(i + 1);
    const nameEl = document.createElement('span');
    nameEl.className = 'score-name';
    nameEl.textContent = s.name + (s.id === actualPid ? ' (you)' : '');
    const ptsEl = document.createElement('span');
    ptsEl.className = 'score-pts';
    ptsEl.textContent = s.score.toLocaleString();
    div.appendChild(rankEl);
    div.appendChild(nameEl);
    div.appendChild(ptsEl);
    listEl.appendChild(div);
  });
  show('scores-screen');
}

// ── Game Over ───────────────────────────────────────────────────────────
function handleGameOver(data) {
  const winners = data.winners || [];
  const isWinner = playerName && winners.includes(playerName);
  document.getElementById('go-title').textContent =
    isWinner ? '🏆 You win!' : (winners.length ? `${winners[0]} wins!` : 'Game Over');
  document.getElementById('go-sub').textContent =
    isWinner ? 'Congratulations!' : (winners.length > 1 ? `It's a tie between ${winners.join(' & ')}` : '');
  const cup = data.thumbs_cup;
  document.getElementById('go-thumbs').textContent =
    cup ? `👍 Thumbs Cup: ${cup}` : '';
  const scores = data.final_scores || [];
  const goScores = document.getElementById('go-scores');
  goScores.innerHTML = '';
  scores.forEach((s, i) => {
    const div = document.createElement('div');
    div.className = 'score-row';
    const rankEl = document.createElement('span');
    rankEl.className = 'score-rank' + (i === 0 ? ' top' : '');
    rankEl.textContent = String(i + 1);
    const nameEl = document.createElement('span');
    nameEl.className = 'score-name';
    nameEl.textContent = s.name + (s.id === actualPid ? ' (you)' : '');
    const ptsEl = document.createElement('span');
    ptsEl.className = 'score-pts';
    ptsEl.textContent = s.score.toLocaleString();
    div.appendChild(rankEl);
    div.appendChild(nameEl);
    div.appendChild(ptsEl);
    goScores.appendChild(div);
  });
  show('gameover-screen');
}

// ── Game state (reconnection) ──────────────────────────────────────────
function handleGameState(data) {
  if (!data.game || data.game !== 'bluff') return;
  const phase = data.phase;
  if (phase === 'lobby') return;
  if (phase === 'collecting_lies') {
    if (data.current_question) handleQuestion({
      prompt: data.current_question.prompt,
      category: data.current_question.category,
      round_num: data.round_num,
      question_num: data.current_question.question_num,
      total_questions: data.current_question.total_questions,
    });
    if (data.submitted_lie) showSubmitted();
  } else if (phase === 'voting') {
    if (data.choices) handleVoting({
      prompt: data.current_question?.prompt || '',
      category: data.current_question?.category || '',
      choices: data.choices,
    });
    ownChoiceIndex = data.own_choice_index ?? null;
    if (data.already_voted) {
      document.getElementById('vote-submitted').style.display = 'block';
      document.getElementById('vote-list').style.display = 'none';
    }
  } else if (phase === 'revealing' && data.reveal) {
    handleReveal(data.reveal);
    if (data.likes_given) data.likes_given.forEach(idx => likedChoices.add(idx));
  } else if (phase === 'scores') {
    handleScores(data);
  } else if (phase === 'game_over') {
    handleGameOver(data);
  }
}

// ── Error ──────────────────────────────────────────────────────────────
function handleError(data) {
  const msg = data.message || 'Something went wrong.';
  const lieErr = document.getElementById('lieError');
  if (document.getElementById('collecting-screen').classList.contains('active')) {
    showError(lieErr, msg);
    document.getElementById('collect-form').style.display = 'block';
    document.getElementById('collect-submitted').style.display = 'none';
    document.getElementById('submitLieBtn').disabled = false;
    document.getElementById('lieForMeBtn').disabled = false;
  } else {
    alert(msg);
  }
}
