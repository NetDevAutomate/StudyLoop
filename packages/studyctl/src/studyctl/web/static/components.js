/**
 * Socratic Study Mentor — Alpine.js components
 *
 * Replaces app.js with declarative Alpine components:
 * - reviewApp(defaultMode)  — course grid → config → card player → summary
 * - Alpine.store('settings') — voice, theme, dyslexic (shared)
 * - Pomodoro timer functions (global, called by header buttons)
 * - Keyboard shortcuts via @keydown.window on body
 */

/* ====================================================================
 * Helpers (pure, no Alpine dependency)
 * ==================================================================== */

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function escAttr(s) {
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

function shuffleArray(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function buildHeatmapData(history) {
  if (!history.length) return [];
  const counts = {};
  history.forEach((h) => {
    if (h.date) counts[h.date] = (counts[h.date] || 0) + 1;
  });

  const days = [];
  const today = new Date();
  for (let i = 89; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    const n = counts[key] || 0;
    const level = n === 0 ? "" : n === 1 ? "l1" : n <= 3 ? "l2" : n <= 5 ? "l3" : "l4";
    days.push({ date: key, count: n, level });
  }
  return days;
}

/* ====================================================================
 * Alpine stores — registered in alpine:init
 * ==================================================================== */

document.addEventListener("alpine:init", () => {
  /* ----------------------------------------------------------------
   * Settings store — voice, theme, dyslexic
   * ---------------------------------------------------------------- */
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
});

/* ====================================================================
 * reviewApp — main flashcard/quiz review component
 * ==================================================================== */

function reviewApp(defaultMode) {
  return {
    /* --- View state --- */
    view: "courses", // courses | config | study | summary
    defaultMode: defaultMode,

    /* --- Course data --- */
    courses: [],
    history: [],
    heatmapDays: [],
    liveSession: null,

    /* --- Session config --- */
    sources: [],
    selectedSource: "all",
    cardLimit: 20,

    /* --- Active session --- */
    course: null,
    mode: null,
    cards: [],
    allCards: [],
    index: 0,
    correct: 0,
    incorrect: 0,
    skipped: 0,
    wrongHashes: [],
    revealed: false,
    startTime: 0,
    cardStart: 0,
    isRetry: false,
    quizAnswered: false,
    quizSelectedIdx: -1,

    /* --- Computed --- */
    get currentCard() {
      return this.cards[this.index] || null;
    },
    get isDone() {
      return this.index >= this.cards.length;
    },
    get progressPct() {
      return this.cards.length ? Math.round((this.index / this.cards.length) * 100) : 0;
    },
    get scoreText() {
      const attempted = this.correct + this.incorrect;
      return attempted ? `${Math.round((this.correct / attempted) * 100)}%` : "";
    },
    get summaryPct() {
      const attempted = this.correct + this.incorrect;
      return attempted > 0 ? Math.round((this.correct / attempted) * 100) : 0;
    },
    get summaryGrade() {
      const p = this.summaryPct;
      if (p >= 80) return { text: "Excellent!", cls: "excellent" };
      if (p >= 60) return { text: "Good progress", cls: "good" };
      return { text: "Keep reviewing", cls: "review" };
    },
    get summaryDuration() {
      const s = Math.round((Date.now() - this.startTime) / 1000);
      return `${Math.floor(s / 60)}m ${s % 60}s`;
    },
    get summaryRingOffset() {
      const circ = 2 * Math.PI * 58;
      return circ - (this.summaryPct / 100) * circ;
    },
    get summaryCircumference() {
      return 2 * Math.PI * 58;
    },
    get wrongCount() {
      return this.wrongHashes.length;
    },
    get correctQuizIdx() {
      return this.currentCard?.options?.findIndex((o) => o.is_correct) ?? -1;
    },
    get retryTag() {
      return this.isRetry ? " (Retry)" : "";
    },

    /* --- Init --- */
    async init() {
      await this.loadCourses();
    },

    /* --- Navigation --- */
    goHome() {
      this.view = "courses";
      this.isRetry = false;
      Alpine.store("settings").stopSpeaking();
      this.loadCourses();
    },

    /* --- Course grid --- */
    async loadCourses() {
      try {
        const [courses, history, sessionState] = await Promise.all([
          fetch("/api/courses").then((r) => r.json()),
          fetch("/api/history").then((r) => r.json()),
          fetch("/api/session/state")
            .then((r) => r.json())
            .catch(() => ({})),
        ]);
        this.courses = courses;
        this.history = history;
        this.heatmapDays = buildHeatmapData(history);
        this.liveSession = sessionState.study_session_id ? sessionState : null;
      } catch {
        this.courses = [];
      }
    },

    /* --- Session config --- */
    async openConfig(courseName, mode) {
      this.course = courseName;
      this.mode = mode || this.defaultMode;
      try {
        this.sources = await fetch(
          `/api/sources/${encodeURIComponent(courseName)}?mode=${this.mode}`
        ).then((r) => r.json());
      } catch {
        this.sources = [];
      }

      if (this.sources.length <= 1) {
        this.startSession("all", 0);
        return;
      }
      this.selectedSource = "all";
      this.cardLimit = 20;
      this.view = "config";
    },

    /* --- Start session --- */
    async startSession(source, limit) {
      let cards;
      try {
        cards = await fetch(
          `/api/cards/${encodeURIComponent(this.course)}?mode=${this.mode}`
        ).then((r) => r.json());
      } catch {
        return;
      }
      if (!cards.length) return;

      if (source && source !== "all") {
        cards = cards.filter((c) => c.source === source);
      }
      shuffleArray(cards);
      if (limit > 0 && cards.length > limit) {
        cards = cards.slice(0, limit);
      }
      if (!cards.length) return;

      this.cards = cards;
      this.allCards = [...cards];
      this.index = 0;
      this.correct = 0;
      this.incorrect = 0;
      this.skipped = 0;
      this.wrongHashes = [];
      this.revealed = false;
      this.startTime = Date.now();
      this.cardStart = Date.now();
      this.isRetry = false;
      this.quizAnswered = false;
      this.quizSelectedIdx = -1;
      this.view = "study";

      const card = this.currentCard;
      if (card) {
        Alpine.store("settings").speak(
          card.type === "flashcard" ? card.front : card.question
        );
      }
    },

    /* --- Card actions --- */
    flipCard() {
      if (this.revealed || !this.currentCard) return;
      this.revealed = true;
      Alpine.store("settings").speak(this.currentCard.back);
    },

    answerFlashcard(correct) {
      this.recordAnswer(correct);
      this.nextCard();
    },

    answerQuiz(idx) {
      if (this.quizAnswered) return;
      this.quizAnswered = true;
      this.quizSelectedIdx = idx;
      const isCorrect = idx === this.correctQuizIdx;
      this.recordAnswer(isCorrect);

      const card = this.currentCard;
      const correctOpt = card.options[this.correctQuizIdx];
      if (correctOpt.rationale) {
        Alpine.store("settings").speak(
          isCorrect
            ? "Correct! " + correctOpt.rationale
            : "Incorrect. The answer is: " + correctOpt.text + ". " + correctOpt.rationale
        );
      } else {
        Alpine.store("settings").speak(
          isCorrect ? "Correct!" : "Incorrect. The answer is: " + correctOpt.text
        );
      }

      setTimeout(() => this.nextCard(), isCorrect ? 1500 : 3000);
    },

    skipCard() {
      this.skipped++;
      Alpine.store("settings").stopSpeaking();
      this.nextCard();
    },

    nextCard() {
      this.index++;
      this.revealed = false;
      this.quizAnswered = false;
      this.quizSelectedIdx = -1;
      this.cardStart = Date.now();

      if (this.isDone) {
        this.finishSession();
        return;
      }

      const card = this.currentCard;
      if (card) {
        Alpine.store("settings").speak(
          card.type === "flashcard" ? card.front : card.question
        );
      }
    },

    recordAnswer(correct) {
      const card = this.currentCard;
      const elapsed = Date.now() - this.cardStart;

      if (correct) {
        this.correct++;
      } else {
        this.incorrect++;
        if (!this.wrongHashes.includes(card.hash)) {
          this.wrongHashes.push(card.hash);
        }
      }

      if (!this.isRetry) {
        fetch("/api/review", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            course: this.course,
            card_type: card.type,
            card_hash: card.hash,
            correct,
            response_time_ms: elapsed,
          }),
        }).catch(() => {});
      }
    },

    /* --- Summary --- */
    finishSession() {
      this.view = "summary";
      Alpine.store("settings").stopSpeaking();

      if (!this.isRetry) {
        const duration = Math.round((Date.now() - this.startTime) / 1000);
        fetch("/api/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            course: this.course,
            mode: this.mode,
            total: this.cards.length,
            correct: this.correct,
            duration_seconds: duration,
          }),
        }).catch(() => {});
      }

      Alpine.store("settings").speak(
        `Session complete. You scored ${this.summaryPct} percent. ${this.correct} correct, ${this.incorrect} wrong.`
      );
    },

    retryWrong() {
      const wrong = this.allCards.filter((c) => this.wrongHashes.includes(c.hash));
      if (!wrong.length) return;
      this.cards = wrong;
      this.index = 0;
      this.correct = 0;
      this.incorrect = 0;
      this.skipped = 0;
      this.wrongHashes = [];
      this.revealed = false;
      this.startTime = Date.now();
      this.cardStart = Date.now();
      this.isRetry = true;
      this.quizAnswered = false;
      this.quizSelectedIdx = -1;
      this.view = "study";

      const card = this.currentCard;
      if (card) {
        Alpine.store("settings").speak(
          card.type === "flashcard" ? card.front : card.question
        );
      }
    },

    restartSession() {
      Alpine.store("settings").stopSpeaking();
      this.openConfig(this.course, this.mode);
    },

    speakCurrentCard() {
      const card = this.currentCard;
      if (!card) return;
      if (card.type === "flashcard") {
        Alpine.store("settings").speakNow(this.revealed ? card.back : card.front);
      } else {
        Alpine.store("settings").speakNow(this.quizAnswered ? "" : card.question);
      }
    },

    /* --- Quiz option styling --- */
    quizOptionClass(idx) {
      if (!this.quizAnswered) return "";
      if (idx === this.correctQuizIdx) return "correct";
      if (idx === this.quizSelectedIdx && idx !== this.correctQuizIdx) return "incorrect";
      return "";
    },

    /* --- Keyboard handler (called from body @keydown.window) --- */
    handleKey(e) {
      if (this.view === "study" && this.currentCard) {
        const card = this.currentCard;
        if ((e.key === " " || e.key === "Enter") && card.type === "flashcard" && !this.revealed) {
          e.preventDefault();
          this.flipCard();
        }
        if (this.revealed && card.type === "flashcard") {
          if (e.key === "y" || e.key === "Y") this.answerFlashcard(true);
          if (e.key === "n" || e.key === "N") this.answerFlashcard(false);
        }
        if (e.key === "s" || e.key === "S") this.skipCard();
        if (e.key === "t" || e.key === "T") this.speakCurrentCard();
        if (e.key === "Escape") this.goHome();
        if (card.type === "quiz" && !this.quizAnswered) {
          const num = parseInt(e.key);
          if (num >= 1 && num <= card.options.length) this.answerQuiz(num - 1);
          if (e.key >= "a" && e.key <= "d") {
            const idx = e.key.charCodeAt(0) - 97;
            if (idx < card.options.length) this.answerQuiz(idx);
          }
        }
      }
      if (this.view === "summary") {
        if (e.key === "r" || e.key === "R") this.retryWrong();
        if (e.key === "Escape") this.goHome();
      }
    },
  };
}

/* ====================================================================
 * Pomodoro Timer (global functions — Phase 3 will Alpine-ify)
 * ==================================================================== */

const pomo = {
  STUDY: 25 * 60,
  BREAK: 5 * 60,
  LONG_BREAK: 15 * 60,
  running: false,
  paused: false,
  isBreak: false,
  remaining: 25 * 60,
  total: 25 * 60,
  interval: null,
  sessions: 0,
};

const POMO_CIRCUMFERENCE = 2 * Math.PI * 18;

function pomoStart() {
  const el = document.getElementById("pomodoro");
  const toggle = document.getElementById("pomo-toggle");
  if (pomo.running) {
    el.classList.toggle("hidden");
    return;
  }
  pomo.isBreak = false;
  pomo.remaining = pomo.STUDY;
  pomo.total = pomo.STUDY;
  pomo.running = true;
  pomo.paused = false;
  el.classList.remove("hidden", "break");
  toggle.classList.add("active");
  document.getElementById("pomo-label").textContent = "Study";
  document.getElementById("pomo-pause").innerHTML = "&#10074;&#10074;";
  pomoTick();
  pomo.interval = setInterval(pomoTick, 1000);
  Alpine.store("settings").speak("Pomodoro started. 25 minutes of focused study.");
}

function pomoPauseToggle() {
  if (pomo.paused) {
    pomo.paused = false;
    document.getElementById("pomo-pause").innerHTML = "&#10074;&#10074;";
    pomo.interval = setInterval(pomoTick, 1000);
  } else {
    pomo.paused = true;
    clearInterval(pomo.interval);
    document.getElementById("pomo-pause").innerHTML = "&#9654;";
  }
}

function pomoStop() {
  pomo.running = false;
  pomo.paused = false;
  clearInterval(pomo.interval);
  document.getElementById("pomodoro").classList.add("hidden");
  document.getElementById("pomo-toggle").classList.remove("active");
}

function pomoTick() {
  pomo.remaining--;
  if (pomo.remaining <= 0) {
    clearInterval(pomo.interval);
    const label = document.getElementById("pomo-label");
    const el = document.getElementById("pomodoro");
    if (pomo.isBreak) {
      Alpine.store("settings").speak("Break over! Time to study.");
      pomoNotify("Break over!", "Time for another study session.");
      pomo.isBreak = false;
      pomo.remaining = pomo.STUDY;
      pomo.total = pomo.STUDY;
      el.classList.remove("break");
      label.textContent = "Study";
    } else {
      pomo.sessions++;
      const isLong = pomo.sessions % 4 === 0;
      const breakTime = isLong ? pomo.LONG_BREAK : pomo.BREAK;
      Alpine.store("settings").speak(
        isLong ? "Great work! Take a 15 minute break." : "Good session! Take a 5 minute break."
      );
      pomoNotify(
        "Study session complete!",
        isLong ? "Take a 15 minute break." : "Take a 5 minute break."
      );
      pomo.isBreak = true;
      pomo.remaining = breakTime;
      pomo.total = breakTime;
      el.classList.add("break");
      label.textContent = isLong ? "Long Break" : "Break";
    }
    pomo.interval = setInterval(pomoTick, 1000);
  }
  pomoRender();
}

function pomoRender() {
  const mins = Math.floor(pomo.remaining / 60);
  const secs = pomo.remaining % 60;
  document.getElementById("pomo-time").textContent = `${mins}:${secs.toString().padStart(2, "0")}`;
  const progress = 1 - pomo.remaining / pomo.total;
  document
    .getElementById("pomo-arc")
    .setAttribute("stroke-dashoffset", (POMO_CIRCUMFERENCE * (1 - progress)).toString());
}

function pomoNotify(title, body) {
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
 * Service Worker registration
 * ==================================================================== */

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
