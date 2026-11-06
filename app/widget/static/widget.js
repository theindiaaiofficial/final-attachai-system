(() => {
  "use strict";

  const script = document.currentScript;
  const apiKey = script?.dataset?.apiKey || "";
  const base = (script?.dataset?.baseUrl || location.origin).replace(/\/$/, "");
  const DAY_MS = 24 * 60 * 60 * 1000;
  const MAX_MESSAGES = 80;
  const hash = value => {
    let result = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      result ^= value.charCodeAt(index);
      result = Math.imul(result, 16777619);
    }
    return (result >>> 0).toString(36);
  };
  const storageKey = `orbit-widget:v2:${hash(`${base}:${apiKey}`)}`;
  const readStored = () => {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey) || "{}");
      return value && typeof value === "object" ? value : {};
    } catch {
      return {};
    }
  };

  const stored = readStored();
  let expiredSessionId = null;
  let sessionId = typeof stored.sessionId === "string" ? stored.sessionId : null;
  let messages = Array.isArray(stored.messages)
    ? stored.messages.filter(item => item && ["user", "assistant"].includes(item.role) && typeof item.content === "string")
    : [];
  let startedAt = Number(stored.startedAt) || null;
  let expiresAt = Number(stored.expiresAt) || null;

  if (expiresAt && expiresAt <= Date.now()) {
    expiredSessionId = sessionId;
    sessionId = null;
    messages = [];
    startedAt = null;
    expiresAt = null;
    localStorage.removeItem(storageKey);
  } else if (startedAt && !expiresAt) {
    expiresAt = startedAt + DAY_MS;
  }

  let busy = false;
  let activeRequest = null;
  let processingInterval = null;
  let assistantName = "Assistant";
  let welcome = "How can I help?";
  let speechConfig = {ttsEnabled: false};
  let activeSpeech = null;

  const ICON_PATHS = {
    orbit: '<circle cx="12" cy="12" r="2.8"/><ellipse cx="12" cy="12" rx="9" ry="4.2" transform="rotate(-32 12 12)"/><circle cx="19.2" cy="6.1" r="1.2"/>',
    bot: '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01M9 17h6"/><path d="M8 4h4"/>',
    user: '<circle cx="12" cy="8" r="3.4"/><path d="M5 20c.5-3.3 3.1-5.2 7-5.2s6.5 1.9 7 5.2"/>',
    message: '<path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2v-6.5A7.5 7.5 0 1 1 20 11.5Z"/>',
    share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.7 10.6 6.6-4.1M8.7 13.4l6.6 4.1"/>',
    close: '<path d="m18 6-12 12M6 6l12 12"/>',
    trash: '<path d="M3 6h18M8 6V4h8v2m3 0-1 14H6L5 6m4 4v6m6-6v6"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    thumbsUp: '<path d="M7 10v10H4V10h3Zm0 9h9.2a2 2 0 0 0 1.9-1.4l1.4-5A2 2 0 0 0 17.6 10H13l.7-3.2A2.2 2.2 0 0 0 11.5 4L7 10v9Z"/>',
    thumbsDown: '<path d="M7 14V4H4v10h3Zm0-9h9.2a2 2 0 0 1 1.9 1.4l1.4 5a2 2 0 0 1-1.9 2.6H13l.7 3.2a2.2 2.2 0 0 1-2.2 2.8L7 14V5Z"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    volume: '<path d="M4 10v4h4l5 4V6l-5 4H4Z"/><path d="M17 9a5 5 0 0 1 0 6m2-9a9 9 0 0 1 0 12"/>',
    send: '<path d="m21 3-7.2 18-3.4-7.4L3 10.2 21 3Z"/><path d="M10.4 13.6 21 3"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    play: '<path d="m8 5 12 7-12 7V5Z"/>',
    refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.5 9a7 7 0 0 1 11.8-2L20 12M4 12l2.7 5a7 7 0 0 0 11.8-2"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
  };

  function iconSvg(name) {
    const body = ICON_PATHS[name] || ICON_PATHS.orbit;
    return `<svg class="orbit-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;
  }

  function cleanVisitorText(value) {
    return String(value ?? "")
      .replace(/\(\s*(?:(?:\[S\d+\]|【S\d+】)\s*,?\s*)+\)/gi, "")
      .replace(/\[S\d+\]|【S\d+】/gi, "")
      .replace(/^[ \t]*Sources?:[ \t]*$/gim, "")
      .replace(/\(\s*\)/g, "")
      .replace(/[ \t]+([,.;:!?])/g, "$1")
      .replace(/[ \t]{2,}/g, " ")
      .replace(/\n[ \t]+/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  const root = document.createElement("div");
  root.setAttribute("data-orbit-widget", "true");
  root.className = "orbit-widget-root";
  const shadow = root.attachShadow({mode: "open"});
  shadow.innerHTML = `<link rel="stylesheet" href="${base}/widget.css">`;

  const launcher = document.createElement("button");
  launcher.className = "orbit-launcher";
  launcher.type = "button";
  launcher.innerHTML = `${iconSvg("message")}<span>Chat</span>`;
  launcher.setAttribute("aria-expanded", "false");
  launcher.setAttribute("aria-label", "Open chat");

  const panel = document.createElement("section");
  panel.className = "orbit-panel";
  panel.hidden = true;
  panel.setAttribute("aria-label", "Website assistant");

  const head = document.createElement("header");
  head.className = "orbit-head";
  const mark = document.createElement("div");
  mark.className = "orbit-mark";
  mark.innerHTML = iconSvg("orbit");
  const title = document.createElement("div");
  title.className = "orbit-title";
  const titleName = document.createElement("strong");
  const titleStatus = document.createElement("span");
  title.append(titleName, titleStatus);

  const headerActions = document.createElement("div");
  headerActions.className = "orbit-header-actions";
  const shareConversationButton = makeButton("orbit-icon-button", "Share conversation", "share");
  shareConversationButton.disabled = true;
  const close = makeButton("orbit-close", "Minimize chat", "close");
  headerActions.append(shareConversationButton, close);
  head.append(mark, title, headerActions);

  const timerBar = document.createElement("div");
  timerBar.className = "orbit-timer";
  timerBar.hidden = true;
  const timerIcon = document.createElement("span");
  timerIcon.className = "orbit-timer-icon";
  timerIcon.innerHTML = iconSvg("clock");
  const timerText = document.createElement("span");
  timerText.className = "orbit-timer-text";
  const deleteButton = makeButton("orbit-delete", "Delete this conversation", "trash");
  timerBar.append(timerIcon, timerText, deleteButton);

  const log = document.createElement("div");
  log.className = "orbit-messages";
  log.setAttribute("role", "log");
  log.setAttribute("aria-live", "polite");
  const status = document.createElement("div");
  status.className = "orbit-status";
  status.hidden = true;
  status.setAttribute("role", "alert");
  const compose = document.createElement("form");
  compose.className = "orbit-compose";
  const input = document.createElement("textarea");
  input.className = "orbit-input";
  input.rows = 1;
  input.placeholder = "Ask a question...";
  input.setAttribute("aria-label", "Message");
  const send = document.createElement("button");
  send.className = "orbit-send";
  send.type = "submit";
  send.setAttribute("aria-label", "Start voice message");
  compose.append(input, send);
  panel.append(head, timerBar, log, status, compose);
  shadow.append(panel, launcher);
  document.body.append(root);

  function makeButton(className, label, text) {
    const button = document.createElement("button");
    button.className = className;
    button.type = "button";
    if (ICON_PATHS[text]) button.innerHTML = iconSvg(text);
    else button.textContent = text;
    button.setAttribute("aria-label", label);
    button.title = label;
    return button;
  }

  function persist() {
    try {
      if (!messages.length && !sessionId) {
        localStorage.removeItem(storageKey);
        return;
      }
      localStorage.setItem(storageKey, JSON.stringify({
        sessionId,
        messages: messages.slice(-MAX_MESSAGES),
        startedAt,
        expiresAt,
      }));
    } catch {
      showStatus("This browser could not save the chat locally.");
    }
  }

  const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[char]);

  function inlineMarkdown(value) {
    return value
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
  }

  function markdown(value) {
    const normalized = cleanVisitorText(value).replace(/\\\|/g, "|");
    const blocks = escapeHtml(normalized).split(/\n{2,}/);
    return blocks.map(block => {
      const lines = block.split("\n");
      const cells = line => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(cell => cell.trim());
      if (lines.length >= 2 && lines[0].includes("|") && lines[1].includes("|")) {
        const headers = cells(lines[0]);
        const separators = cells(lines[1]);
        if (headers.length && headers.length === separators.length && separators.every(cell => /^:?-{3,}:?$/.test(cell))) {
          const bodyRows = lines.slice(2).filter(line => line.includes("|")).map(cells);
          const head = headers.map(cell => `<th>${inlineMarkdown(cell)}</th>`).join("");
          const body = bodyRows.map(row => `<tr>${headers.map((_, index) => `<td>${inlineMarkdown(row[index] || "")}</td>`).join("")}</tr>`).join("");
          return `<div class="orbit-table-wrap"><table class="orbit-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
        }
      }
      if (lines.every(line => /^[-*] /.test(line))) {
        return `<ul>${lines.map(line => `<li>${inlineMarkdown(line.slice(2))}</li>`).join("")}</ul>`;
      }
      if (lines.every(line => /^\d+[.)] /.test(line))) {
        return `<ol>${lines.map(line => `<li>${inlineMarkdown(line.replace(/^\d+[.)] /, ""))}</li>`).join("")}</ol>`;
      }
      if (lines.length === 1 && /^#{1,3} /.test(lines[0])) {
        const level = Math.min(3, lines[0].match(/^#+/)[0].length);
        const content = inlineMarkdown(lines[0].replace(/^#{1,3} /, ""));
        return `<h${level + 2}>${content}</h${level + 2}>`;
      }
      return `<p>${lines.map(inlineMarkdown).join("<br>")}</p>`;
    }).join("");
  }

  function showStatus(message) {
    status.textContent = message || "";
    status.hidden = !message;
  }

  function scrollLatest() {
    requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
  }

  function updateTimer() {
    if (!expiresAt || !messages.length) {
      timerBar.hidden = true;
      return;
    }
    const remaining = expiresAt - Date.now();
    if (remaining <= 0) {
      clearConversation(false);
      return;
    }
    const totalSeconds = Math.floor(remaining / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    timerText.textContent = `Chat expires in ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    timerBar.hidden = false;
  }

  function beginConversation() {
    if (expiresAt) return;
    startedAt = Date.now();
    expiresAt = startedAt + DAY_MS;
    updateTimer();
  }

  function renderMessage(item, index) {
    const row = document.createElement("article");
    row.className = `orbit-message ${item.role}`;
    const avatar = document.createElement("div");
    avatar.className = "orbit-avatar";
    avatar.innerHTML = iconSvg(item.role === "user" ? "user" : "bot");
    const contentWrap = document.createElement("div");
    contentWrap.className = "orbit-message-content";
    const bubble = document.createElement("div");
    bubble.className = "orbit-bubble";
    if (item.role === "assistant") bubble.innerHTML = markdown(cleanVisitorText(item.content));
    else bubble.textContent = item.content;
    contentWrap.append(bubble);

    if (item.role === "assistant") {
      const speechPlayer = document.createElement("div");
      speechPlayer.className = "orbit-speech-player";
      speechPlayer.hidden = true;
      speechPlayer.dataset.state = "idle";
      speechPlayer.setAttribute("aria-live", "polite");

      const speechHeader = document.createElement("div");
      speechHeader.className = "orbit-speech-header";
      const speechLabel = document.createElement("span");
      speechLabel.className = "orbit-speech-label";
      speechLabel.textContent = "Preparing audio…";
      const speechWave = document.createElement("span");
      speechWave.className = "orbit-speech-wave";
      speechWave.setAttribute("aria-hidden", "true");
      for (let barIndex = 0; barIndex < 19; barIndex += 1) {
        const bar = document.createElement("i");
        bar.style.setProperty("--wave-delay", `${barIndex * 37}ms`);
        bar.style.setProperty("--wave-height", `${5 + Math.round(Math.abs(Math.sin(barIndex * .73)) * 12)}px`);
        speechWave.append(bar);
      }
      const speechSpinner = document.createElement("span");
      speechSpinner.className = "orbit-speech-spinner";
      speechSpinner.setAttribute("aria-hidden", "true");
      speechHeader.append(speechSpinner, speechLabel, speechWave);

      const speechProgress = document.createElement("div");
      speechProgress.className = "orbit-speech-progress";
      const speechProgressFill = document.createElement("span");
      speechProgress.append(speechProgressFill);
      const speechMeta = document.createElement("div");
      speechMeta.className = "orbit-speech-meta";
      const speechElapsed = document.createElement("span");
      speechElapsed.textContent = "0:00";
      const speechTotal = document.createElement("span");
      speechTotal.textContent = "--:--";
      speechMeta.append(speechElapsed, speechTotal);

      const speechControls = document.createElement("div");
      speechControls.className = "orbit-speech-controls";
      const pauseSpeech = makeButton("orbit-speech-control", "Pause speech", "pause");
      const stopSpeech = makeButton("orbit-speech-control", "Stop speech", "stop");
      pauseSpeech.disabled = true;
      stopSpeech.disabled = true;
      speechControls.append(pauseSpeech, stopSpeech);
      speechPlayer.append(speechHeader, speechProgress, speechMeta, speechControls);

      const actions = document.createElement("div");
      actions.className = "orbit-message-actions";
      const like = makeButton("orbit-message-action", "Like response", "thumbsUp");
      const copy = makeButton("orbit-message-action", "Copy response", "copy");
      const speak = makeButton("orbit-message-action", "Speak response", "volume");
      const dislike = makeButton("orbit-message-action", "Dislike response", "thumbsDown");
      const share = makeButton("orbit-message-action", "Share response", "share");
      speak.hidden = !speechConfig.ttsEnabled;
      speak.disabled = !speechConfig.ttsEnabled;
      if (!speechConfig.ttsEnabled) speak.title = "Text-to-speech is not configured";
      if (item.reaction === "like") like.classList.add("selected");
      if (item.reaction === "dislike") dislike.classList.add("selected");
      like.setAttribute("aria-pressed", String(item.reaction === "like"));
      dislike.setAttribute("aria-pressed", String(item.reaction === "dislike"));
      like.addEventListener("click", () => setReaction(index, "like"));
      dislike.addEventListener("click", () => setReaction(index, "dislike"));
      copy.addEventListener("click", async () => {
        if (await copyText(cleanVisitorText(item.content))) showStatus("Response copied.");
        else showStatus("Could not copy this response.");
      });
      share.addEventListener("click", () => shareText(cleanVisitorText(item.content), "Assistant response"));
      speak.addEventListener("click", () => {
        void speakText(cleanVisitorText(item.content), {
          player: speechPlayer,
          label: speechLabel,
          wave: speechWave,
          spinner: speechSpinner,
          progress: speechProgressFill,
          elapsed: speechElapsed,
          total: speechTotal,
          pauseButton: pauseSpeech,
          stopButton: stopSpeech,
          speakerButton: speak,
        });
      });
      pauseSpeech.addEventListener("click", () => toggleSpeechPause(speechPlayer));
      stopSpeech.addEventListener("click", () => stopSpeechPlayback(speechPlayer));
      actions.append(like, copy, speak, dislike, share);
      contentWrap.append(speechPlayer, actions);
    }
    row.append(avatar, contentWrap);
    log.append(row);
  }

  function stopProcessing() {
    if (processingInterval !== null) {
      window.clearInterval(processingInterval);
      processingInterval = null;
    }
  }

  function renderTyping() {
    stopProcessing();
    const row = document.createElement("article");
    row.id = "orbit-typing";
    row.className = "orbit-message assistant orbit-processing";
    const avatar = document.createElement("div");
    avatar.className = "orbit-avatar";
    avatar.innerHTML = iconSvg("bot");

    const content = document.createElement("div");
    content.className = "orbit-message-content";
    const panel = document.createElement("div");
    panel.className = "orbit-bubble orbit-thinking";
    const heading = document.createElement("div");
    heading.className = "orbit-thinking-heading";
    const indicator = document.createElement("span");
    indicator.className = "orbit-thinking-indicator";
    indicator.innerHTML = "<i></i><i></i><i></i>";
    const label = document.createElement("span");
    label.className = "orbit-thinking-label";
    label.setAttribute("aria-live", "polite");
    label.textContent = "Understanding your question";
    heading.append(indicator, label);

    const track = document.createElement("div");
    track.className = "orbit-thinking-track";
    const fill = document.createElement("span");
    track.append(fill);
    panel.append(heading, track);
    content.append(panel);
    row.append(avatar, content);
    log.append(row);
    scrollLatest();

  }

  function updateProcessingLabel(value) {
    const label = log.querySelector("#orbit-typing .orbit-thinking-label");
    if (label && value) label.textContent = value;
  }

  async function consumeEventStream(response, onEvent) {
    if (!response.body?.getReader) throw new Error("Streaming is not supported by this browser.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const dispatch = raw => {
      let eventName = "message";
      const dataLines = [];
      for (const line of raw.split(/\r?\n/)) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      if (!dataLines.length) return;
      let data;
      try { data = JSON.parse(dataLines.join("\n")); }
      catch { throw new Error("The response stream contained invalid data."); }
      onEvent(eventName, data);
    };
    while (true) {
      const {value, done} = await reader.read();
      if (value) buffer += decoder.decode(value, {stream: true});
      if (done) buffer += decoder.decode();
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (raw.trim()) dispatch(raw);
      }
      if (done) break;
    }
    if (buffer.trim()) dispatch(buffer);
  }

  async function revealAssistantMessage(value) {
    const text = cleanVisitorText(value);
    const row = document.createElement("article");
    row.className = "orbit-message assistant";
    const avatar = document.createElement("div");
    avatar.className = "orbit-avatar";
    avatar.innerHTML = iconSvg("bot");
    const content = document.createElement("div");
    content.className = "orbit-message-content";
    const bubble = document.createElement("div");
    bubble.className = "orbit-bubble orbit-typewriter";
    content.append(bubble);
    row.append(avatar, content);
    log.append(row);

    const pieces = text.match(/\S+\s*/gu) || [text];
    const delay = Math.max(8, Math.min(28, 2400 / Math.max(pieces.length, 1)));
    let visible = "";
    for (let index = 0; index < pieces.length; index += 1) {
      visible += pieces[index];
      bubble.innerHTML = markdown(visible) + '<span class="orbit-caret" aria-hidden="true"></span>';
      if (index % 2 === 0 || index === pieces.length - 1) scrollLatest();
      if (index < pieces.length - 1) {
        await new Promise(resolve => window.setTimeout(resolve, delay));
      }
    }
    bubble.innerHTML = markdown(text);
    row.classList.add("orbit-message-complete");
    scrollLatest();
  }

  function renderAll() {
    // Rebuilding the message DOM must not leave playback attached to a removed row.
    if (activeSpeech) cleanupSpeech(activeSpeech);
    log.replaceChildren();
    if (!messages.length) {
      const welcomeNode = document.createElement("div");
      welcomeNode.className = "orbit-welcome";
      const strong = document.createElement("strong");
      strong.textContent = `Welcome to ${assistantName}`;
      const paragraph = document.createElement("p");
      paragraph.textContent = welcome;
      welcomeNode.append(strong, paragraph);
      log.append(welcomeNode);
    } else {
      messages.forEach(renderMessage);
    }
    shareConversationButton.disabled = messages.length === 0;
    updateTimer();
    scrollLatest();
  }

  async function loadConfig() {
    try {
      const response = await fetch(`${base}/v1/config`, {headers: {"X-API-Key": apiKey}});
      if (!response.ok) return;
      const data = await response.json();
      assistantName = data.assistantName || assistantName;
      welcome = data.welcomeMessage || welcome;
      speechConfig = data.speech || speechConfig;
      titleName.textContent = assistantName;
      titleStatus.textContent = data.clientName || "Online assistant";
      renderAll();
    } catch {
      titleStatus.textContent = "Online assistant";
    }
  }

  async function copyText(text) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch {
      // Continue with the selection-based fallback below.
    }
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    shadow.append(area);
    area.select();
    let success = false;
    try { success = document.execCommand("copy"); } catch { success = false; }
    area.remove();
    return success;
  }

  async function shareText(text, titleText) {
    const payload = {title: titleText, text};
    try {
      if (navigator.share) {
        await navigator.share(payload);
        return;
      }
      if (await copyText(text)) showStatus("Share text copied. You can paste it into any app.");
      else showStatus("Sharing is not available in this browser.");
    } catch (error) {
      if (error?.name !== "AbortError") showStatus("Could not share this content.");
    }
  }

  function conversationTranscript() {
    return messages.map(item => `${item.role === "user" ? "You" : assistantName}:\n${cleanVisitorText(item.content)}`).join("\n\n");
  }

  function setReaction(index, reaction) {
    const item = messages[index];
    if (!item || item.role !== "assistant") return;
    item.reaction = item.reaction === reaction ? null : reaction;
    persist();
    renderAll();
  }

  function formatSpeechTime(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return "--:--";
    const whole = Math.floor(seconds);
    const minutes = Math.floor(whole / 60);
    const remainder = whole % 60;
    return `${minutes}:${String(remainder).padStart(2, "0")}`;
  }

  function setSpeechState(ui, state, label) {
    if (!ui?.player) return;
    ui.player.hidden = false;
    ui.player.dataset.state = state;
    if (label) ui.label.textContent = label;
    ui.spinner.hidden = state !== "loading";
    ui.wave.hidden = !["playing", "paused", "complete"].includes(state);
    ui.pauseButton.disabled = !["playing", "paused", "ready"].includes(state);
    ui.stopButton.disabled = !["playing", "paused", "loading", "ready"].includes(state);
    const canResume = state === "paused" || state === "ready";
    ui.pauseButton.innerHTML = iconSvg(canResume ? "play" : "pause");
    ui.pauseButton.setAttribute("aria-label", canResume ? "Play speech" : "Pause speech");
    ui.pauseButton.title = canResume ? "Play speech" : "Pause speech";
  }

  function cleanupSpeech(state, keepPlayer = false) {
    if (!state) return;
    if (state.controller && !state.controller.signal.aborted) state.controller.abort();
    if (state.audio) {
      try { state.audio.pause(); } catch { /* playback may already be stopped */ }
      state.audio.removeAttribute("src");
      try { state.audio.load(); } catch { /* browser may already have released it */ }
    }
    if (state.url) {
      URL.revokeObjectURL(state.url);
      state.url = null;
    }
    if (activeSpeech === state) activeSpeech = null;
    state.speakerButton?.classList.remove("selected");
    if (!keepPlayer) state.ui.player.hidden = true;
  }

  function stopSpeechPlayback(player) {
    if (!activeSpeech || activeSpeech.ui.player !== player) return;
    const state = activeSpeech;
    cleanupSpeech(state);
    state.ui.player.hidden = true;
  }

  function toggleSpeechPause(player) {
    const state = activeSpeech;
    if (!state || state.ui.player !== player || !state.audio) return;
    if (state.audio.paused) {
      state.audio.play().then(() => {
        setSpeechState(state.ui, "playing", "Speaking response");
      }).catch(error => {
        if (error?.name === "NotAllowedError") {
          setSpeechState(state.ui, "ready", "Audio ready — tap play");
        } else {
          cleanupSpeech(state);
          setSpeechState(state.ui, "error", "Playback could not resume");
        }
      });
    } else {
      state.audio.pause();
      setSpeechState(state.ui, "paused", "Paused");
    }
  }

  function updateSpeechProgress(state) {
    if (!state?.audio || activeSpeech !== state) return;
    const duration = state.audio.duration;
    const current = state.audio.currentTime || 0;
    state.ui.elapsed.textContent = formatSpeechTime(current);
    state.ui.total.textContent = formatSpeechTime(duration);
    const ratio = Number.isFinite(duration) && duration > 0 ? Math.min(1, current / duration) : 0;
    state.ui.progress.style.width = `${ratio * 100}%`;
  }

  async function speakText(text, ui) {
    if (!speechConfig.ttsEnabled) {
      setSpeechState(ui, "error", "Text-to-speech is not configured");
      return false;
    }

    if (activeSpeech) {
      const wasSamePlayer = activeSpeech.ui.player === ui.player;
      cleanupSpeech(activeSpeech);
      if (wasSamePlayer) {
        ui.player.hidden = true;
        return false;
      }
    }

    const controller = new AbortController();
    const state = {controller, audio: null, url: null, ui, speakerButton: ui.speakerButton};
    activeSpeech = state;
    state.speakerButton.classList.add("selected");
    ui.player.hidden = false;
    ui.progress.style.width = "0%";
    ui.elapsed.textContent = "0:00";
    ui.total.textContent = "--:--";
    setSpeechState(ui, "loading", "Preparing audio…");

    try {
      const language = /[\u0900-\u097F]/u.test(text) ? "hi" : null;
      const response = await fetch(`${base}/v1/tts`, {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-API-Key": apiKey},
        body: JSON.stringify({text, language}),
        signal: controller.signal,
      });
      const errorData = response.ok ? null : await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorData?.detail || `TTS request failed (${response.status})`);
      const blob = await response.blob();
      if (activeSpeech !== state || controller.signal.aborted) return false;
      if (!blob.size) throw new Error("The speech provider returned empty audio.");

      const mediaType = response.headers.get("content-type") || blob.type || "audio/mpeg";
      const normalizedMediaType = String(mediaType).split(";", 1)[0].trim();
      const audioBlob = (!blob.type || blob.type === "application/octet-stream")
        ? new Blob([blob], {type: normalizedMediaType || "audio/mpeg"})
        : blob;
      state.url = URL.createObjectURL(audioBlob);
      state.audio = new Audio();
      state.audio.preload = "metadata";
      state.audio.src = state.url;
      state.audio.addEventListener("loadedmetadata", () => updateSpeechProgress(state));
      state.audio.addEventListener("durationchange", () => updateSpeechProgress(state));
      state.audio.addEventListener("timeupdate", () => updateSpeechProgress(state));
      state.audio.addEventListener("playing", () => setSpeechState(ui, "playing", "Speaking response"));
      state.audio.addEventListener("pause", () => {
        if (activeSpeech === state && state.audio && !state.audio.ended) {
          setSpeechState(ui, "paused", "Paused");
        }
      });
      state.audio.addEventListener("ended", () => {
        if (activeSpeech !== state) return;
        ui.progress.style.width = "100%";
        ui.elapsed.textContent = formatSpeechTime(state.audio.duration);
        setSpeechState(ui, "complete", "Finished speaking");
        cleanupSpeech(state, true);
        ui.player.dataset.state = "complete";
        ui.wave.hidden = false;
      }, {once: true});
      state.audio.addEventListener("error", () => {
        if (activeSpeech !== state) return;
        cleanupSpeech(state);
        setSpeechState(ui, "error", "Audio playback failed");
      }, {once: true});

      // The provider is fully abstracted behind /v1/tts. Native SDK, Deepgram,
      // OpenAI-compatible endpoints, and registered custom adapters all return
      // the same audio-bytes + media-type contract to this player.
      await state.audio.play();
      if (activeSpeech === state) setSpeechState(ui, "playing", "Speaking response");
      return true;
    } catch (error) {
      if (error?.name === "AbortError") return false;
      if (error?.name === "NotAllowedError" && activeSpeech === state) {
        // Some browsers expire the original click activation while the provider
        // is generating audio. Keep the ready player visible so the visitor can
        // start playback with one explicit tap instead of losing the audio.
        setSpeechState(ui, "ready", "Audio ready — tap play");
        return false;
      }
      if (activeSpeech === state) cleanupSpeech(state);
      setSpeechState(ui, "error", error instanceof Error ? error.message : "Text-to-speech failed");
      return false;
    }
  }

  async function deleteRemoteConversation(id) {
    if (!id) return;
    try {
      await fetch(`${base}/v1/conversations/${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: {"X-API-Key": apiKey},
        keepalive: true,
      });
    } catch {
      // Local chat is still cleared even when the network is unavailable.
    }
  }

  function clearConversation(ask = true) {
    if (busy) {
      showStatus("Please wait for the current reply before deleting the conversation.");
      return;
    }
    if (ask && messages.length && !window.confirm("Delete this entire conversation and start fresh?")) return;
    const oldSessionId = sessionId;
    if (activeSpeech) cleanupSpeech(activeSpeech);
    if (activeRequest) activeRequest.abort();
    sessionId = null;
    messages = [];
    startedAt = null;
    expiresAt = null;
    localStorage.removeItem(storageKey);
    if (oldSessionId) deleteRemoteConversation(oldSessionId);
    showStatus("");
    renderAll();
    updateTimer();
  }

  async function sendMessage(value) {
    const text = value.trim();
    if (!text || busy) return;
    busy = true;
    deleteButton.disabled = true;
    showStatus("");
    beginConversation();
    send.disabled = true;
    input.disabled = true;
    input.value = "";
    input.style.height = "42px";
    updateComposeButton();
    messages.push({role: "user", content: text});
    persist();
    renderAll();
    renderTyping();
    activeRequest = new AbortController();
    let streamedText = "";
    let streamBubble = null;
    let finalData = null;

    const showStreamedText = value => {
      if (!streamBubble) {
        const row = document.createElement("article");
        row.className = "orbit-message assistant";
        const avatar = document.createElement("div");
        avatar.className = "orbit-avatar";
        avatar.innerHTML = iconSvg("bot");
        const content = document.createElement("div");
        content.className = "orbit-message-content";
        streamBubble = document.createElement("div");
        streamBubble.className = "orbit-bubble";
        content.append(streamBubble);
        row.append(avatar, content);
        log.append(row);
      }
      streamBubble.innerHTML = markdown(cleanVisitorText(value));
      scrollLatest();
    };

    try {
      const response = await fetch(`${base}/v1/chat/stream`, {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-API-Key": apiKey},
        body: JSON.stringify({message: text, session_id: sessionId || undefined}),
        signal: activeRequest.signal,
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Request failed (${response.status})`);
      }
      await consumeEventStream(response, (eventName, data) => {
        if (eventName === "progress") {
          updateProcessingLabel(data.label || "Working on your response");
        } else if (eventName === "token") {
          streamedText += String(data.text || "");
          showStreamedText(streamedText);
        } else if (eventName === "done") {
          finalData = data;
        } else if (eventName === "error") {
          throw new Error(data.detail || "The assistant could not complete this request.");
        }
      });
      if (!finalData) throw new Error("The response stream ended before the answer was complete.");
      sessionId = finalData.session_id;
      stopProcessing();
      log.querySelector("#orbit-typing")?.remove();
      const answer = finalData.answer || streamedText || "I could not produce an answer.";
      messages.push({
        role: "assistant",
        content: answer,
        citations: Array.isArray(finalData.citations) ? finalData.citations : [],
      });
      persist();
      renderAll();
    } catch (error) {
      stopProcessing();
      log.querySelector("#orbit-typing")?.remove();
      if (error?.name !== "AbortError") {
        streamBubble?.closest(".orbit-message")?.remove();
        const message = error instanceof Error ? error.message : "The assistant could not complete that request.";
        showStatus(message);
        const row = document.createElement("article");
        row.className = "orbit-message assistant";
        const avatar = document.createElement("div");
        avatar.className = "orbit-avatar";
        avatar.innerHTML = iconSvg("bot");
        const bubble = document.createElement("div");
        bubble.className = "orbit-bubble orbit-error";
        bubble.textContent = "I couldn't complete that request.";
        const retry = makeButton("orbit-retry", "Retry message", "Retry");
        retry.addEventListener("click", () => {
          retry.remove();
          const last = messages[messages.length - 1];
          if (last?.role === "user" && last.content === text) messages.pop();
          persist();
          renderAll();
          sendMessage(text);
        });
        bubble.append(retry);
        row.append(avatar, bubble);
        log.append(row);
        scrollLatest();
      }
    } finally {
      stopProcessing();
      busy = false;
      activeRequest = null;
      deleteButton.disabled = false;
      input.disabled = false;
      updateComposeButton();
      if (!panel.hidden) input.focus();
    }
  }

  function updateComposeButton() {
    send.innerHTML = iconSvg("send");
    send.setAttribute("aria-label", "Send message");
    send.title = "Send message";
    send.disabled = busy || !input.value.trim();
  }

  function togglePanel(open) {
    panel.hidden = !open;
    launcher.setAttribute("aria-expanded", String(open));
    if (open) {
      renderAll();
      input.focus();
      scrollLatest();
    }
  }

  compose.addEventListener("submit", event => {
    event.preventDefault();
    if (input.value.trim()) sendMessage(input.value);
  });
  input.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      compose.requestSubmit();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 110)}px`;
    updateComposeButton();
  });
  launcher.addEventListener("click", () => togglePanel(panel.hidden));
  close.addEventListener("click", () => togglePanel(false));
  shareConversationButton.addEventListener("click", () => shareText(conversationTranscript(), `${assistantName} conversation`));
  deleteButton.addEventListener("click", () => clearConversation(true));

  titleName.textContent = assistantName;
  titleStatus.textContent = "Online assistant";
  updateComposeButton();
  renderAll();
  if (expiredSessionId) deleteRemoteConversation(expiredSessionId);
  loadConfig();
  window.setInterval(updateTimer, 1000);
})();
