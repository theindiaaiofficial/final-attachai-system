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
  let speechConfig = {ttsEnabled: false, sttEnabled: false};
  let voiceMode = false;
  let voiceMuted = false;
  let voiceStateBeforeMute = "listening";
  let voiceState = "idle";
  let voiceSessionToken = 0;
  let micStream = null;
  let mediaRecorder = null;
  let audioChunks = [];
  let recognition = null;
  let voiceAudioContext = null;
  let voiceAnalyser = null;
  let voiceMeterFrame = null;
  let outputAudioContext = null;
  let outputAudioAnalyser = null;
  let outputMeterFrame = null;
  let voiceStartedAt = 0;
  let voiceLastHeardAt = 0;
  let voiceSpeechDetected = false;
  let activeSpeechRequest = null;
  let activeTtsRequest = null;
  let voiceLanguage = null;
  let currentAudio = null;
  let currentAudioUrl = null;

  const ICON_PATHS = {
    orbit: '<circle cx="12" cy="12" r="2.8"/><ellipse cx="12" cy="12" rx="9" ry="4.2" transform="rotate(-32 12 12)"/><circle cx="19.2" cy="6.1" r="1.2"/>',
    bot: '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01M9 17h6"/><path d="M8 4h4"/>',
    user: '<circle cx="12" cy="8" r="3.4"/><path d="M5 20c.5-3.3 3.1-5.2 7-5.2s6.5 1.9 7 5.2"/>',
    message: '<path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2v-6.5A7.5 7.5 0 1 1 20 11.5Z"/>',
    share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.7 10.6 6.6-4.1M8.7 13.4l6.6 4.1"/>',
    close: '<path d="m18 6-12 12M6 6l12 12"/>',
    trash: '<path d="M3 6h18M8 6V4h8v2m3 0-1 14H6L5 6m4 4v6m6-6v6"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    mic: '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3m-4 0h8"/>',
    micOff: '<path d="m3 3 18 18M9 9v3a3 3 0 0 0 5.1 2.1M15 9V6a3 3 0 0 0-5.8-1M5 11a7 7 0 0 0 12 4.9M12 18v3m-4 0h8"/>',
    minus: '<path d="M5 12h14"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    thumbsUp: '<path d="M7 10v10H4V10h3Zm0 9h9.2a2 2 0 0 0 1.9-1.4l1.4-5A2 2 0 0 0 17.6 10H13l.7-3.2A2.2 2.2 0 0 0 11.5 4L7 10v9Z"/>',
    thumbsDown: '<path d="M7 14V4H4v10h3Zm0-9h9.2a2 2 0 0 1 1.9 1.4l1.4 5a2 2 0 0 1-1.9 2.6H13l.7 3.2a2.2 2.2 0 0 1-2.2 2.8L7 14V5Z"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    volume: '<path d="M4 10v4h4l5 4V6l-5 4H4Z"/><path d="M17 9a5 5 0 0 1 0 6m2-9a9 9 0 0 1 0 12"/>',
    send: '<path d="m21 3-7.2 18-3.4-7.4L3 10.2 21 3Z"/><path d="M10.4 13.6 21 3"/>',
    audio: '<path d="M3 10v4m4-7v10m4-13v16m4-13v10m4-7v4m3-6v8"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    phoneOff: '<path d="m3 3 18 18M7.4 7.4a14.5 14.5 0 0 0 9.2 9.2M5.2 5.2A15.5 15.5 0 0 0 4 12c0 4.4 3.6 8 8 8 1.1 0 2.2-.2 3.2-.7M18.8 18.8A15.5 15.5 0 0 0 20 12c0-1.1-.2-2.2-.7-3.2"/>',
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
  launcher.innerHTML = `${iconSvg("message")}<span>Chat with us</span>`;
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

  const voicePanel = document.createElement("div");
  voicePanel.className = "orbit-voice-panel";
  voicePanel.hidden = true;
  voicePanel.dataset.state = "idle";
  const voiceTopline = document.createElement("div");
  voiceTopline.className = "orbit-voice-topline";
  const voiceLiveBadge = document.createElement("span");
  voiceLiveBadge.className = "orbit-voice-live-badge";
  voiceLiveBadge.textContent = "LIVE VOICE";
  const voicePrivacy = document.createElement("span");
  voicePrivacy.className = "orbit-voice-privacy";
  voicePrivacy.textContent = "VOICE SESSION";
  voiceTopline.append(voiceLiveBadge, voicePrivacy);

  const voiceStage = document.createElement("div");
  voiceStage.className = "orbit-voice-stage";
  const voiceOrb = document.createElement("div");
  voiceOrb.className = "orbit-voice-orb";
  voiceOrb.setAttribute("aria-hidden", "true");
  const voiceRingOuter = document.createElement("span");
  voiceRingOuter.className = "orbit-orb-ring orbit-orb-ring-outer";
  const voiceRingInner = document.createElement("span");
  voiceRingInner.className = "orbit-orb-ring orbit-orb-ring-inner";
  const voiceCore = document.createElement("span");
  voiceCore.className = "orbit-orb-core";
  const voiceAnimation = document.createElement("span");
  voiceAnimation.className = "orbit-waveform";
  for (let index = 0; index < 25; index += 1) {
    const bar = document.createElement("i");
    bar.style.setProperty("--bar-delay", `${index * -31}ms`);
    bar.style.setProperty("--bar-height", `${Math.round(6 + Math.abs(Math.sin(index * 0.82)) * 10)}px`);
    voiceAnimation.append(bar);
  }
  voiceCore.append(voiceAnimation);
  voiceOrb.append(voiceRingOuter, voiceRingInner, voiceCore);

  const voiceInfo = document.createElement("div");
  voiceInfo.className = "orbit-voice-info";
  const voiceStatus = document.createElement("strong");
  voiceStatus.textContent = "Ready when you are";
  voiceStatus.setAttribute("aria-live", "polite");
  const micStatus = document.createElement("span");
  micStatus.textContent = "Speak naturally. I’ll respond when you pause.";
  micStatus.setAttribute("aria-live", "polite");
  voiceInfo.append(voiceStatus, micStatus);

  const voiceTranscript = document.createElement("div");
  voiceTranscript.className = "orbit-voice-transcript";
  voiceTranscript.setAttribute("aria-live", "polite");
  const voiceTranscriptLabel = document.createElement("span");
  voiceTranscriptLabel.textContent = "YOU";
  const voiceTranscriptText = document.createElement("p");
  voiceTranscriptText.textContent = "Your words will appear here";
  voiceTranscript.append(voiceTranscriptLabel, voiceTranscriptText);

  const voiceReply = document.createElement("div");
  voiceReply.className = "orbit-voice-reply";
  voiceReply.setAttribute("aria-live", "polite");
  const voiceReplyLabel = document.createElement("span");
  voiceReplyLabel.textContent = "ASSISTANT";
  const voiceReplyText = document.createElement("p");
  voiceReplyText.textContent = "Your assistant’s reply will appear here";
  voiceReply.append(voiceReplyLabel, voiceReplyText);
  voiceStage.append(voiceOrb, voiceInfo, voiceTranscript, voiceReply);

  const voiceActions = document.createElement("div");
  voiceActions.className = "orbit-voice-actions";
  const muteButton = makeButton("orbit-voice-control", "Mute microphone", "mic");
  const interruptButton = makeButton("orbit-voice-interrupt", "Interrupt assistant", "pause");
  const minimizeVoiceButton = makeButton("orbit-voice-control", "Minimize voice chat", "minus");
  const stopVoiceButton = makeButton("orbit-voice-stop", "End voice conversation", "phoneOff");
  voiceActions.append(muteButton, interruptButton, minimizeVoiceButton, stopVoiceButton);
  voicePanel.append(voiceTopline, voiceStage, voiceActions);

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
  panel.append(head, timerBar, voicePanel, log, status, compose);
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
      const actions = document.createElement("div");
      actions.className = "orbit-message-actions";
      const like = makeButton("orbit-message-action", "Like response", "thumbsUp");
      const copy = makeButton("orbit-message-action", "Copy response", "copy");
      const dislike = makeButton("orbit-message-action", "Dislike response", "thumbsDown");
      const share = makeButton("orbit-message-action", "Share response", "share");
      const speak = makeButton("orbit-message-action", "Speak response", "volume");
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
      speak.addEventListener("click", () => speakText(cleanVisitorText(item.content)));
      actions.append(like, copy, dislike, share, speak);
      contentWrap.append(actions);
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

    const phases = [
      "Understanding your question",
      "Reviewing relevant context",
      "Preparing a helpful response",
    ];
    let phase = 0;
    processingInterval = window.setInterval(() => {
      phase = (phase + 1) % phases.length;
      label.textContent = phases[phase];
    }, 1900);
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

  function releaseCurrentAudio(audio = currentAudio) {
    if (audio && audio === currentAudio) currentAudio = null;
    stopOutputMeter();
    if (currentAudioUrl) {
      URL.revokeObjectURL(currentAudioUrl);
      currentAudioUrl = null;
    }
  }

  async function startOutputMeter(audio) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass || !audio) return;
    try {
      outputAudioContext = new AudioContextClass();
      if (outputAudioContext.state === "suspended") await outputAudioContext.resume();
      outputAudioAnalyser = outputAudioContext.createAnalyser();
      outputAudioAnalyser.fftSize = 256;
      outputAudioAnalyser.smoothingTimeConstant = 0.2;
      const source = outputAudioContext.createMediaElementSource(audio);
      source.connect(outputAudioAnalyser);
      outputAudioAnalyser.connect(outputAudioContext.destination);
      const samples = new Float32Array(outputAudioAnalyser.fftSize);
      const measure = () => {
        if (!outputAudioAnalyser || audio !== currentAudio) {
          outputMeterFrame = null;
          return;
        }
        outputAudioAnalyser.getFloatTimeDomainData(samples);
        let energy = 0;
        for (let index = 0; index < samples.length; index += 1) energy += samples[index] * samples[index];
        updateVoiceLevel(Math.min(1, Math.sqrt(energy / samples.length) * 9));
        outputMeterFrame = window.requestAnimationFrame(measure);
      };
      outputMeterFrame = window.requestAnimationFrame(measure);
    } catch {
      stopOutputMeter();
    }
  }

  function stopOutputMeter() {
    if (outputMeterFrame !== null) window.cancelAnimationFrame(outputMeterFrame);
    outputMeterFrame = null;
    outputAudioAnalyser = null;
    if (outputAudioContext) {
      const context = outputAudioContext;
      outputAudioContext = null;
      try { context.close().catch(() => {}); } catch { /* context may already be closed */ }
    }
    if (voiceState !== "listening") updateVoiceLevel(0);
  }

  function cancelCurrentSpeech() {
    if (activeTtsRequest) {
      activeTtsRequest.abort();
      activeTtsRequest = null;
    }
    stopOutputMeter();
    if (currentAudio) {
      const audio = currentAudio;
      currentAudio = null;
      try { audio.pause(); } catch { /* playback may already be stopped */ }
    }
    if (currentAudioUrl) {
      URL.revokeObjectURL(currentAudioUrl);
      currentAudioUrl = null;
    }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }

  async function speakText(text, options = {}) {
    cancelCurrentSpeech();
    const liveVoice = options.liveVoice === true;
    const waitForEnd = options.waitForEnd === true;
    const language = options.language || voiceLanguage || null;

    if (speechConfig.ttsEnabled) {
      const controller = new AbortController();
      activeTtsRequest = controller;
      try {
        const response = await fetch(`${base}/v1/tts`, {
          method: "POST",
          headers: {"Content-Type": "application/json", "X-API-Key": apiKey},
          body: JSON.stringify({text, language}),
          signal: controller.signal,
        });
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `TTS request failed (${response.status})`);
        }
        const blob = await response.blob();
        if (controller.signal.aborted || (liveVoice && !voiceMode)) return false;
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        currentAudioUrl = url;
        currentAudio = audio;
        if (liveVoice) {
          voiceState = "speaking";
          setVoiceUi("Speaking…", "Assistant is responding");
          await startOutputMeter(audio);
          if (!voiceMode) return false;
        }

        let settlePlayback;
        const playbackFinished = new Promise(resolve => { settlePlayback = resolve; });
        let settled = false;
        const finishPlayback = played => {
          if (settled) return;
          settled = true;
          if (audio === currentAudio) releaseCurrentAudio(audio);
          settlePlayback(played);
        };
        audio.addEventListener("ended", () => finishPlayback(true), {once: true});
        audio.addEventListener("error", () => finishPlayback(false), {once: true});
        audio.addEventListener("pause", () => {
          if (!audio.ended) finishPlayback(false);
        }, {once: true});
        await audio.play();
        if (activeTtsRequest === controller) activeTtsRequest = null;
        if (waitForEnd) return await playbackFinished;
        return true;
      } catch (error) {
        if (activeTtsRequest === controller) activeTtsRequest = null;
        if (error?.name !== "AbortError") {
          if (liveVoice) {
            voiceStatus.textContent = "Voice playback unavailable";
            micStatus.textContent = "Please check the audio output and try again";
          }
          showStatus("Text-to-speech could not play this response.");
        }
        return false;
      }
    }

    if (window.speechSynthesis && window.SpeechSynthesisUtterance) {
      const utterance = new SpeechSynthesisUtterance(cleanVisitorText(text));
      utterance.lang = language || document.documentElement.lang || navigator.language || "en-US";
      if (liveVoice) {
        voiceState = "speaking";
        setVoiceUi("Speaking…", "Assistant is responding");
      }
      if (!waitForEnd) {
        window.speechSynthesis.speak(utterance);
        return true;
      }
      return await new Promise(resolve => {
        utterance.onend = () => resolve(true);
        utterance.onerror = () => resolve(false);
        window.speechSynthesis.speak(utterance);
      });
    }

    showStatus("Text-to-speech is not supported in this browser.");
    return false;
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
    if (voiceMode) finishVoice();
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

  async function sendMessage(value, options = {}) {
    const text = value.trim();
    if (!text || busy) return;
    const liveVoice = options.voice === true;
    const sessionToken = options.sessionToken ?? voiceSessionToken;
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
    try {
      const response = await fetch(`${base}/v1/chat`, {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-API-Key": apiKey},
        body: JSON.stringify({message: text, session_id: sessionId || undefined}),
        signal: activeRequest.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
      sessionId = data.session_id;
      stopProcessing();
      log.querySelector("#orbit-typing")?.remove();
      const answer = data.answer || "I could not produce an answer.";
      if (liveVoice) {
        voiceReplyText.textContent = cleanVisitorText(answer);
      } else {
        await revealAssistantMessage(answer);
      }
      messages.push({
        role: "assistant",
        content: answer,
        citations: Array.isArray(data.citations) ? data.citations : [],
      });
      persist();
      renderAll();
      if (liveVoice && voiceMode && sessionToken === voiceSessionToken) {
        await speakText(answer, {language: options.language || voiceLanguage, liveVoice: true, waitForEnd: true});
        if (voiceMode && sessionToken === voiceSessionToken) {
          if (!voiceMuted) {
            await continueVoiceListening();
          } else {
            voiceState = "muted";
            voiceStateBeforeMute = "listening";
            setVoiceUi("Microphone muted", "Unmute to continue the conversation");
          }
        }
      }
    } catch (error) {
      stopProcessing();
      log.querySelector("#orbit-typing")?.remove();
      if (error?.name !== "AbortError") {
        const message = error instanceof Error ? error.message : "The assistant could not complete that request.";
        showStatus(message);
        if (liveVoice && voiceMode && sessionToken === voiceSessionToken) {
          voiceState = "error";
          setVoiceUi("I couldn’t complete that", "Please try speaking again");
          window.setTimeout(() => {
            if (voiceMode && sessionToken === voiceSessionToken && !voiceMuted && !busy) continueVoiceListening();
          }, 1400);
        }
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
      send.disabled = false;
      input.disabled = false;
      updateComposeButton();
      if (!panel.hidden && !voiceMode) input.focus();
    }
  }

  function updateComposeButton() {
    if (input.value.trim()) {
      send.innerHTML = iconSvg("send");
      send.setAttribute("aria-label", "Send message");
      send.title = "Send message";
    } else {
      send.innerHTML = iconSvg(voiceMode ? "phoneOff" : "audio");
      send.setAttribute("aria-label", voiceMode ? "End voice conversation" : "Start live voice conversation");
      send.title = voiceMode ? "End voice conversation" : "Start live voice conversation";
    }
  }

  function setVoiceUi(message, permission) {
    voicePanel.hidden = !voiceMode;
    voicePanel.dataset.state = voiceState;
    if (message) voiceStatus.textContent = message;
    if (permission) micStatus.textContent = permission;
    muteButton.innerHTML = iconSvg(voiceMuted ? "micOff" : "mic");
    muteButton.setAttribute("aria-label", voiceMuted ? "Unmute microphone" : "Mute microphone");
    muteButton.title = voiceMuted ? "Unmute microphone" : "Mute microphone";
    interruptButton.disabled = voiceState !== "speaking";
    interruptButton.setAttribute("aria-label", "Interrupt assistant and speak");
    interruptButton.title = voiceState === "speaking" ? "Interrupt assistant and speak" : "Interrupt available while assistant is speaking";
    launcher.classList.toggle("voice-active", voiceMode && panel.hidden);
    launcher.classList.toggle("voice-muted", voiceMode && voiceMuted);
    launcher.innerHTML = voiceMode && panel.hidden
      ? `<span class="orbit-launcher-wave">${iconSvg("audio")}</span><span class="orbit-launcher-mic">${iconSvg("mic")}</span><i class="orbit-mic-dot"></i>`
      : `${iconSvg("message")}<span>Chat with us</span>`;
    launcher.setAttribute("aria-label", voiceMode && panel.hidden ? "Return to active voice chat" : "Open chat");
    updateComposeButton();
  }

  function updateVoiceLevel(level) {
    const normalized = Math.max(0, Math.min(1, level));
    voiceOrb.style.setProperty("--voice-level", normalized.toFixed(3));
    voiceOrb.style.setProperty("--orb-scale", (1 + normalized * 0.035).toFixed(3));
  }

  function startVoiceMeter() {
    if (!voiceAnalyser || voiceMeterFrame !== null) return;
    const samples = new Float32Array(voiceAnalyser.fftSize);
    const measure = () => {
      if (!voiceMode || !voiceAnalyser) {
        voiceMeterFrame = null;
        return;
      }
      voiceAnalyser.getFloatTimeDomainData(samples);
      let energy = 0;
      for (let index = 0; index < samples.length; index += 1) energy += samples[index] * samples[index];
      const rms = Math.sqrt(energy / samples.length);

      if (voiceState === "listening" && mediaRecorder?.state === "recording" && !voiceMuted) {
        updateVoiceLevel(Math.min(1, rms * 7));
        const now = Date.now();
        if (rms > 0.018) {
          voiceSpeechDetected = true;
          voiceLastHeardAt = now;
          if (voiceStatus.textContent !== "Listening…") voiceStatus.textContent = "Listening…";
        }
        if (voiceSpeechDetected && now - voiceLastHeardAt > 1150 && now - voiceStartedAt > 650) {
          stopVoiceRecording();
        } else if (now - voiceStartedAt > 25000) {
          stopVoiceRecording();
        } else if (!voiceSpeechDetected && now - voiceStartedAt > 15000) {
          stopVoiceRecording();
        }
      } else if (voiceState !== "speaking") {
        updateVoiceLevel(0);
      }
      voiceMeterFrame = window.requestAnimationFrame(measure);
    };
    voiceMeterFrame = window.requestAnimationFrame(measure);
  }

  async function setupVoiceMeter() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass || !micStream) return;
    try {
      voiceAudioContext = new AudioContextClass();
      if (voiceAudioContext.state === "suspended") await voiceAudioContext.resume();
      voiceAnalyser = voiceAudioContext.createAnalyser();
      voiceAnalyser.fftSize = 512;
      voiceAnalyser.smoothingTimeConstant = 0.18;
      const source = voiceAudioContext.createMediaStreamSource(micStream);
      source.connect(voiceAnalyser);
      startVoiceMeter();
    } catch {
      voiceAnalyser = null;
      voiceStatus.textContent = "Listening… pause briefly when you finish";
    }
  }

  function stopVoiceMeter() {
    if (voiceMeterFrame !== null) window.cancelAnimationFrame(voiceMeterFrame);
    voiceMeterFrame = null;
    voiceAnalyser = null;
    if (voiceAudioContext) {
      const context = voiceAudioContext;
      voiceAudioContext = null;
      try { context.close().catch(() => {}); } catch { /* context may already be closed */ }
    }
    updateVoiceLevel(0);
  }

  function stopMicrophoneTracks() {
    const recorder = mediaRecorder;
    if (recorder && recorder.state === "recording") {
      recorder._orbitDiscard = true;
      try { recorder.stop(); } catch { /* recorder may already be stopping */ }
    }
    mediaRecorder = null;
    if (micStream) micStream.getTracks().forEach(track => track.stop());
    micStream = null;
    audioChunks = [];
    stopVoiceMeter();
  }

  function finishVoice() {
    voiceSessionToken += 1;
    voiceMode = false;
    voiceMuted = false;
    voiceState = "idle";
    voiceStateBeforeMute = "listening";
    if (activeSpeechRequest) {
      activeSpeechRequest.abort();
      activeSpeechRequest = null;
    }
    if (recognition) {
      const recognizer = recognition;
      recognition = null;
      try { recognizer.onend = null; recognizer.stop(); } catch { /* already stopped */ }
    }
    cancelCurrentSpeech();
    stopMicrophoneTracks();
    setVoiceUi("Voice conversation ended", "Microphone off");
    window.setTimeout(() => {
      if (!voiceMode) {
        voiceStatus.textContent = "Ready when you are";
        micStatus.textContent = "Speak naturally. I’ll respond when you pause.";
      }
    }, 900);
  }

  function stopVoiceRecording() {
    if (mediaRecorder?.state === "recording") {
      try { mediaRecorder.stop(); } catch { /* recorder may already be stopping */ }
    }
  }

  function inferLanguageFromText(text) {
    return /[\u0900-\u097F]/.test(text) ? "hi" : null;
  }

  async function handleVoiceRecording(recorder, chunks, sessionToken) {
    if (!voiceMode || sessionToken !== voiceSessionToken || recorder._orbitDiscard) return;
    mediaRecorder = null;
    const mime = recorder.mimeType || chunks[0]?.type || "audio/webm";
    const extension = mime.includes("mp4") ? "m4a" : mime.includes("ogg") ? "ogg" : "webm";
    const blob = new Blob(chunks, {type: mime});
    if (!blob.size) {
      voiceState = "error";
      setVoiceUi("I didn’t catch that", "Please speak a little louder");
      window.setTimeout(() => continueVoiceListening(), 900);
      return;
    }

    voiceState = "thinking";
    setVoiceUi("Understanding you…", "Turning your speech into text");
    const controller = new AbortController();
    activeSpeechRequest = controller;
    try {
      const form = new FormData();
      form.append("file", blob, `recording.${extension}`);
      const response = await fetch(`${base}/v1/stt`, {
        method: "POST",
        headers: {"X-API-Key": apiKey},
        body: form,
        signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Speech recognition failed.");
      const transcript = String(data.text || "").trim();
      if (!transcript) throw new Error("No speech was detected. Please try again.");
      voiceLanguage = data.language || inferLanguageFromText(transcript);
      voiceTranscriptText.textContent = transcript;
      await sendMessage(transcript, {voice: true, language: voiceLanguage, sessionToken});
    } catch (error) {
      if (error?.name !== "AbortError" && voiceMode && sessionToken === voiceSessionToken) {
        voiceState = "error";
        setVoiceUi("I couldn’t hear that clearly", error instanceof Error ? error.message : "Please try again");
        window.setTimeout(() => {
          if (voiceMode && sessionToken === voiceSessionToken && !voiceMuted && !busy) continueVoiceListening();
        }, 1500);
      }
    } finally {
      if (activeSpeechRequest === controller) activeSpeechRequest = null;
    }
  }

  function startRecorderTurn() {
    if (!voiceMode || voiceMuted || !micStream) return;
    if (mediaRecorder?.state === "recording") return;
    const preferred = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(type => MediaRecorder.isTypeSupported(type));
    const recorder = preferred ? new MediaRecorder(micStream, {mimeType: preferred}) : new MediaRecorder(micStream);
    const chunks = [];
    const sessionToken = voiceSessionToken;
    mediaRecorder = recorder;
    voiceStartedAt = Date.now();
    voiceLastHeardAt = 0;
    voiceSpeechDetected = false;
    recorder.addEventListener("dataavailable", event => {
      if (event.data?.size) chunks.push(event.data);
    });
    recorder.addEventListener("stop", () => {
      if (recorder._orbitFallbackTimer) window.clearTimeout(recorder._orbitFallbackTimer);
      void handleVoiceRecording(recorder, chunks, sessionToken);
    }, {once: true});
    recorder.addEventListener("error", () => {
      if (sessionToken === voiceSessionToken && voiceMode) {
        voiceState = "error";
        setVoiceUi("Microphone issue", "Please check your microphone and try again");
      }
    }, {once: true});
    recorder.start(250);
    if (!voiceAnalyser) {
      recorder._orbitFallbackTimer = window.setTimeout(() => {
        if (recorder.state === "recording") stopVoiceRecording();
      }, 12000);
    }
    voiceState = "listening";
    setVoiceUi("Listening…", "Speak naturally. I’ll respond when you pause.");
    if (voiceAnalyser) startVoiceMeter();
  }

  async function startRemoteVoice() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      throw new Error("Audio recording is not supported in this browser. Try Chrome on HTTPS.");
    }
    setVoiceUi("Connecting microphone…", "Allow microphone access to start");
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true},
    });
    await setupVoiceMeter();
    startRecorderTurn();
  }

  function startBrowserVoice() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      throw new Error("Speech-to-text is not configured and this browser has no built-in speech recognition.");
    }
    if (!voiceMode || voiceMuted || recognition) return;
    const recognizer = new SpeechRecognition();
    const sessionToken = voiceSessionToken;
    recognition = recognizer;
    recognizer.lang = navigator.language || "en-US";
    recognizer.continuous = false;
    recognizer.interimResults = true;
    let transcript = "";
    voiceState = "listening";
    setVoiceUi("Listening…", "Speak naturally. I’ll respond when you pause.");
    recognizer.onresult = event => {
      let interim = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const part = event.results[index][0].transcript;
        if (event.results[index].isFinal) transcript += `${part} `;
        else interim += part;
      }
      voiceTranscriptText.textContent = (transcript + interim).trim() || "Listening…";
    };
    recognizer.onerror = event => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        finishVoice();
        showStatus("Microphone permission was denied. Allow microphone access in Chrome site settings.");
      }
    };
    recognizer.onend = async () => {
      if (recognition !== recognizer) return;
      recognition = null;
      if (!voiceMode || sessionToken !== voiceSessionToken || voiceMuted) return;
      const text = transcript.trim();
      if (text) {
        voiceLanguage = inferLanguageFromText(text) || recognizer.lang;
        voiceTranscriptText.textContent = text;
        await sendMessage(text, {voice: true, language: voiceLanguage, sessionToken});
      } else {
        setVoiceUi("I’m still listening", "Say something whenever you’re ready");
        window.setTimeout(() => {
          if (voiceMode && sessionToken === voiceSessionToken && !voiceMuted && !busy) continueVoiceListening();
        }, 500);
      }
    };
    recognizer.start();
  }

  async function continueVoiceListening() {
    if (!voiceMode || voiceMuted || !micStream && speechConfig.sttEnabled) return;
    if (mediaRecorder?.state === "recording" || recognition) return;
    try {
      if (speechConfig.sttEnabled) startRecorderTurn();
      else startBrowserVoice();
    } catch (error) {
      voiceState = "error";
      setVoiceUi("Microphone unavailable", error instanceof Error ? error.message : "Please try again");
    }
  }

  async function startVoice() {
    if (busy || voiceMode) return;
    showStatus("");
    voiceSessionToken += 1;
    voiceLanguage = null;
    voiceTranscriptText.textContent = "Your words will appear here";
    voiceReplyText.textContent = "Your assistant’s reply will appear here";
    voiceMode = true;
    voiceMuted = false;
    voiceState = "listening";
    setVoiceUi("Starting live voice…", "Connecting securely to your microphone");
    try {
      if (speechConfig.sttEnabled) await startRemoteVoice();
      else startBrowserVoice();
    } catch (error) {
      finishVoice();
      showStatus(error instanceof Error ? error.message : "Could not start voice input.");
    }
  }

  function toggleVoice() {
    if (voiceMode) finishVoice();
    else void startVoice();
  }

  function toggleMute() {
    if (!voiceMode) return;
    const previousState = voiceState;
    voiceMuted = !voiceMuted;
    if (micStream) micStream.getAudioTracks().forEach(track => { track.enabled = !voiceMuted; });
    if (voiceMuted) {
      if (mediaRecorder?.state === "recording") {
        mediaRecorder._orbitDiscard = true;
        stopVoiceRecording();
      }
      if (recognition) {
        const recognizer = recognition;
        recognition = null;
        try { recognizer.onend = null; recognizer.stop(); } catch { /* already stopped */ }
      }
      voiceState = "muted";
      setVoiceUi("Microphone muted", "Your microphone is paused");
    } else {
      if (voiceStateBeforeMute === "speaking" || previousState === "speaking") {
        voiceState = "speaking";
        setVoiceUi("Speaking…", "Assistant is responding · tap interrupt to speak");
      } else if (voiceStateBeforeMute === "thinking" || previousState === "thinking") {
        voiceState = "thinking";
        setVoiceUi("Thinking…", "Microphone active · listening starts after the reply");
      } else {
        voiceState = "listening";
        setVoiceUi("Listening…", "Microphone active");
        if (!busy) void continueVoiceListening();
      }
    }
    if (voiceMuted) voiceStateBeforeMute = previousState;
  }

  function interruptAssistant() {
    if (!voiceMode || voiceState !== "speaking") return;
    cancelCurrentSpeech();
    voiceState = "listening";
    setVoiceUi("Your turn…", "Go ahead. I’m listening");
    void continueVoiceListening();
  }

  function togglePanel(open) {
    panel.hidden = !open;
    launcher.setAttribute("aria-expanded", String(open));
    setVoiceUi(voiceStatus.textContent, micStatus.textContent);
    if (open) {
      renderAll();
      if (!voiceMode) input.focus();
      scrollLatest();
    }
  }

  compose.addEventListener("submit", event => {
    event.preventDefault();
    if (input.value.trim()) sendMessage(input.value);
    else toggleVoice();
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
  stopVoiceButton.addEventListener("click", () => toggleVoice());
  muteButton.addEventListener("click", toggleMute);
  interruptButton.addEventListener("click", interruptAssistant);
  minimizeVoiceButton.addEventListener("click", () => togglePanel(false));

  titleName.textContent = assistantName;
  titleStatus.textContent = "Online assistant";
  updateComposeButton();
  renderAll();
  if (expiredSessionId) deleteRemoteConversation(expiredSessionId);
  loadConfig();
  window.setInterval(updateTimer, 1000);
})();
