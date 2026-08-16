/* ============================================================
 * Virtual Being · Web 聊天界面逻辑（M5 形象）
 * 原生 JS，无框架依赖；只接真实后端契约（/chat、/chat/voice）。
 * - 表情状态机：default / thinking / speaking / happy
 * - 文本：POST /chat；语音：MediaRecorder → POST /chat/voice → 播放回复音频
 * ============================================================ */
(() => {
  "use strict";

  const PORTRAIT   = document.getElementById("portrait");
  const STATE_TEXT = document.getElementById("state-text");
  const STATE_BADGE = document.getElementById("state-badge");
  const MESSAGES   = document.getElementById("messages");
  const FORM       = document.getElementById("chat-form");
  const INPUT      = document.getElementById("input");
  const SEND_BTN   = document.getElementById("send-btn");
  const VOICE_BTN  = document.getElementById("voice-btn");
  const VOICE_HINT = document.getElementById("voice-hint");

  const API_CHAT  = "/chat";
  const API_VOICE = "/chat/voice";

  const STATE_LABELS = {
    default: "默认",
    thinking: "思考中",
    speaking: "说话中",
    happy: "开心",
  };

  const SESSION_KEY = "vb_session_id";
  const MAX_RECORD_MS = 15000; // 录音上限，防止误按
  const HAPPY_DWELL_MS = 2200; // 开心表情停留时长

  let sessionId = localStorage.getItem(SESSION_KEY) || "";
  let busy = false;          // 请求互斥，避免并发错乱
  let recorder = null;       // MediaRecorder
  let chunks = [];           // 录音分片
  let recording = false;
  let recordTimer = null;
  let audioEl = null;        // 回复音频播放器

  /* ---------- 表情状态机 ---------- */
  function setState(state) {
    if (!STATE_LABELS[state]) state = "default";
    PORTRAIT.dataset.state = state;
    STATE_TEXT.textContent = STATE_LABELS[state];
    STATE_BADGE.classList.toggle("hidden", state === "default");
  }

  /* ---------- 会话 id（浏览器端生成，服务端会延续/返回） ---------- */
  function ensureSession() {
    if (!sessionId) {
      sessionId =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : "s-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
      localStorage.setItem(SESSION_KEY, sessionId);
    }
    return sessionId;
  }

  /* ---------- 消息渲染（textContent 防注入） ---------- */
  function addMessage(role, text) {
    const wrap = document.createElement("div");
    wrap.className = "msg " + role;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    wrap.appendChild(bubble);
    MESSAGES.appendChild(wrap);
    MESSAGES.scrollTop = MESSAGES.scrollHeight;
    return bubble;
  }

  /** 逐字显示回复，营造"说话"感；用户偏好减弱动画时直接显示。 */
  async function typeReply(bubble, text) {
    const reduced =
      window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || text.length <= 2) {
      bubble.textContent = text;
      return;
    }
    setState("speaking");
    const step = text.length > 120 ? 2 : 1;
    for (let i = 0; i <= text.length; i += step) {
      bubble.textContent = text.slice(0, i);
      await new Promise((r) => setTimeout(r, 16));
    }
    bubble.textContent = text;
  }

  /** 收到完整回复后：开心 → 短暂停留 → 回到默认。 */
  function happyBriefly() {
    setState("happy");
    setTimeout(() => {
      if (PORTRAIT.dataset.state === "happy") setState("default");
    }, HAPPY_DWELL_MS);
  }

  /* ---------- 文本对话 ---------- */
  async function sendText(query) {
    if (!query.trim() || busy) return;
    busy = true;
    SEND_BTN.disabled = true;
    addMessage("user", query.trim());
    INPUT.value = "";
    autoResize();
    setState("thinking");
    try {
      const resp = await fetch(API_CHAT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), session_id: ensureSession() }),
      });
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        throw new Error(detail.detail || ("HTTP " + resp.status));
      }
      const data = await resp.json();
      sessionId = data.session_id || sessionId;
      localStorage.setItem(SESSION_KEY, sessionId);
      const bubble = addMessage("bot", "");
      await typeReply(bubble, data.reply);
      happyBriefly();
    } catch (err) {
      setState("default");
      addMessage("error", "TA 好像走神了… " + err.message + "，请稍后再试～");
    } finally {
      busy = false;
      SEND_BTN.disabled = false;
      INPUT.focus();
    }
  }

  /* ---------- 语音：按住说话 ---------- */
  const hasRecorder = typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices;

  function initVoice() {
    if (hasRecorder) return;
    VOICE_BTN.disabled = true;
    VOICE_BTN.title = "当前浏览器不支持录音";
    VOICE_HINT.textContent = "当前浏览器不支持录音，可改用文字输入～";
  }

  async function startRecording() {
    if (recording || busy || !hasRecorder) return;
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      addMessage("error", "麦克风权限被拒绝，无法录音（" + err.name + "）");
      return;
    }
    chunks = [];
    try {
      recorder = new MediaRecorder(stream);
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop());
      addMessage("error", "当前浏览器不支持录音编码，请更换 Chrome/Edge 试试～");
      return;
    }
    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunks.push(ev.data);
    };
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      sendVoice();
    };
    recorder.start();
    recording = true;
    VOICE_BTN.classList.add("recording");
    VOICE_BTN.title = "正在聆听… 松开发送";
    VOICE_HINT.textContent = "正在聆听… 松开发送";
    setState("thinking");
    recordTimer = setTimeout(stopRecording, MAX_RECORD_MS);
  }

  function stopRecording() {
    if (!recording) return;
    recording = false;
    clearTimeout(recordTimer);
    VOICE_BTN.classList.remove("recording");
    VOICE_BTN.title = "按住说话";
    VOICE_HINT.textContent = "按住 🎙 说话，松开发送";
    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
      } catch (e) {
        /* 已停止则忽略 */
      }
    }
  }

  /** 录音结束后上传 /chat/voice 并播放回复音频。 */
  async function sendVoice() {
    if (!chunks.length) {
      setState("default");
      return;
    }
    busy = true;
    const mimeType = recorder && recorder.mimeType ? recorder.mimeType : "audio/webm";
    const blob = new Blob(chunks, { type: mimeType });
    const fd = new FormData();
    fd.append("file", blob, "voice.webm");
    fd.append("session_id", ensureSession());
    setState("thinking");
    try {
      const resp = await fetch(API_VOICE, { method: "POST", body: fd });
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        throw new Error(detail.detail || ("HTTP " + resp.status));
      }
      const data = await resp.json();
      sessionId = data.session_id || sessionId;
      localStorage.setItem(SESSION_KEY, sessionId);
      addMessage("user", "🎤 " + (data.text || "（语音输入）"));
      const bubble = addMessage("bot", "");
      await typeReply(bubble, data.reply);
      playReplyAudio(data.audio_url);
    } catch (err) {
      setState("default");
      addMessage("error", "语音没听清… " + err.message + "，请再试一次～");
    } finally {
      busy = false;
    }
  }

  /* ---------- 播放回复音频 ---------- */
  function stopCurrentAudio() {
    if (audioEl) {
      audioEl.onended = null;
      audioEl.onerror = null;
      try { audioEl.pause(); } catch (e) { /* 忽略 */ }
      audioEl = null;
    }
  }

  function playReplyAudio(url) {
    if (!url) return;
    stopCurrentAudio();
    audioEl = new Audio(url);
    audioEl.onplay = () => setState("speaking");
    audioEl.onended = () => happyBriefly();
    audioEl.onerror = () => setState("default");
    audioEl.play().catch(() => {
      /* 自动播放被浏览器拦截时：文字已显示，表情回默认即可 */
      setState("default");
    });
  }

  /* ---------- 输入框自适应高度 ---------- */
  function autoResize() {
    INPUT.style.height = "auto";
    INPUT.style.height = Math.min(INPUT.scrollHeight, 120) + "px";
  }

  /* ---------- 事件绑定 ---------- */
  FORM.addEventListener("submit", (ev) => {
    ev.preventDefault();
    sendText(INPUT.value);
  });

  INPUT.addEventListener("input", autoResize);
  INPUT.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      FORM.requestSubmit();
    }
  });

  // 按住说话：指针（鼠标/触屏）与键盘均支持
  VOICE_BTN.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    startRecording();
  });
  VOICE_BTN.addEventListener("pointerup", stopRecording);
  VOICE_BTN.addEventListener("pointercancel", stopRecording);
  VOICE_BTN.addEventListener("pointerleave", stopRecording);
  VOICE_BTN.addEventListener("keydown", (ev) => {
    if ((ev.key === " " || ev.key === "Enter") && !ev.repeat) {
      ev.preventDefault();
      startRecording();
    }
  });
  VOICE_BTN.addEventListener("keyup", (ev) => {
    if (ev.key === " " || ev.key === "Enter") stopRecording();
  });

  // 页面卸载前停止录音/播放，避免麦克风常驻
  window.addEventListener("beforeunload", () => {
    stopRecording();
    stopCurrentAudio();
  });

  /* ---------- 启动 ---------- */
  initVoice();
  INPUT.focus();
})();
