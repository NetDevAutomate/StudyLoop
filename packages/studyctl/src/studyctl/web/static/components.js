/**
 * components.js — Alpine review engine + settings store + Pomodoro
 *
 * Provides reviewApp() which drives the flashcard and quiz review UI.
 * Used by both the Flashcards and Quizzes tabs (x-data="reviewApp('flashcards')")
 * and (x-data="reviewApp('quiz')").
 */

/* eslint-disable no-unused-vars */

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
