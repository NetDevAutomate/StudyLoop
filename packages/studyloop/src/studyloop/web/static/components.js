/**
 * components.js — Alpine review engine + settings store + Pomodoro
 *
 * Provides reviewApp() which drives the flashcard and quiz review UI.
 * Used by both the Flashcards and Quizzes tabs (x-data="reviewApp('flashcards')")
 * and (x-data="reviewApp('quiz')").
 */

/* eslint-disable no-unused-vars */

/* ====================================================================
 * Pomodoro helpers
 * ==================================================================== */

const POMO_CIRCUMFERENCE = 2 * Math.PI * 18;

function _pomoNotify(title, body) {
  if ("Notification" in window && Notification.permission === "granted") {
    new Notification(title, { body, icon: "/icon-192.svg" });
  }
  try {
    const ctx = new AudioContext();
    [0, 200, 400].forEach((delay) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 880;
      gain.gain.value = 0.15;
      osc.start(ctx.currentTime + delay / 1000);
      osc.stop(ctx.currentTime + delay / 1000 + 0.12);
    });
  } catch {
    /* audio not available */
  }
}

/* ====================================================================
 * Alpine stores — settings + pomodoro (registered in alpine:init)
 * ==================================================================== */

document.addEventListener("alpine:init", () => {
  Alpine.store("settings", {
    voiceOn: localStorage.getItem("voice") === "true",
    dyslexic: localStorage.getItem("dyslexic") === "true",
    light: localStorage.getItem("theme") === "light",
    _preferredVoice: null,
    _voicesLoaded: false,

    init() {
      if (this.dyslexic) document.body.classList.add("dyslexic");
      if (this.light) document.body.classList.add("light");
      this.loadVoices();
      if (window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = () => this.loadVoices();
      }
    },

    toggleDyslexic() {
      this.dyslexic = !this.dyslexic;
      document.body.classList.toggle("dyslexic", this.dyslexic);
      localStorage.setItem("dyslexic", this.dyslexic);
    },

    toggleTheme() {
      this.light = !this.light;
      document.body.classList.toggle("light", this.light);
      localStorage.setItem("theme", this.light ? "light" : "dark");
    },

    toggleVoice() {
      this.voiceOn = !this.voiceOn;
      localStorage.setItem("voice", this.voiceOn);
      if (this.voiceOn) {
        this.speak("Voice enabled");
      } else {
        this.stopSpeaking();
      }
    },

    speak(text) {
      if (!this.voiceOn || !window.speechSynthesis || !text) return;
      this.speakNow(text);
    },

    speakNow(text) {
      if (!window.speechSynthesis || !text) return;
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 0.95;
      u.pitch = 1.0;
      if (this._preferredVoice) u.voice = this._preferredVoice;
      window.speechSynthesis.speak(u);
    },

    stopSpeaking() {
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    },

    loadVoices() {
      if (!window.speechSynthesis) return;
      const voices = window.speechSynthesis.getVoices();
      if (!voices.length) return;
      this._voicesLoaded = true;

      const english = voices.filter((v) => v.lang.startsWith("en"));
      const select = document.getElementById("voice-select");
      if (select) {
        select.innerHTML = "";
        english.forEach((v) => {
          const opt = document.createElement("option");
          opt.value = v.name;
          const label = v.name.replace(/Microsoft |Google |Apple /i, "");
          opt.textContent = v.localService ? label : `${label} (online)`;
          select.appendChild(opt);
        });
      }

      const saved = localStorage.getItem("voiceName");
      const savedVoice = saved && english.find((v) => v.name === saved);
      if (savedVoice) {
        this._preferredVoice = savedVoice;
        if (select) select.value = savedVoice.name;
      } else {
        this._preferredVoice =
          english.find((v) => /premium|enhanced|natural/i.test(v.name)) ||
          english.find((v) => /samantha|daniel|karen|moira|tessa|fiona/i.test(v.name)) ||
          english.find((v) => v.lang.startsWith("en-") && !v.name.includes("Google")) ||
          english[0] ||
          null;
        if (this._preferredVoice && select) select.value = this._preferredVoice.name;
      }
    },

    onVoiceChange(name) {
      const voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
      this._preferredVoice = voices.find((v) => v.name === name) || null;
      localStorage.setItem("voiceName", name);
      if (this.voiceOn) this.speakNow("Voice changed");
    },
  });

  Alpine.store("pomodoro", {
    STUDY: 25 * 60, BREAK: 5 * 60, LONG_BREAK: 15 * 60, CYCLES: 4,
    focusMin: 25, shortBreakMin: 5, longBreakMin: 15, cycles: 4,
    running: false, paused: false, visible: false, isBreak: false,
    remaining: 25 * 60, total: 25 * 60, sessions: 0, _interval: null, _loaded: false,

    get display() {
      const m = Math.floor(this.remaining / 60);
      const s = this.remaining % 60;
      return `${m}:${s.toString().padStart(2, "0")}`;
    },
    get label() {
      if (!this.running) return "Study";
      return this.isBreak
        ? (this.sessions > 0 && this.sessions % this.CYCLES === 0 ? "Long Break" : "Break")
        : "Study";
    },
    get arcOffset() { return POMO_CIRCUMFERENCE * (1 - (1 - this.remaining / this.total)); },
    get pauseIcon() { return this.paused ? "\u25b6" : "\u23f8\ufe0e"; },

    async loadConfig() {
      if (this._loaded) return;
      this._loaded = true;
      let defaults = { focus: 25, short_break: 5, long_break: 15, cycles: 4 };
      try { const res = await fetch("/api/settings/pomodoro"); if (res.ok) defaults = await res.json(); } catch {}
      this.focusMin = parseInt(localStorage.getItem("pomoFocus")) || defaults.focus;
      this.shortBreakMin = parseInt(localStorage.getItem("pomoShortBreak")) || defaults.short_break;
      this.longBreakMin = parseInt(localStorage.getItem("pomoLongBreak")) || defaults.long_break;
      this.cycles = parseInt(localStorage.getItem("pomoCycles")) || defaults.cycles;
      this._applyDurations();
    },
    _applyDurations() {
      this.STUDY = this.focusMin * 60; this.BREAK = this.shortBreakMin * 60;
      this.LONG_BREAK = this.longBreakMin * 60; this.CYCLES = this.cycles;
      if (!this.running) { this.remaining = this.STUDY; this.total = this.STUDY; }
    },
    saveDurations() {
      localStorage.setItem("pomoFocus", this.focusMin);
      localStorage.setItem("pomoShortBreak", this.shortBreakMin);
      localStorage.setItem("pomoLongBreak", this.longBreakMin);
      localStorage.setItem("pomoCycles", this.cycles);
      this._applyDurations();
    },
    toggle() { this.visible = !this.visible; },
    start() {
      this._applyDurations(); this.isBreak = false;
      this.remaining = this.STUDY; this.total = this.STUDY;
      this.running = true; this.paused = false; this.visible = true;
      this._startInterval();
      Alpine.store("settings").speak(`Pomodoro started. ${this.focusMin} minutes of focused study.`);
      if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    },
    togglePause() {
      if (this.paused) { this.paused = false; this._startInterval(); }
      else { this.paused = true; clearInterval(this._interval); }
    },
    stop() { this.running = false; this.paused = false; this.visible = false; clearInterval(this._interval); },
    _startInterval() { clearInterval(this._interval); this._tick(); this._interval = setInterval(() => this._tick(), 1000); },
    _tick() {
      if (this.paused) return;
      this.remaining--;
      if (this.remaining <= 0) {
        clearInterval(this._interval);
        if (this.isBreak) {
          Alpine.store("settings").speak("Break over! Time to study.");
          _pomoNotify("Break over!", "Time for another study session.");
          this.isBreak = false; this.remaining = this.STUDY; this.total = this.STUDY;
        } else {
          this.sessions++;
          const isLong = this.sessions % this.CYCLES === 0;
          const breakTime = isLong ? this.LONG_BREAK : this.BREAK;
          const breakMins = Math.round(breakTime / 60);
          Alpine.store("settings").speak(isLong ? `Great work! Take a ${breakMins} minute break.` : `Good session! Take a ${breakMins} minute break.`);
          _pomoNotify("Study session complete!", `Take a ${breakMins} minute break.`);
          this.isBreak = true; this.remaining = breakTime; this.total = breakTime;
        }
        this._interval = setInterval(() => this._tick(), 1000);
      }
    },
  });

  Alpine.store("pomodoro").loadConfig();
});

/**
 * Review application Alpine component.
 * @param {string} defaultMode - 'flashcards' or 'quiz'
 */
function reviewApp(defaultMode) {
  return {
    // Navigation state
    view: 'courses',       // 'courses' | 'config' | 'study' | 'summary'
    mode: defaultMode,

    // Course listing
    courses: [],
    liveSession: null,
    heatmapDays: [],
    history: [],

    // Config / session setup
    course: '',
    sources: [],
    selectedSource: 'all',
    cardLimit: 20,

    // Study state
    cards: [],
    index: 0,
    revealed: false,
    correct: 0,
    incorrect: 0,
    skipped: 0,
    sessionStartTime: null,
    isRetry: false,

    // Quiz state
    quizAnswered: false,
    quizSelectedIdx: -1,

    // Wrong-answer tracking for retry
    wrongHashes: [],

    get currentCard() {
      return this.cards[this.index] || null;
    },

    get progressPct() {
      return this.cards.length ? Math.round((this.index / this.cards.length) * 100) : 0;
    },

    get scoreText() {
      const answered = this.correct + this.incorrect;
      if (!answered) return '';
      return Math.round((this.correct / answered) * 100) + '%';
    },

    get retryTag() {
      return this.isRetry ? ' (retry)' : '';
    },

    get wrongCount() {
      return this.wrongHashes.length;
    },

    get summaryPct() {
      const answered = this.correct + this.incorrect;
      return answered ? Math.round((this.correct / answered) * 100) : 0;
    },

    get summaryCircumference() {
      return 2 * Math.PI * 58;  // r=58 from SVG
    },

    get summaryRingOffset() {
      const pct = this.summaryPct / 100;
      return this.summaryCircumference * (1 - pct);
    },

    get summaryGrade() {
      const pct = this.summaryPct;
      if (pct >= 90) return { text: 'Excellent!', cls: 'grade-a' };
      if (pct >= 70) return { text: 'Good work', cls: 'grade-b' };
      if (pct >= 50) return { text: 'Keep going', cls: 'grade-c' };
      return { text: 'Review again', cls: 'grade-d' };
    },

    get summaryDuration() {
      if (!this.sessionStartTime) return '';
      const secs = Math.floor((Date.now() - this.sessionStartTime) / 1000);
      const m = Math.floor(secs / 60);
      const s = secs % 60;
      return m + 'm ' + s + 's';
    },

    get correctQuizIdx() {
      if (!this.currentCard || this.currentCard.type !== 'quiz') return -1;
      return this.currentCard.options.findIndex(o => o.is_correct);
    },

    // ------------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------------

    async init() {
      await this._loadCourses();
      await this._loadLiveSession();
    },

    async _loadCourses() {
      try {
        const res = await fetch('/api/courses');
        if (res.ok) {
          this.courses = await res.json();
          await this._loadHistory();
          this._buildHeatmap();
        }
      } catch { /* courses unavailable */ }
    },

    async _loadLiveSession() {
      try {
        const res = await fetch('/api/session/state');
        if (res.ok) {
          const state = await res.json();
          if (state.study_session_id && state.mode !== 'ended') {
            this.liveSession = state;
          }
        }
      } catch { /* no live session */ }
    },

    async _loadHistory() {
      // Build history from course stats — review_sessions table
      const items = [];
      for (const c of this.courses) {
        try {
          const res = await fetch('/api/stats/' + encodeURIComponent(c.name));
          if (res.ok) {
            const stats = await res.json();
            if (stats.total_reviews > 0) {
              items.push({
                course: c.name,
                mode: this.mode,
                correct: stats.mastered || 0,
                total: stats.unique_cards || 0,
                date: '',
              });
            }
          }
        } catch { /* skip */ }
      }
      this.history = items;
    },

    _buildHeatmap() {
      // Simple 90-day heatmap placeholder — real implementation would
      // query per-day review counts from the API
      const days = [];
      const now = new Date();
      for (let i = 89; i >= 0; i--) {
        const d = new Date(now);
        d.setDate(d.getDate() - i);
        days.push({
          date: d.toISOString().slice(0, 10),
          count: 0,
          level: 'level-0',
        });
      }
      this.heatmapDays = days;
    },

    // ------------------------------------------------------------------
    // Navigation
    // ------------------------------------------------------------------

    goHome() {
      this.view = 'courses';
      this.cards = [];
      this.index = 0;
      this.revealed = false;
      this.correct = 0;
      this.incorrect = 0;
      this.skipped = 0;
      this.isRetry = false;
      this.wrongHashes = [];
      this._loadCourses();
    },

    async openConfig(course, mode) {
      this.course = course;
      this.mode = mode;
      this.selectedSource = 'all';
      this.view = 'config';

      try {
        const res = await fetch(
          '/api/sources/' + encodeURIComponent(course) + '?mode=' + mode
        );
        if (res.ok) this.sources = await res.json();
      } catch {
        this.sources = [];
      }
    },

    // ------------------------------------------------------------------
    // Session lifecycle
    // ------------------------------------------------------------------

    async startSession(source, limit) {
      try {
        const res = await fetch(
          '/api/cards/' + encodeURIComponent(this.course) + '?mode=' + this.mode
        );
        if (!res.ok) return;
        let cards = await res.json();

        // Filter by source
        if (source && source !== 'all') {
          cards = cards.filter(c => c.source === source);
        }

        // Shuffle
        for (let i = cards.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [cards[i], cards[j]] = [cards[j], cards[i]];
        }

        // Limit
        if (limit && limit > 0) {
          cards = cards.slice(0, limit);
        }

        if (!cards.length) return;

        this.cards = cards;
        this.index = 0;
        this.revealed = false;
        this.correct = 0;
        this.incorrect = 0;
        this.skipped = 0;
        this.wrongHashes = [];
        this.isRetry = false;
        this.sessionStartTime = Date.now();
        this.view = 'study';
      } catch { /* load failed */ }
    },

    restartSession() {
      this.startSession(this.selectedSource, this.cardLimit);
    },

    retryWrong() {
      if (!this.wrongHashes.length) return;
      const wrongSet = new Set(this.wrongHashes);
      const retryCards = this.cards.filter(c => wrongSet.has(c.hash));
      if (!retryCards.length) return;

      this.cards = retryCards;
      this.index = 0;
      this.revealed = false;
      this.correct = 0;
      this.incorrect = 0;
      this.skipped = 0;
      this.wrongHashes = [];
      this.isRetry = true;
      this.sessionStartTime = Date.now();
      this.view = 'study';
    },

    // ------------------------------------------------------------------
    // Card interaction
    // ------------------------------------------------------------------

    flipCard() {
      if (this.currentCard?.type === 'flashcard') {
        this.revealed = !this.revealed;
      }
    },

    async answerFlashcard(correct) {
      if (!this.currentCard) return;

      if (correct) {
        this.correct++;
      } else {
        this.incorrect++;
        this.wrongHashes.push(this.currentCard.hash);
      }

      // Record review to server
      this._recordReview(this.currentCard.hash, correct, 'flashcard');
      this._advance();
    },

    answerQuiz(idx) {
      if (this.quizAnswered || !this.currentCard) return;

      this.quizAnswered = true;
      this.quizSelectedIdx = idx;
      const isCorrect = this.currentCard.options[idx]?.is_correct || false;

      if (isCorrect) {
        this.correct++;
      } else {
        this.incorrect++;
        this.wrongHashes.push(this.currentCard.hash);
      }

      this._recordReview(this.currentCard.hash, isCorrect, 'quiz');

      // Auto-advance after delay
      setTimeout(() => this._advance(), 1500);
    },

    quizOptionClass(idx) {
      if (!this.quizAnswered) return '';
      const opt = this.currentCard?.options[idx];
      if (!opt) return '';
      if (opt.is_correct) return 'correct';
      if (idx === this.quizSelectedIdx && !opt.is_correct) return 'incorrect';
      return 'dimmed';
    },

    skipCard() {
      this.skipped++;
      this._advance();
    },

    _advance() {
      this.revealed = false;
      this.quizAnswered = false;
      this.quizSelectedIdx = -1;

      if (this.index + 1 < this.cards.length) {
        this.index++;
      } else {
        this.view = 'summary';
      }
    },

    async _recordReview(cardHash, correct, cardType) {
      try {
        await fetch('/api/review', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            course: this.course,
            card_hash: cardHash,
            correct: correct,
            card_type: cardType,
          }),
        });
      } catch { /* best effort */ }
    },

    // ------------------------------------------------------------------
    // TTS
    // ------------------------------------------------------------------

    speakCurrentCard() {
      if (!this.currentCard) return;
      const text = this.currentCard.type === 'flashcard'
        ? (this.revealed ? this.currentCard.back : this.currentCard.front)
        : this.currentCard.question;
      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
      }
    },

    // ------------------------------------------------------------------
    // Keyboard shortcuts
    // ------------------------------------------------------------------

    handleKey(event) {
      const key = event.key.toLowerCase();

      if (this.view === 'study') {
        if (this.currentCard?.type === 'flashcard') {
          if (key === ' ' || key === 'spacebar') { event.preventDefault(); this.flipCard(); }
          else if (key === 'y' && this.revealed) this.answerFlashcard(true);
          else if (key === 'n' && this.revealed) this.answerFlashcard(false);
          else if (key === 's') this.skipCard();
          else if (key === 't') this.speakCurrentCard();
          else if (key === 'escape') this.goHome();
        } else if (this.currentCard?.type === 'quiz') {
          if (['1', '2', '3', '4'].includes(key) && !this.quizAnswered) {
            this.answerQuiz(parseInt(key) - 1);
          }
          else if (key === 't') this.speakCurrentCard();
          else if (key === 'escape') this.goHome();
        }
      } else if (this.view === 'summary') {
        if (key === 'r' && this.wrongCount) this.retryWrong();
        else if (key === 'escape') this.goHome();
      } else if (this.view === 'courses') {
        // No global shortcuts on courses view
      }
    },
  };
}
