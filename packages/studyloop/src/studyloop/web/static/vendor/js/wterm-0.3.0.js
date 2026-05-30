// wterm v0.3.0 — IIFE bundle for StudyLoop --dev mode
// Source: https://github.com/vercel-labs/wterm  tag v0.3.0 (commit: npm @wterm/dom@0.3.0 + @wterm/core@0.3.0)
// License: Apache-2.0
// Bundled offline with: npx esbuild@0.28.0 entry.js --bundle --format=iife --global-name=WtermLib
// WASM (~12 KB) is inlined as base64 in this bundle — no external fetches at runtime.
// Exposes: WtermLib.WTerm, WtermLib.WebSocketTransport, WtermLib.WasmBridge

var WtermLib = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // entry.js
  var entry_exports = {};
  __export(entry_exports, {
    WTerm: () => WTerm,
    WasmBridge: () => WasmBridge,
    WebSocketTransport: () => WebSocketTransport
  });

  // node_modules/@wterm/core/dist/wasm-inline.js
  var WASM_BASE64 = "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CyAAQQFxDQEQpoCAgAAMAgsPCxClgICAAAsgAUECaiEBDAALC+sBAQJ/I4CAgIAAQRBrIgIkgICAgABBACEDIAJBADoACyACIAE6AAkgAiAAOgAIIAJCADcDACACQQAtAMSAwIAAIgE6AAogAUEEIAFBBEkbQQF0IQECQANAIAEgA0YNASACIANqIANBoIDAgABqLwEAOwEAIANBAmohAwwACwtBAC0A2ozwgABBDGwiA0H8hvCAAGogAkEIaigCADYCACADIAIpAwA3AvSG8IAAQQBBACgC5ITAgABBAWoiA0F/IAMbNgLkhMCAAEEAQQAtANqM8IAAQQFqQR9xOgDajPCAACACQRBqJICAgIAAC3gBAn8CQCAAQf//A3EiAkEALwHqhPCAAE8NACACQYAYbEHohMCAAGohAEEAIQMCQANAIANBAC8B6ITwgABPDQEgACABKQIANwIAIABBCGogAUEIaigCADYCACAAQQxqIQAgA0EBaiEDDAALCyACQQE6AOyE8IAACwujAQEBfwJAIABB//8DcSIEQQAvAeqE8IAATw0AQQAgAkH//wNxIgBBAC8B6ITwgAAiAiAAIAJJGyIAIAFB//8DcSIBayICIAIgAEsbIQIgBEGAGGwgAUEMbGpB6ITAgABqIQACQANAIAJFDQEgACADKQIANwIAIABBCGogA0EIaigCADYCACAAQQxqIQAgAkF/aiECDAALCyAEQQE6AOyE8IAACwvhAQEEfwJAIAJB//8DcUUNACABQf//A3EgAEH//wNxTQ0AIAEgAGsiBCACQf//A3EiAiAEQf//A3EiBCACIARJGyIFa0H//wNxIQZBACECA0ACQCAGIAJHDQAgBSAAakH//wNxIQIDQCAAQf//A3EgAk8NAyAAIAMQnYCAgAAgAEEBaiEADAALCyABIAJBf3NqIgdB//8DcSEEAkBBgBhFDQAgBEGAGGxB6ITAgABqIAcgBWtB//8DcUGAGGxB6ITAgABqQYAY/AoAAAsgBEEBOgDshPCAACACQQFqIQIMAAsLC9gBAQN/AkAgAkH//wNxRQ0AIAFB//8DcSAAQf//A3FNDQAgAkH//wNxIgIgASAAa0H//wNxIgQgAiAESRsiBEGAGGxB6ITAgABqIQUgAUH//wNxIQYgAEH//wNxIgBBgBhsIQIDQAJAIAQgAGogBkkN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";

  // node_modules/@wterm/core/dist/wasm-bridge.js
  function decodeBase64(base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++)
      bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
  }
  var WasmBridge = class _WasmBridge {
    constructor(instance) {
      this.gridPtr = 0;
      this.dirtyPtr = 0;
      this.writeBufferPtr = 0;
      this.cellSize = 12;
      this.maxCols = 256;
      this.encoder = new TextEncoder();
      this.decoder = new TextDecoder();
      this.exports = instance.exports;
      this.memory = this.exports.memory;
    }
    static async load(url) {
      let bytes;
      if (url) {
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`[wterm] Failed to load WASM from ${url}: ${response.status} ${response.statusText}`);
        }
        bytes = await response.arrayBuffer();
      } else {
        bytes = decodeBase64(WASM_BASE64);
      }
      const { instance } = await WebAssembly.instantiate(bytes);
      return new _WasmBridge(instance);
    }
    init(cols, rows) {
      this.exports.init(cols, rows);
      this._updatePointers();
    }
    _updatePointers() {
      this.gridPtr = this.exports.getGridPtr();
      this.dirtyPtr = this.exports.getDirtyPtr();
      this.writeBufferPtr = this.exports.getWriteBuffer();
      this.cellSize = this.exports.getCellSize();
      this.maxCols = this.exports.getMaxCols();
      this._dv = new DataView(this.memory.buffer);
    }
    writeString(str) {
      const encoded = this.encoder.encode(str);
      this.writeRaw(encoded);
    }
    writeRaw(data) {
      const buf = new Uint8Array(this.memory.buffer, this.writeBufferPtr, 8192);
      let offset = 0;
      while (offset < data.length) {
        const chunk = Math.min(data.length - offset, 8192);
        buf.set(data.subarray(offset, offset + chunk));
        this.exports.writeBytes(chunk);
        offset += chunk;
      }
    }
    getCell(row, col) {
      const offset = this.gridPtr + (row * this.maxCols + col) * this.cellSize;
      const dv = this._dv;
      return {
        char: dv.getUint32(offset, true),
        fg: dv.getUint16(offset + 4, true),
        bg: dv.getUint16(offset + 6, true),
        flags: dv.getUint8(offset + 8)
      };
    }
    isDirtyRow(row) {
      return new Uint8Array(this.memory.buffer, this.dirtyPtr, 256)[row] !== 0;
    }
    clearDirty() {
      this.exports.clearDirty();
    }
    getCursor() {
      return {
        row: this.exports.getCursorRow(),
        col: this.exports.getCursorCol(),
        visible: this.exports.getCursorVisible() !== 0
      };
    }
    getCols() {
      return this.exports.getCols();
    }
    getRows() {
      return this.exports.getRows();
    }
    cursorKeysApp() {
      return this.exports.getCursorKeysApp() !== 0;
    }
    bracketedPaste() {
      return this.exports.getBracketedPaste() !== 0;
    }
    usingAltScreen() {
      return this.exports.getUsingAltScreen() !== 0;
    }
    getTitle() {
      if (this.exports.getTitleChanged() === 0)
        return null;
      const ptr = this.exports.getTitlePtr();
      const len = this.exports.getTitleLen();
      const bytes = new Uint8Array(this.memory.buffer, ptr, len);
      return this.decoder.decode(bytes);
    }
    getResponse() {
      const len = this.exports.getResponseLen();
      if (len === 0)
        return null;
      const ptr = this.exports.getResponsePtr();
      const bytes = new Uint8Array(this.memory.buffer, ptr, len);
      const str = this.decoder.decode(bytes);
      this.exports.clearResponse();
      return str;
    }
    getScrollbackCount() {
      return this.exports.getScrollbackCount();
    }
    getScrollbackCell(offset, col) {
      const ptr = this.exports.getScrollbackLine(offset);
      const off = ptr + col * this.cellSize;
      const dv = this._dv;
      return {
        char: dv.getUint32(off, true),
        fg: dv.getUint16(off + 4, true),
        bg: dv.getUint16(off + 6, true),
        flags: dv.getUint8(off + 8)
      };
    }
    getScrollbackLineLen(offset) {
      return this.exports.getScrollbackLineLen(offset);
    }
    getUnhandledSequences() {
      const count = this.exports.getDebugLogCount();
      if (count === 0)
        return [];
      const ptr = this.exports.getDebugLogPtr();
      const entrySize = this.exports.getDebugLogEntrySize();
      const maxEntries = this.exports.getDebugLogMax();
      const total = Math.min(count, maxEntries);
      const dv = new DataView(this.memory.buffer);
      const entries = [];
      const startIdx = count >= maxEntries ? count % maxEntries : 0;
      for (let i = 0; i < total; i++) {
        const idx = (startIdx + i) % maxEntries;
        const off = ptr + idx * entrySize;
        const finalByte = dv.getUint8(off);
        if (finalByte === 0)
          continue;
        const privateByte = dv.getUint8(off + 1);
        const paramCount = dv.getUint8(off + 2);
        const params = [];
        for (let p = 0; p < Math.min(paramCount, 4); p++) {
          params.push(dv.getUint16(off + 4 + p * 2, true));
        }
        entries.push({
          final: String.fromCharCode(finalByte),
          private: privateByte ? String.fromCharCode(privateByte) : "",
          paramCount,
          params
        });
      }
      return entries;
    }
    resize(cols, rows) {
      this.exports.resizeTerminal(cols, rows);
      this._updatePointers();
    }
  };

  // node_modules/@wterm/core/dist/transport.js
  var WebSocketTransport = class {
    constructor(options = {}) {
      this._ws = null;
      this._reconnectTimer = null;
      this._reconnectDelay = 1e3;
      this._closed = false;
      this._buffer = [];
      this.url = options.url ?? null;
      this.reconnect = options.reconnect !== false;
      this.maxReconnectDelay = options.maxReconnectDelay ?? 3e4;
      this.onData = options.onData ?? null;
      this.onOpen = options.onOpen ?? null;
      this.onClose = options.onClose ?? null;
      this.onError = options.onError ?? null;
    }
    connect(url) {
      if (url)
        this.url = url;
      if (!this.url)
        throw new Error("No WebSocket URL provided");
      this._closed = false;
      this._ws = new WebSocket(this.url);
      this._ws.binaryType = "arraybuffer";
      this._ws.onopen = () => {
        this._reconnectDelay = 1e3;
        this._flushBuffer();
        if (this.onOpen)
          this.onOpen();
      };
      this._ws.onmessage = (event) => {
        if (this.onData) {
          if (event.data instanceof ArrayBuffer) {
            this.onData(new Uint8Array(event.data));
          } else {
            this.onData(event.data);
          }
        }
      };
      this._ws.onclose = () => {
        if (this.onClose)
          this.onClose();
        if (this.reconnect && !this._closed)
          this._scheduleReconnect();
      };
      this._ws.onerror = (event) => {
        if (this.onError)
          this.onError(event);
        this._ws?.close();
      };
    }
    send(data) {
      if (this._ws && this._ws.readyState === WebSocket.OPEN) {
        if (typeof data === "string") {
          this._ws.send(new TextEncoder().encode(data));
        } else {
          this._ws.send(data);
        }
      } else {
        this._buffer.push(data);
      }
    }
    close() {
      this._closed = true;
      if (this._reconnectTimer)
        clearTimeout(this._reconnectTimer);
      if (this._ws)
        this._ws.close();
    }
    get connected() {
      return this._ws !== null && this._ws.readyState === WebSocket.OPEN;
    }
    _flushBuffer() {
      const items = this._buffer.splice(0);
      for (const item of items) {
        this.send(item);
      }
    }
    _scheduleReconnect() {
      this._reconnectTimer = setTimeout(() => {
        this.connect();
      }, this._reconnectDelay);
      this._reconnectDelay = Math.min(this._reconnectDelay * 2, this.maxReconnectDelay);
    }
  };

  // node_modules/@wterm/dom/dist/renderer.js
  var DEFAULT_COLOR = 256;
  var FLAG_BOLD = 1;
  var FLAG_DIM = 2;
  var FLAG_ITALIC = 4;
  var FLAG_UNDERLINE = 8;
  var FLAG_REVERSE = 32;
  var FLAG_INVISIBLE = 64;
  var FLAG_STRIKETHROUGH = 128;
  function rgbToCSS(packed) {
    const r = packed >> 16 & 255;
    const g = packed >> 8 & 255;
    const b = packed & 255;
    return `rgb(${r},${g},${b})`;
  }
  function colorToCSS(index) {
    if (index === DEFAULT_COLOR)
      return null;
    if (index < 16)
      return `var(--term-color-${index})`;
    if (index < 232) {
      const n = index - 16;
      const r = Math.floor(n / 36) * 51;
      const g = Math.floor(n / 6) % 6 * 51;
      const b = n % 6 * 51;
      return `rgb(${r},${g},${b})`;
    }
    const level = (index - 232) * 10 + 8;
    return `rgb(${level},${level},${level})`;
  }
  function cellFgCSS(fg, fgRgb) {
    if (fgRgb !== void 0)
      return rgbToCSS(fgRgb);
    return colorToCSS(fg);
  }
  function cellBgCSS(bg, bgRgb) {
    if (bgRgb !== void 0)
      return rgbToCSS(bgRgb);
    return colorToCSS(bg);
  }
  function buildCellStyle(fg, bg, flags, fgRgb, bgRgb) {
    let fgIdx = fg, bgIdx = bg, fgR = fgRgb, bgR = bgRgb;
    if (flags & FLAG_REVERSE) {
      const tmpIdx = fgIdx;
      fgIdx = bgIdx;
      bgIdx = tmpIdx;
      const tmpR = fgR;
      fgR = bgR;
      bgR = tmpR;
      if (fgR === void 0 && fgIdx === DEFAULT_COLOR)
        fgIdx = 0;
      if (bgR === void 0 && bgIdx === DEFAULT_COLOR)
        bgIdx = 7;
    }
    const fgCSS = cellFgCSS(fgIdx, fgR);
    const bgCSS = cellBgCSS(bgIdx, bgR);
    let style = "";
    if (fgCSS)
      style += `color:${fgCSS};`;
    if (bgCSS)
      style += `background:${bgCSS};`;
    if (flags & FLAG_BOLD)
      style += "font-weight:bold;";
    if (flags & FLAG_DIM)
      style += "opacity:0.5;";
    if (flags & FLAG_ITALIC)
      style += "font-style:italic;";
    const decorations = [];
    if (flags & FLAG_UNDERLINE)
      decorations.push("underline");
    if (flags & FLAG_STRIKETHROUGH)
      decorations.push("line-through");
    if (decorations.length)
      style += `text-decoration:${decorations.join(" ")};`;
    if (flags & FLAG_INVISIBLE)
      style += "visibility:hidden;";
    return style;
  }
  function escapeHTML(text) {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function resolveColors(fg, bg, flags, fgRgb, bgRgb) {
    let fgIdx = fg, bgIdx = bg, fgR = fgRgb, bgR = bgRgb;
    if (flags & FLAG_REVERSE) {
      [fgIdx, bgIdx] = [bgIdx, fgIdx];
      [fgR, bgR] = [bgR, fgR];
      if (fgR === void 0 && fgIdx === DEFAULT_COLOR)
        fgIdx = 0;
      if (bgR === void 0 && bgIdx === DEFAULT_COLOR)
        bgIdx = 7;
    }
    return {
      fg: cellFgCSS(fgIdx, fgR) || "var(--term-fg)",
      bg: cellBgCSS(bgIdx, bgR) || "var(--term-bg)"
    };
  }
  function getBlockBackground(cp, fg, bg) {
    switch (cp) {
      case 9600:
        return `linear-gradient(${fg} 50%,${bg} 50%)`;
      case 9601:
        return `linear-gradient(${bg} 87.5%,${fg} 87.5%)`;
      case 9602:
        return `linear-gradient(${bg} 75%,${fg} 75%)`;
      case 9603:
        return `linear-gradient(${bg} 62.5%,${fg} 62.5%)`;
      case 9604:
        return `linear-gradient(${bg} 50%,${fg} 50%)`;
      case 9605:
        return `linear-gradient(${bg} 37.5%,${fg} 37.5%)`;
      case 9606:
        return `linear-gradient(${bg} 25%,${fg} 25%)`;
      case 9607:
        return `linear-gradient(${bg} 12.5%,${fg} 12.5%)`;
      case 9608:
        return fg;
      case 9609:
        return `linear-gradient(to right,${fg} 87.5%,${bg} 87.5%)`;
      case 9610:
        return `linear-gradient(to right,${fg} 75%,${bg} 75%)`;
      case 9611:
        return `linear-gradient(to right,${fg} 62.5%,${bg} 62.5%)`;
      case 9612:
        return `linear-gradient(to right,${fg} 50%,${bg} 50%)`;
      case 9613:
        return `linear-gradient(to right,${fg} 37.5%,${bg} 37.5%)`;
      case 9614:
        return `linear-gradient(to right,${fg} 25%,${bg} 25%)`;
      case 9615:
        return `linear-gradient(to right,${fg} 12.5%,${bg} 12.5%)`;
      case 9616:
        return `linear-gradient(to right,${bg} 50%,${fg} 50%)`;
      case 9617:
        return `color-mix(in srgb,${fg} 25%,${bg})`;
      case 9618:
        return `color-mix(in srgb,${fg} 50%,${bg})`;
      case 9619:
        return `color-mix(in srgb,${fg} 75%,${bg})`;
      case 9620:
        return `linear-gradient(${fg} 12.5%,${bg} 12.5%)`;
      case 9621:
        return `linear-gradient(to right,${bg} 87.5%,${fg} 87.5%)`;
      default: {
        const QUADRANTS = {
          9622: [false, false, true, false],
          9623: [false, false, false, true],
          9624: [true, false, false, false],
          9625: [true, false, true, true],
          9626: [true, false, false, true],
          9627: [true, true, true, false],
          9628: [true, true, false, true],
          9629: [false, true, false, false],
          9630: [false, true, true, false],
          9631: [false, true, true, true]
        };
        const q = QUADRANTS[cp];
        if (!q)
          return fg;
        const [tl, tr, bl, br] = q;
        if (tl && tr && bl && br)
          return fg;
        const layers = [];
        const POS = ["0 0", "100% 0", "0 100%", "100% 100%"];
        q.forEach((filled, i) => {
          if (filled)
            layers.push(`linear-gradient(${fg},${fg}) ${POS[i]}/50% 50% no-repeat`);
        });
        layers.push(bg);
        return layers.join(",");
      }
    }
  }
  var Renderer = class {
    constructor(container) {
      this.rows = 0;
      this.cols = 0;
      this.rowEls = [];
      this.prevCursorRow = -1;
      this.prevCursorCol = -1;
      this.prevContainerBg = "";
      this.prevRowBg = [];
      this._scrollbackRowEls = [];
      this._renderedScrollbackCount = 0;
      this.container = container;
    }
    setup(cols, rows) {
      this.cols = cols;
      this.rows = rows;
      this.container.innerHTML = "";
      this.rowEls = [];
      this.prevRowBg = [];
      this._scrollbackRowEls = [];
      this._renderedScrollbackCount = 0;
      const fragment = document.createDocumentFragment();
      for (let r = 0; r < rows; r++) {
        const rowEl = document.createElement("div");
        rowEl.className = "term-row";
        fragment.appendChild(rowEl);
        this.rowEls.push(rowEl);
      }
      this.container.appendChild(fragment);
      this.prevCursorRow = -1;
      this.prevCursorCol = -1;
    }
    _buildRowContent(rowEl, getCell, lineLen, cursorCol, rowIndex) {
      let html = "";
      let runStyle = "";
      let runText = "";
      let runStart = 0;
      const flushRun = (endCol) => {
        if (!runText)
          return;
        const escaped = escapeHTML(runText);
        if (cursorCol >= runStart && cursorCol < endCol) {
          const offset = cursorCol - runStart;
          const chars = [...runText];
          const before = chars.slice(0, offset).join("");
          const cursorChar = chars[offset] || " ";
          const after = chars.slice(offset + 1).join("");
          if (before) {
            html += runStyle ? `<span style="${runStyle}">${escapeHTML(before)}</span>` : `<span>${escapeHTML(before)}</span>`;
          }
          html += runStyle ? `<span class="term-cursor" style="${runStyle}">${escapeHTML(cursorChar)}</span>` : `<span class="term-cursor">${escapeHTML(cursorChar)}</span>`;
          if (after) {
            html += runStyle ? `<span style="${runStyle}">${escapeHTML(after)}</span>` : `<span>${escapeHTML(after)}</span>`;
          }
        } else {
          html += runStyle ? `<span style="${runStyle}">${escaped}</span>` : `<span>${escaped}</span>`;
        }
      };
      for (let col = 0; col < this.cols; col++) {
        const cell = getCell(col);
        const inBounds = col < lineLen;
        const cp = inBounds ? cell.char : 0;
        if (inBounds && cp >= 9600 && cp <= 9631) {
          flushRun(col);
          const colors = resolveColors(cell.fg, cell.bg, cell.flags, cell.fgRgb, cell.bgRgb);
          const cls = col === cursorCol ? "term-block term-cursor" : "term-block";
          const bg = getBlockBackground(cp, colors.fg, colors.bg);
          const dim = cell.flags & FLAG_DIM ? "opacity:0.5;" : "";
          html += `<span class="${cls}" style="background:${bg};${dim}"></span>`;
          runStyle = "";
          runText = "";
          runStart = col + 1;
        } else {
          const ch = inBounds && cp >= 32 ? String.fromCodePoint(cp) : " ";
          const style = inBounds ? buildCellStyle(cell.fg, cell.bg, cell.flags, cell.fgRgb, cell.bgRgb) : "";
          if (style !== runStyle) {
            flushRun(col);
            runStyle = style;
            runText = ch;
            runStart = col;
          } else {
            runText += ch;
          }
        }
      }
      flushRun(this.cols);
      rowEl.innerHTML = html;
      let bgCss = "";
      if (lineLen >= this.cols && this.cols > 0) {
        const lastCell = getCell(this.cols - 1);
        let bgIdx = lastCell.bg;
        let bgR = lastCell.bgRgb;
        if (lastCell.flags & FLAG_REVERSE) {
          bgIdx = lastCell.fg;
          bgR = lastCell.fgRgb;
          if (bgR === void 0 && bgIdx === DEFAULT_COLOR)
            bgIdx = 7;
        }
        bgCss = cellBgCSS(bgIdx, bgR) || "";
      }
      const boxShadow = bgCss ? `0 1px 0 ${bgCss}` : "";
      if (rowIndex >= 0) {
        if (bgCss !== (this.prevRowBg[rowIndex] ?? "")) {
          rowEl.style.background = bgCss;
          rowEl.style.boxShadow = boxShadow;
          this.prevRowBg[rowIndex] = bgCss;
        }
      } else {
        rowEl.style.background = bgCss;
        rowEl.style.boxShadow = boxShadow;
      }
    }
    _buildScrollbackRowEl(core, sbOffset) {
      const rowEl = document.createElement("div");
      rowEl.className = "term-row term-scrollback-row";
      const lineLen = core.getScrollbackLineLen(sbOffset);
      this._buildRowContent(rowEl, (col) => core.getScrollbackCell(sbOffset, col), lineLen, -1, -1);
      return rowEl;
    }
    syncScrollback(core) {
      const scrollbackCount = core.getScrollbackCount();
      if (scrollbackCount === this._renderedScrollbackCount)
        return;
      if (scrollbackCount > this._renderedScrollbackCount) {
        const newCount = scrollbackCount - this._renderedScrollbackCount;
        const firstGridRow = this.rowEls[0] ?? null;
        const fragment = document.createDocumentFragment();
        for (let i = newCount - 1; i >= 0; i--) {
          const rowEl = this._buildScrollbackRowEl(core, i);
          fragment.appendChild(rowEl);
          this._scrollbackRowEls.push(rowEl);
        }
        this.container.insertBefore(fragment, firstGridRow);
      } else {
        const removeCount = this._renderedScrollbackCount - scrollbackCount;
        for (let i = 0; i < removeCount; i++) {
          const el = this._scrollbackRowEls.shift();
          if (el)
            el.remove();
        }
      }
      this._renderedScrollbackCount = scrollbackCount;
    }
    render(core) {
      const rows = core.getRows();
      const cols = core.getCols();
      let resized = false;
      if (rows !== this.rows || cols !== this.cols) {
        this.setup(cols, rows);
        resized = true;
      }
      this.syncScrollback(core);
      const cursor = core.getCursor();
      const cursorVisible = cursor.visible;
      const needsCursorUpdate = cursor.row !== this.prevCursorRow || cursor.col !== this.prevCursorCol;
      for (let r = 0; r < this.rows; r++) {
        const isDirty = resized || core.isDirtyRow(r);
        const hadCursor = r === this.prevCursorRow && needsCursorUpdate;
        const hasCursor = r === cursor.row;
        if (isDirty || hadCursor || hasCursor && needsCursorUpdate) {
          const cCol = hasCursor && cursorVisible ? cursor.col : -1;
          this._buildRowContent(this.rowEls[r], (col) => core.getCell(r, col), this.cols, cCol, r);
        }
      }
      this.prevCursorRow = cursor.row;
      this.prevCursorCol = cursor.col;
      const lastRowDirty = resized || core.isDirtyRow(this.rows - 1);
      if (lastRowDirty) {
        const bottomRight = core.getCell(this.rows - 1, this.cols - 1);
        let gridBgIdx = bottomRight.bg;
        let gridBgRgb = bottomRight.bgRgb;
        if (bottomRight.flags & FLAG_REVERSE) {
          gridBgIdx = bottomRight.fg;
          gridBgRgb = bottomRight.fgRgb;
          if (gridBgRgb === void 0 && gridBgIdx === DEFAULT_COLOR)
            gridBgIdx = 7;
        }
        const containerBg = cellBgCSS(gridBgIdx, gridBgRgb) || "";
        if (containerBg !== this.prevContainerBg) {
          this.container.style.background = containerBg;
          this.prevContainerBg = containerBg;
        }
      }
      core.clearDirty();
    }
  };

  // node_modules/@wterm/dom/dist/input.js
  var NORMAL_KEYS = {
    ArrowUp: "\x1B[A",
    ArrowDown: "\x1B[B",
    ArrowRight: "\x1B[C",
    ArrowLeft: "\x1B[D",
    Home: "\x1B[H",
    End: "\x1B[F"
  };
  var APP_KEYS = {
    ArrowUp: "\x1BOA",
    ArrowDown: "\x1BOB",
    ArrowRight: "\x1BOC",
    ArrowLeft: "\x1BOD",
    Home: "\x1BOH",
    End: "\x1BOF"
  };
  var FIXED_KEYS = {
    Enter: "\r",
    Backspace: "\x7F",
    Tab: "	",
    Escape: "\x1B",
    Insert: "\x1B[2~",
    Delete: "\x1B[3~",
    PageUp: "\x1B[5~",
    PageDown: "\x1B[6~",
    F1: "\x1BOP",
    F2: "\x1BOQ",
    F3: "\x1BOR",
    F4: "\x1BOS",
    F5: "\x1B[15~",
    F6: "\x1B[17~",
    F7: "\x1B[18~",
    F8: "\x1B[19~",
    F9: "\x1B[20~",
    F10: "\x1B[21~",
    F11: "\x1B[23~",
    F12: "\x1B[24~"
  };
  var InputHandler = class {
    constructor(element, onData, getBridge) {
      this.composing = false;
      this.element = element;
      this.onData = onData;
      this.getBridge = getBridge;
      this.textarea = document.createElement("textarea");
      this.textarea.setAttribute("autocapitalize", "off");
      this.textarea.setAttribute("autocomplete", "off");
      this.textarea.setAttribute("autocorrect", "off");
      this.textarea.setAttribute("spellcheck", "false");
      this.textarea.setAttribute("enterkeyhint", "send");
      this.textarea.setAttribute("tabindex", "0");
      this.textarea.setAttribute("aria-hidden", "true");
      const s = this.textarea.style;
      s.position = "absolute";
      s.left = "-9999px";
      s.top = "0";
      s.width = "1px";
      s.height = "1px";
      s.opacity = "0";
      s.overflow = "hidden";
      s.border = "0";
      s.padding = "0";
      s.margin = "0";
      s.outline = "none";
      s.resize = "none";
      s.pointerEvents = "none";
      s.caretColor = "transparent";
      s.color = "transparent";
      s.background = "transparent";
      element.appendChild(this.textarea);
      this._onKeyDown = this.handleKeyDown.bind(this);
      this._onPaste = this.handlePaste.bind(this);
      this._onCompositionStart = this.handleCompositionStart.bind(this);
      this._onCompositionEnd = this.handleCompositionEnd.bind(this);
      this._onInput = this.handleInput.bind(this);
      this._onFocus = () => this.element.classList.add("focused");
      this._onBlur = () => this.element.classList.remove("focused");
      this.textarea.addEventListener("keydown", this._onKeyDown);
      this.textarea.addEventListener("paste", this._onPaste);
      this.textarea.addEventListener("compositionstart", this._onCompositionStart);
      this.textarea.addEventListener("compositionend", this._onCompositionEnd);
      this.textarea.addEventListener("input", this._onInput);
      this.textarea.addEventListener("focus", this._onFocus);
      this.textarea.addEventListener("blur", this._onBlur);
    }
    focus() {
      this.textarea.focus({ preventScroll: true });
    }
    destroy() {
      this.textarea.removeEventListener("keydown", this._onKeyDown);
      this.textarea.removeEventListener("paste", this._onPaste);
      this.textarea.removeEventListener("compositionstart", this._onCompositionStart);
      this.textarea.removeEventListener("compositionend", this._onCompositionEnd);
      this.textarea.removeEventListener("input", this._onInput);
      this.textarea.removeEventListener("focus", this._onFocus);
      this.textarea.removeEventListener("blur", this._onBlur);
      this.element.classList.remove("focused");
      this.textarea.remove();
    }
    handleKeyDown(e) {
      if (this.composing)
        return;
      if ((e.metaKey || e.ctrlKey) && e.key === "c") {
        const sel = window.getSelection();
        if (sel && sel.toString().length > 0)
          return;
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "v") {
        this.textarea.focus();
        return;
      }
      if (e.metaKey && !e.ctrlKey) {
        if (e.key === "Backspace") {
          e.preventDefault();
          this.onData("");
        } else if (e.key === "a") {
          e.preventDefault();
          const sel = window.getSelection();
          if (sel) {
            const range = document.createRange();
            range.selectNodeContents(this.element);
            sel.removeAllRanges();
            sel.addRange(range);
          }
        }
        return;
      }
      e.preventDefault();
      const seq = this.keyToSequence(e);
      if (seq)
        this.onData(seq);
    }
    handlePaste(e) {
      e.preventDefault();
      const text = e.clipboardData?.getData("text");
      if (!text)
        return;
      const bridge = this.getBridge();
      if (bridge && bridge.bracketedPaste()) {
        const safe = text.replace(/\x1b/g, "");
        this.onData("\x1B[200~" + safe + "\x1B[201~");
      } else {
        this.onData(text);
      }
    }
    handleCompositionStart() {
      this.composing = true;
    }
    handleCompositionEnd(e) {
      this.composing = false;
      if (e.data)
        this.onData(e.data);
      this.textarea.value = "";
    }
    handleInput() {
      if (this.composing)
        return;
      const value = this.textarea.value;
      if (value) {
        this.onData(value);
        this.textarea.value = "";
      }
    }
    keyToSequence(e) {
      if (e.ctrlKey && !e.altKey && !e.metaKey) {
        if (e.key.length === 1) {
          const code = e.key.toLowerCase().charCodeAt(0);
          if (code >= 97 && code <= 122)
            return String.fromCharCode(code - 96);
        }
        if (e.key === "[")
          return "\x1B";
        if (e.key === "\\")
          return "";
        if (e.key === "]")
          return "";
        if (e.key === "^")
          return "";
        if (e.key === "_")
          return "";
      }
      if (e.key === "Enter" && e.shiftKey)
        return "\x1B[13;2u";
      if (e.key === "Tab" && e.shiftKey)
        return "\x1B[Z";
      const fixed = FIXED_KEYS[e.key];
      if (fixed)
        return e.altKey ? "\x1B" + fixed : fixed;
      const bridge = this.getBridge();
      const appMode = bridge && bridge.cursorKeysApp();
      const navMap = appMode ? APP_KEYS : NORMAL_KEYS;
      const nav = navMap[e.key];
      if (nav)
        return e.altKey ? "\x1B" + nav : nav;
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
        return e.altKey ? "\x1B" + e.key : e.key;
      }
      return null;
    }
  };

  // node_modules/@wterm/dom/dist/debug.js
  var FLAG_NAMES = {
    1: "bold",
    2: "dim",
    4: "italic",
    8: "underline",
    16: "blink",
    32: "reverse",
    64: "invisible",
    128: "strikethrough"
  };
  function flagsToNames(flags) {
    const names = [];
    for (const [bit, name] of Object.entries(FLAG_NAMES)) {
      if (flags & Number(bit))
        names.push(name);
    }
    return names;
  }
  var ESC = 27;
  function scanSequences(data) {
    const entries = [];
    const ts = Date.now();
    let i = 0;
    let textStart = 0;
    const flushText = () => {
      if (i > textStart) {
        const raw = data.slice(textStart, i);
        if (raw.length > 0 && !/^[\x00-\x1f]+$/.test(raw)) {
          entries.push({ ts, type: "text", raw: raw.slice(0, 60) });
        }
      }
    };
    while (i < data.length) {
      if (data.charCodeAt(i) !== ESC) {
        i++;
        continue;
      }
      flushText();
      const seqStart = i;
      i++;
      if (i >= data.length)
        break;
      const next = data[i];
      if (next === "[") {
        i++;
        let priv = "";
        if (i < data.length && (data[i] === "?" || data[i] === ">" || data[i] === "!")) {
          priv = data[i];
          i++;
        }
        let paramStr = "";
        while (i < data.length && (data.charCodeAt(i) >= 48 && data.charCodeAt(i) <= 59 || data[i] === ":")) {
          paramStr += data[i];
          i++;
        }
        while (i < data.length && data.charCodeAt(i) >= 32 && data.charCodeAt(i) <= 47) {
          i++;
        }
        let final = "";
        if (i < data.length && data.charCodeAt(i) >= 64 && data.charCodeAt(i) <= 126) {
          final = data[i];
          i++;
        }
        const raw = data.slice(seqStart, i);
        const params = paramStr ? paramStr.split(/[;:]/).map(Number).filter((n) => !isNaN(n)) : [];
        const type = final === "m" ? "sgr" : "csi";
        entries.push({
          ts,
          type,
          raw,
          params: params.length > 0 ? params : void 0,
          private: priv || void 0,
          final
        });
      } else if (next === "]") {
        i++;
        while (i < data.length && data.charCodeAt(i) !== 7 && !(data.charCodeAt(i) === ESC && i + 1 < data.length && data[i + 1] === "\\")) {
          i++;
        }
        if (i < data.length) {
          if (data.charCodeAt(i) === 7)
            i++;
          else if (data.charCodeAt(i) === ESC)
            i += 2;
        }
        const raw = data.slice(seqStart, i);
        entries.push({ ts, type: "osc", raw: raw.slice(0, 80) });
      } else if (next >= " " && next <= "~") {
        i++;
        entries.push({
          ts,
          type: "esc",
          raw: data.slice(seqStart, i),
          final: next
        });
      } else {
        i++;
      }
      textStart = i;
    }
    flushText();
    return entries;
  }
  var MAX_TRACES = 500;
  var DebugAdapter = class {
    constructor() {
      this._traces = [];
      this._bridge = null;
      this._perf = {
        frameCount: 0,
        totalRenderMs: 0,
        avgRenderMs: 0,
        maxRenderMs: 0,
        lastDirtyRows: 0
      };
    }
    get traces() {
      return this._traces;
    }
    get perf() {
      return this._perf;
    }
    setBridge(bridge) {
      this._bridge = bridge;
    }
    traceWrite(data) {
      const str = typeof data === "string" ? data : new TextDecoder().decode(data);
      const entries = scanSequences(str);
      for (const entry of entries) {
        this._traces.push(entry);
      }
      if (this._traces.length > MAX_TRACES) {
        this._traces = this._traces.slice(-MAX_TRACES);
      }
    }
    recordRender(renderMs, dirtyRows) {
      this._perf.frameCount++;
      this._perf.totalRenderMs += renderMs;
      this._perf.avgRenderMs = this._perf.totalRenderMs / this._perf.frameCount;
      if (renderMs > this._perf.maxRenderMs) {
        this._perf.maxRenderMs = renderMs;
      }
      this._perf.lastDirtyRows = dirtyRows;
    }
    resetPerf() {
      this._perf = {
        frameCount: 0,
        totalRenderMs: 0,
        avgRenderMs: 0,
        maxRenderMs: 0,
        lastDirtyRows: 0
      };
    }
    // -- Cell inspector --
    cell(row, col) {
      if (!this._bridge)
        return null;
      const c = this._bridge.getCell(row, col);
      return {
        ...c,
        charStr: c.char >= 32 ? String.fromCodePoint(c.char) : "",
        flagNames: flagsToNames(c.flags)
      };
    }
    row(row) {
      if (!this._bridge)
        return null;
      const cols = this._bridge.getCols();
      const cells = [];
      for (let c = 0; c < cols; c++) {
        cells.push(this.cell(row, c));
      }
      return cells;
    }
    grid() {
      if (!this._bridge)
        return null;
      const cursor = this._bridge.getCursor();
      return {
        rows: this._bridge.getRows(),
        cols: this._bridge.getCols(),
        cursor,
        altScreen: this._bridge.usingAltScreen(),
        scrollbackCount: this._bridge.getScrollbackCount()
      };
    }
    unhandled() {
      if (!this._bridge)
        return [];
      return this._bridge.getUnhandledSequences();
    }
    // -- Console-friendly dump --
    dump(count = 50) {
      const entries = this._traces.slice(-count);
      console.group(`%cwterm debug \u2014 last ${entries.length} traces`, "color: #569cd6; font-weight: bold");
      for (const e of entries) {
        const badge = e.type === "sgr" ? "%cSGR" : e.type === "csi" ? "%cCSI" : e.type === "osc" ? "%cOSC" : e.type === "esc" ? "%cESC" : "%cTXT";
        const color = e.type === "sgr" ? "background:#2d5a27;color:#fff;padding:1px 4px;border-radius:2px" : e.type === "csi" ? "background:#1e4a7a;color:#fff;padding:1px 4px;border-radius:2px" : "background:#555;color:#fff;padding:1px 4px;border-radius:2px";
        const detail = [
          e.private ? `private=${e.private}` : "",
          e.params ? `params=[${e.params}]` : "",
          e.final ? `final=${e.final}` : ""
        ].filter(Boolean).join(" ");
        console.log(`${badge} ${e.raw.slice(0, 40)}`, color, detail ? `  ${detail}` : "");
      }
      console.groupEnd();
    }
    dumpUnhandled() {
      const entries = this.unhandled();
      if (entries.length === 0) {
        console.log("%cwterm debug \u2014 no unhandled sequences", "color: #6a9955");
        return;
      }
      console.group(`%cwterm debug \u2014 ${entries.length} unhandled sequences`, "color: #d7ba7d; font-weight: bold");
      for (const e of entries) {
        console.log(`  final=${e.final} private=${e.private || "-"} params=[${e.params.slice(0, e.paramCount)}]`);
      }
      console.groupEnd();
    }
  };

  // node_modules/@wterm/dom/dist/wterm.js
  var WTerm = class {
    constructor(element, options = {}) {
      this.bridge = null;
      this.debug = null;
      this.renderer = null;
      this.input = null;
      this.rafId = null;
      this._renderTimer = null;
      this.resizeObserver = null;
      this._destroyed = false;
      this._shouldScrollToBottom = false;
      this._rowHeight = 0;
      this.element = element;
      this._coreOption = options.core;
      this.wasmUrl = options.wasmUrl;
      this.cols = options.cols || 80;
      this.rows = options.rows || 24;
      this.autoResize = options.autoResize !== false;
      this._debugEnabled = options.debug ?? false;
      this.onData = options.onData || null;
      this.onTitle = options.onTitle || null;
      this.onResize = options.onResize || null;
      this._container = document.createElement("div");
      this._container.className = "term-grid";
      this.element.appendChild(this._container);
      this.element.classList.add("wterm");
      if (options.cursorBlink)
        this.element.classList.add("cursor-blink");
      this._onClickFocus = () => {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed)
          this.input?.focus();
      };
      this.element.addEventListener("click", this._onClickFocus);
    }
    async init() {
      try {
        if (this._coreOption) {
          this.bridge = this._coreOption;
        } else {
          this.bridge = await WasmBridge.load(this.wasmUrl);
        }
        if (this._destroyed)
          return this;
        this.bridge.init(this.cols, this.rows);
        if (this._debugEnabled) {
          this.debug = new DebugAdapter();
          this.debug.setBridge(this.bridge);
          globalThis.__wterm = this;
        }
        this._setRowHeight();
        this.renderer = new Renderer(this._container);
        this.renderer.setup(this.cols, this.rows);
        this.input = new InputHandler(this.element, (data) => {
          this._scrollToBottom();
          if (this.onData) {
            this.onData(data);
          } else {
            this.write(data);
          }
        }, () => this.bridge);
        if (this.autoResize) {
          this._setupResizeObserver();
        } else {
          this._lockHeight();
        }
        this.input.focus();
        this._initialRender();
      } catch (err) {
        this.destroy();
        throw new Error(`wterm: failed to initialize: ${err instanceof Error ? err.message : err}`);
      }
      return this;
    }
    _isScrolledToBottom() {
      const el = this.element;
      return el.scrollHeight - el.scrollTop - el.clientHeight < 5;
    }
    _scrollToBottom() {
      const el = this.element;
      const maxScroll = el.scrollHeight - el.clientHeight;
      if (maxScroll <= 0) {
        el.scrollTop = 0;
        return;
      }
      const rh = this._rowHeight || 17;
      el.scrollTop = Math.floor(maxScroll / rh) * rh;
    }
    write(data) {
      if (!this.bridge)
        return;
      if (this.debug)
        this.debug.traceWrite(data);
      this._shouldScrollToBottom = this._isScrolledToBottom();
      if (typeof data === "string") {
        this.bridge.writeString(data);
      } else {
        this.bridge.writeRaw(data);
      }
      this._scheduleRender();
    }
    resize(cols, rows) {
      if (!this.bridge)
        return;
      this._shouldScrollToBottom = this._isScrolledToBottom();
      this.cols = cols;
      this.rows = rows;
      this.bridge.resize(cols, rows);
      this.renderer?.setup(cols, rows);
      this._scheduleRender();
      if (this.onResize)
        this.onResize(cols, rows);
    }
    focus() {
      if (this.input) {
        this.input.focus();
      } else {
        this.element.focus();
      }
    }
    _scheduleRender() {
      if (this._renderTimer != null)
        return;
      this._renderTimer = setTimeout(() => {
        this._renderTimer = null;
        if (this.rafId == null) {
          this.rafId = requestAnimationFrame(() => {
            this.rafId = null;
            this._doRender();
          });
        }
      }, 0);
    }
    _initialRender() {
      this._doRender();
    }
    _doRender() {
      if (!this.bridge || !this.renderer)
        return;
      let dirtyCount = 0;
      const t0 = this.debug ? performance.now() : 0;
      if (this.debug) {
        for (let r = 0; r < this.rows; r++) {
          if (this.bridge.isDirtyRow(r))
            dirtyCount++;
        }
      }
      this.renderer.render(this.bridge);
      if (this.debug) {
        this.debug.recordRender(performance.now() - t0, dirtyCount);
      }
      const hasScrollback = this.bridge.getScrollbackCount() > 0;
      this.element.classList.toggle("has-scrollback", hasScrollback);
      if (this._shouldScrollToBottom) {
        this._scrollToBottom();
      } else if (!hasScrollback && this.element.scrollTop !== 0) {
        this.element.scrollTop = 0;
      }
      const title = this.bridge.getTitle();
      if (title !== null && this.onTitle) {
        this.onTitle(title);
      }
      const response = this.bridge.getResponse();
      if (response !== null && this.onData) {
        this.onData(response);
      }
    }
    _lockHeight() {
      const rh = this._rowHeight || 17;
      const gridHeight = this.rows * rh;
      const cs = getComputedStyle(this.element);
      let extra = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
      if (cs.boxSizing === "border-box") {
        extra += (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.borderBottomWidth) || 0);
      }
      this.element.style.height = `${gridHeight + extra}px`;
    }
    _setRowHeight() {
      const probe = document.createElement("div");
      probe.className = "term-row";
      probe.style.visibility = "hidden";
      probe.style.position = "absolute";
      probe.textContent = "W";
      this._container.appendChild(probe);
      const h = probe.getBoundingClientRect().height;
      probe.remove();
      if (h > 0) {
        const rh = Math.ceil(h);
        this._rowHeight = rh;
        this.element.style.setProperty("--term-row-height", `${rh}px`);
      }
    }
    _measureCharSize() {
      const row = document.createElement("div");
      row.className = "term-row";
      row.style.visibility = "hidden";
      row.style.position = "absolute";
      const probe = document.createElement("span");
      probe.textContent = "W";
      row.appendChild(probe);
      this._container.appendChild(row);
      const charWidth = probe.getBoundingClientRect().width;
      const rowHeight = row.getBoundingClientRect().height;
      row.remove();
      if (charWidth === 0 || rowHeight === 0)
        return null;
      this._rowHeight = rowHeight;
      return { charWidth, rowHeight };
    }
    _setupResizeObserver() {
      const initial = this._measureCharSize();
      if (!initial)
        return;
      let { charWidth, rowHeight } = initial;
      this.resizeObserver = new ResizeObserver((entries) => {
        const measured = this._measureCharSize();
        if (measured) {
          charWidth = measured.charWidth;
          rowHeight = measured.rowHeight;
        }
        for (const entry of entries) {
          const { width, height } = entry.contentRect;
          const newCols = Math.max(1, Math.floor(width / charWidth));
          const newRows = Math.max(1, Math.floor(height / rowHeight));
          if (newCols !== this.cols || newRows !== this.rows) {
            this.resize(newCols, newRows);
          }
        }
      });
      this.resizeObserver.observe(this.element);
    }
    destroy() {
      this._destroyed = true;
      if (this._renderTimer != null)
        clearTimeout(this._renderTimer);
      if (this.rafId != null)
        cancelAnimationFrame(this.rafId);
      if (this.resizeObserver)
        this.resizeObserver.disconnect();
      if (this.input)
        this.input.destroy();
      this.element.removeEventListener("click", this._onClickFocus);
      this.element.innerHTML = "";
      if (this.debug && globalThis.__wterm === this) {
        delete globalThis.__wterm;
      }
      this.debug = null;
    }
  };
  return __toCommonJS(entry_exports);
})();
