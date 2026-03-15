/* Socratic Study Mentor — PWA flashcard & quiz review */

const $ = (sel) => document.querySelector(sel);
const app = $("#app");
const shortcuts = $("#shortcuts");

let state = {
  view: "courses",
  course: null,
  mode: null,
  cards: [],
  index: 0,
  correct: 0,
  incorrect: 0,
  skipped: 0,
  wrongHashes: new Set(),
  revealed: false,
  startTime: 0,
  cardStart: 0,
  isRetry: false,
  allCards: [],
};

/* --- Service Worker --- */
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

/* --- Dyslexic toggle --- */
const dyslexicBtn = $("#dyslexic-toggle");
if (localStorage.getItem("dyslexic") === "true") {
  document.body.classList.add("dyslexic");
  dyslexicBtn.classList.add("active");
}
dyslexicBtn.addEventListener("click", () => {
  document.body.classList.toggle("dyslexic");
  const on = document.body.classList.contains("dyslexic");
  dyslexicBtn.classList.toggle("active", on);
  localStorage.setItem("dyslexic", on);
});

/* --- API --- */
async function api(path, opts) {
  const r = await fetch(path, opts);
  return r.json();
}

/* --- Views --- */
async function showCourses() {
  state.view = "courses";
  state.isRetry = false;
  const courses = await api("/api/courses");

  if (courses.length === 0) {
    app.innerHTML = `
      <div style="text-align:center;color:var(--text-muted)">
        <h2 style="margin-bottom:12px">No courses found</h2>
        <p>Configure directories in ~/.config/studyctl/config.yaml:</p>
        <pre style="text-align:left;margin:16px auto;max-width:400px;background:var(--bg-card);padding:16px;border-radius:8px">review:
  directories:
    - ~/Desktop/ZTM-DE/downloads
    - ~/Desktop/Python/downloads</pre>
      </div>`;
    shortcuts.innerHTML = "";
    return;
  }

  app.innerHTML = `<div class="courses">${courses.map((c) => `
    <div class="course-card" data-course="${c.name}">
      <h2>${c.name}</h2>
      <div class="counts">
        <span>${c.flashcard_count} flashcards</span>
        <span>${c.quiz_count} quiz questions</span>
      </div>
      <div class="mode-buttons">
        ${c.flashcard_count ? `<button class="mode-btn flashcard" data-course="${c.name}" data-mode="flashcards">Flashcards</button>` : ""}
        ${c.quiz_count ? `<button class="mode-btn quiz" data-course="${c.name}" data-mode="quiz">Quiz</button>` : ""}
      </div>
    </div>`).join("")}</div>`;

  app.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      startSession(btn.dataset.course, btn.dataset.mode);
    });
  });

  shortcuts.innerHTML = "";
}

async function startSession(course, mode) {
  const cards = await api(`/api/cards/${encodeURIComponent(course)}?mode=${mode}`);
  if (!cards.length) return;

  // Shuffle
  for (let i = cards.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [cards[i], cards[j]] = [cards[j], cards[i]];
  }

  Object.assign(state, {
    view: "study",
    course,
    mode,
    cards,
    allCards: [...cards],
    index: 0,
    correct: 0,
    incorrect: 0,
    skipped: 0,
    wrongHashes: new Set(),
    revealed: false,
    startTime: Date.now(),
    cardStart: Date.now(),
    isRetry: false,
  });

  showCard();
}

function showCard() {
  if (state.index >= state.cards.length) {
    showSummary();
    return;
  }

  const card = state.cards[state.index];
  const total = state.cards.length;
  const pct = ((state.index / total) * 100).toFixed(0);
  const retryTag = state.isRetry ? " (Retry)" : "";
  state.revealed = false;
  state.cardStart = Date.now();

  if (card.type === "flashcard") {
    app.innerHTML = `
      <div class="study-view">
        <div class="progress-bar">
          <span>${state.index + 1}/${total}${retryTag}</span>
          <div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
          <span>${scoreText()}</span>
        </div>
        <div class="card" id="card">
          <div class="card-label">Question</div>
          <div class="card-content">${escHtml(card.front)}</div>
          <div class="card-hint">Tap or press Space to reveal</div>
        </div>
        <div class="actions" id="actions" style="display:none">
          <button class="action-btn btn-correct" onclick="answer(true)">I knew it</button>
          <button class="action-btn btn-incorrect" onclick="answer(false)">Didn't know</button>
          <button class="action-btn btn-skip" onclick="skip()">Skip</button>
        </div>
      </div>`;

    $("#card").addEventListener("click", flipCard);
  } else {
    app.innerHTML = `
      <div class="study-view">
        <div class="progress-bar">
          <span>${state.index + 1}/${total}${retryTag}</span>
          <div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
          <span>${scoreText()}</span>
        </div>
        <div class="card" id="card">
          <div class="card-label">Question</div>
          <div class="card-content">${escHtml(card.question)}</div>
          ${card.hint ? `<div class="card-hint">Hint: ${escHtml(card.hint)}</div>` : ""}
          <div class="quiz-options" id="quiz-options">
            ${card.options.map((o, i) => `
              <button class="quiz-option" data-idx="${i}">
                <span class="option-letter">${"ABCDEFGHIJ"[i]}</span>
                <span>${escHtml(o.text)}</span>
              </button>`).join("")}
          </div>
        </div>
      </div>`;

    app.querySelectorAll(".quiz-option").forEach((btn) => {
      btn.addEventListener("click", () => answerQuiz(parseInt(btn.dataset.idx)));
    });
  }

  updateShortcuts("study");
}

function flipCard() {
  if (state.revealed) return;
  state.revealed = true;

  const card = state.cards[state.index];
  const cardEl = $("#card");
  cardEl.classList.add("revealed");
  cardEl.querySelector(".card-label").textContent = "Answer";
  cardEl.querySelector(".card-content").innerHTML = escHtml(card.back);
  cardEl.querySelector(".card-hint").style.display = "none";
  $("#actions").style.display = "flex";
}

function answerQuiz(idx) {
  const card = state.cards[state.index];
  const buttons = app.querySelectorAll(".quiz-option");
  const correctIdx = card.options.findIndex((o) => o.is_correct);
  const isCorrect = idx === correctIdx;

  buttons.forEach((btn, i) => {
    btn.style.pointerEvents = "none";
    if (i === correctIdx) btn.classList.add("correct");
    if (i === idx && !isCorrect) btn.classList.add("incorrect");
  });

  // Show rationale
  const correctOpt = card.options[correctIdx];
  if (correctOpt.rationale) {
    const r = document.createElement("div");
    r.className = "rationale";
    r.textContent = correctOpt.rationale;
    $("#quiz-options").after(r);
  }

  recordAnswer(isCorrect);

  setTimeout(() => {
    state.index++;
    showCard();
  }, isCorrect ? 1200 : 2500);
}

function answer(correct) {
  recordAnswer(correct);
  state.index++;
  showCard();
}

function skip() {
  state.skipped++;
  state.index++;
  showCard();
}

function recordAnswer(correct) {
  const card = state.cards[state.index];
  const elapsed = Date.now() - state.cardStart;

  if (correct) {
    state.correct++;
  } else {
    state.incorrect++;
    state.wrongHashes.add(card.hash);
  }

  // Record to SM-2 (skip during retry)
  if (!state.isRetry) {
    api("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        course: state.course,
        card_type: card.type,
        card_hash: card.hash,
        correct,
        response_time_ms: elapsed,
      }),
    }).catch(() => {});
  }
}

function showSummary() {
  state.view = "summary";
  const attempted = state.correct + state.incorrect;
  const pct = attempted > 0 ? Math.round((state.correct / attempted) * 100) : 0;
  const duration = Math.round((Date.now() - state.startTime) / 1000);
  const mins = Math.floor(duration / 60);
  const secs = duration % 60;
  const wrongCount = state.wrongHashes.size;

  let grade, gradeClass;
  if (pct >= 80) { grade = "Excellent!"; gradeClass = "excellent"; }
  else if (pct >= 60) { grade = "Good progress"; gradeClass = "good"; }
  else { grade = "Keep reviewing"; gradeClass = "review"; }

  const circumference = 2 * Math.PI * 58;
  const offset = circumference - (pct / 100) * circumference;

  // Record session
  if (!state.isRetry) {
    api("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        course: state.course,
        mode: state.mode,
        total: state.cards.length,
        correct: state.correct,
        duration_seconds: duration,
      }),
    }).catch(() => {});
  }

  app.innerHTML = `
    <div class="summary">
      <div class="score-ring">
        <svg width="140" height="140" viewBox="0 0 140 140">
          <circle class="track" cx="70" cy="70" r="58"/>
          <circle class="fill ${gradeClass}" cx="70" cy="70" r="58"
            stroke-dasharray="${circumference}"
            stroke-dashoffset="${offset}"/>
        </svg>
        <div class="score-text">${pct}%</div>
      </div>
      <h2>Session Complete</h2>
      <div class="grade ${gradeClass}">${grade}</div>
      <div class="summary-stats">
        <span>${state.correct} correct</span>
        <span>${state.incorrect} wrong</span>
        <span>${state.skipped} skipped</span>
        <span>${mins}m ${secs}s</span>
      </div>
      <div class="summary-actions">
        ${wrongCount && !state.isRetry ? `<button class="summary-btn btn-retry" onclick="retryWrong()">Retry ${wrongCount} wrong</button>` : ""}
        <button class="summary-btn btn-back" onclick="showCourses()">Back to courses</button>
      </div>
    </div>`;

  updateShortcuts("summary");
}

function retryWrong() {
  const wrong = state.wrongHashes;
  const retryCards = state.allCards.filter((c) => wrong.has(c.hash));
  if (!retryCards.length) return;

  Object.assign(state, {
    cards: retryCards,
    index: 0,
    correct: 0,
    incorrect: 0,
    skipped: 0,
    wrongHashes: new Set(),
    revealed: false,
    startTime: Date.now(),
    isRetry: true,
  });

  showCard();
}

function scoreText() {
  const attempted = state.correct + state.incorrect;
  if (!attempted) return "";
  return `${Math.round((state.correct / attempted) * 100)}%`;
}

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function updateShortcuts(view) {
  if (view === "study") {
    shortcuts.innerHTML = `
      <span><kbd>Space</kbd> Flip</span>
      <span><kbd>Y</kbd> Correct</span>
      <span><kbd>N</kbd> Incorrect</span>
      <span><kbd>S</kbd> Skip</span>`;
  } else if (view === "summary") {
    shortcuts.innerHTML = `
      <span><kbd>R</kbd> Retry</span>
      <span><kbd>Esc</kbd> Back</span>`;
  } else {
    shortcuts.innerHTML = "";
  }
}

/* --- Keyboard shortcuts --- */
document.addEventListener("keydown", (e) => {
  if (state.view === "study") {
    const card = state.cards[state.index];
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      if (card.type === "flashcard" && !state.revealed) flipCard();
    }
    if (state.revealed && card.type === "flashcard") {
      if (e.key === "y" || e.key === "Y") answer(true);
      if (e.key === "n" || e.key === "N") answer(false);
    }
    if (e.key === "s" || e.key === "S") skip();
    if (card.type === "quiz") {
      const num = parseInt(e.key);
      if (num >= 1 && num <= card.options.length) answerQuiz(num - 1);
      if (e.key >= "a" && e.key <= "j") {
        const idx = e.key.charCodeAt(0) - 97;
        if (idx < card.options.length) answerQuiz(idx);
      }
    }
  }

  if (state.view === "summary") {
    if (e.key === "r" || e.key === "R") retryWrong();
    if (e.key === "Escape") showCourses();
  }

  if (state.view === "courses" && e.key === "Escape") showCourses();
});

/* --- Init --- */
showCourses();
