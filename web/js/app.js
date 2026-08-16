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
  const VOICE_STATUS = document.getElementById("voice-status");

  // M5.2 能力面板元素
  const TABS = Array.from(document.querySelectorAll(".panels-tabs .tab"));
  const PANELS = {
    schedule: document.getElementById("panel-schedule"),
    plans: document.getElementById("panel-plans"),
    memory: document.getElementById("panel-memory"),
  };
  const SCHED_LIST = document.getElementById("schedule-list");
  const SCHED_EMPTY = document.getElementById("schedule-empty");
  const SCHED_FORM = document.getElementById("schedule-form");
  const SCHED_INPUT = document.getElementById("schedule-input");
  const SCHED_HINT = document.getElementById("schedule-hint");
  const SCHED_REFRESH = document.getElementById("schedule-refresh");
  const SCHED_SEG_BTNS = Array.from(document.querySelectorAll(".seg-btn[data-date]"));
  const PLANS_LIST = document.getElementById("plans-list");
  const PLANS_EMPTY = document.getElementById("plans-empty");
  const PLANS_HINT = document.getElementById("plans-hint");
  const PLANS_REFRESH = document.getElementById("plans-refresh");
  const MEMORY_LIST = document.getElementById("memory-list");
  const MEMORY_EMPTY = document.getElementById("memory-empty");
  const MEMORY_HINT = document.getElementById("memory-hint");
  const MEMORY_REFRESH = document.getElementById("memory-refresh");
  const MEMORY_CLEAR = document.getElementById("memory-clear");

  const API_CHAT  = "/chat";
  const API_VOICE = "/chat/voice";
  const API_SCHEDULE = "/schedule";
  const API_PLANS = "/plans";
  const API_MEMORY = "/memory";

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

  /* ---------- 语音处理中阶段提示（M4.2：识别中/思考中/回复中） ---------- */
  function setVoiceStatus(text) {
    if (!VOICE_STATUS) return;
    if (text) {
      VOICE_STATUS.textContent = text;
      VOICE_STATUS.classList.add("visible");
    } else {
      VOICE_STATUS.textContent = "";
      VOICE_STATUS.classList.remove("visible");
    }
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
      // M5.2：规划意图 → 步骤卡片（优先 POST /plans 结构化数据，失败则从回复文本解析；都不行只显示文本）
      if (isPlanningQuery(query)) {
        const steps = await fetchPlanSteps(query.trim(), data.reply);
        if (steps.length) renderPlanCard(bubble, steps);
      }
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
    // M4.2：分阶段"处理中"提示（客户端估算：识别 → 思考 → 合成），避免误判卡死
    setVoiceStatus("正在识别你的声音…");
    const statusT1 = setTimeout(() => setVoiceStatus("TA 正在思考…"), 1500);
    const statusT2 = setTimeout(() => setVoiceStatus("正在合成回复…"), 4500);
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
      clearTimeout(statusT1);
      clearTimeout(statusT2);
      setVoiceStatus("");
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

  /* ============================================================
   * M5.2：规划步骤卡片（对话内）
   * 后端 /chat 返回的是人设化纯文本回复（步骤经 LLM 口语化输出），
   * 前端识别规划意图并在回复文本中解析编号步骤行 → 卡片化展示。
   * ============================================================ */

  // 规划意图关键词（与后端 is_planning_query 的强词对齐，前端用于决定是否尝试解析卡片）
  const PLANNING_RE = /(帮我规划|帮我做个计划|帮我制定|做个计划|制定计划|规划一下|计划一下|怎么学|怎么准备|给我个计划|帮我安排一下计划)/;

  function isPlanningQuery(text) {
    return PLANNING_RE.test(text || "");
  }

  /**
   * 从回复文本中解析步骤行：形如 "1. 步骤标题（优先级：高）——说明" 或 "1. 步骤标题"。
   * 返回 [{no, title, priority, detail}]；解析不到 ≥2 步则返回 []（不渲染卡片，避免误导）。
   */
  function parsePlanSteps(text) {
    const steps = [];
    const re = /^\s*(\d+)[.、．）]\s*(.+?)\s*$/gm;
    let m;
    while ((m = re.exec(text)) !== null) {
      const raw = m[2];
      let title = raw;
      let priority = "";
      // 提取 "（优先级：高）" 尾巴
      const pri = raw.match(/[（(]\s*优先级[:：]\s*(高|中|低)\s*[）)]/);
      if (pri) {
        priority = pri[1];
        title = raw.replace(pri[0], "");
      }
      // 提取 "——说明" 尾巴
      const sep = title.search(/——|--|：/);
      let detail = "";
      if (sep > 0) {
        detail = title.slice(sep + 1).trim();
        title = title.slice(0, sep).trim();
      }
      title = title.replace(/[，,。.、\s]+$/, "").trim();
      if (!title) continue;
      steps.push({ no: steps.length + 1, title, priority, detail });
      if (steps.length >= 12) break;
    }
    return steps.length >= 2 ? steps : [];
  }

  /**
   * 获取规划步骤（真实数据，非前端编造）：
   * 1) 优先 POST /plans 调后端 PlanningAgent 拿结构化 steps；
   * 2) 失败时从 chat 回复文本解析编号步骤行作兜底。
   * 返回 [{no, title, priority, detail}]；拿不到 ≥2 步则 []。
   */
  async function fetchPlanSteps(goal, replyText) {
    try {
      const resp = await fetch(API_PLANS, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal }),
      });
      if (resp.ok) {
        const data = await resp.json();
        if (Array.isArray(data.steps) && data.steps.length >= 2) {
          return data.steps.map((s, i) => ({
            no: s.no || i + 1,
            title: String(s.title || ""),
            priority: s.priority || "",
            detail: s.detail || "",
          })).filter((s) => s.title);
        }
      }
    } catch (e) {
      /* 结构化接口失败 → 文本解析兜底 */
    }
    return parsePlanSteps(replyText || "");
  }

  /** 在回复气泡下方渲染步骤卡片。 */
  function renderPlanCard(bubble, steps) {
    if (!steps || !steps.length) return;
    const card = document.createElement("div");
    card.className = "plan-card";
    const title = document.createElement("div");
    title.className = "plan-card-title";
    title.textContent = "📋 帮你梳理好的步骤：";
    card.appendChild(title);
    for (const s of steps) {
      const row = document.createElement("div");
      row.className = "plan-step";
      const no = document.createElement("span");
      no.className = "plan-step-no";
      no.textContent = String(s.no);
      const body = document.createElement("div");
      body.className = "plan-step-body";
      const text = document.createElement("span");
      text.textContent = s.title;
      body.appendChild(text);
      if (s.priority) {
        const pri = document.createElement("span");
        pri.className = "plan-step-pri";
        pri.textContent = s.priority;
        body.appendChild(pri);
      }
      if (s.detail) {
        const det = document.createElement("div");
        det.textContent = s.detail;
        det.style.cssText = "font-size:12px;color:#8a7284;margin-top:2px;";
        body.appendChild(det);
      }
      row.appendChild(no);
      row.appendChild(body);
      card.appendChild(row);
    }
    // 插到气泡所在消息内（气泡之后）
    const wrap = bubble.parentElement;
    wrap.appendChild(card);
    MESSAGES.scrollTop = MESSAGES.scrollHeight;
  }

  /* ============================================================
   * M5.2：能力面板（日程 / 规划 / 记忆）
   * ============================================================ */

  function setHint(el, text, isError) {
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("error", !!isError);
  }

  function switchPanel(name) {
    for (const tab of TABS) {
      const active = tab.dataset.panel === name;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    }
    for (const key of Object.keys(PANELS)) {
      PANELS[key].classList.toggle("active", key === name);
    }
    // 首次打开时按需加载
    if (name === "schedule" && !SCHED_LIST.dataset.loaded) loadSchedule(currentSchedDate());
    if (name === "plans" && !PLANS_LIST.dataset.loaded) loadPlans();
    if (name === "memory" && !MEMORY_LIST.dataset.loaded) loadMemory();
  }

  function currentSchedDate() {
    const active = SCHED_SEG_BTNS.find((b) => b.classList.contains("active"));
    return active ? active.dataset.date : "today";
  }

  // ---------- 日程 ----------

  async function loadSchedule(date) {
    try {
      const resp = await fetch(API_SCHEDULE + "?date=" + encodeURIComponent(date));
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      SCHED_LIST.dataset.loaded = "1";
      renderSchedule(data.entries || [], data.date);
    } catch (err) {
      setHint(SCHED_HINT, "日程加载失败：" + err.message, true);
    }
  }

  function renderSchedule(entries, dateLabel) {
    SCHED_LIST.textContent = "";
    SCHED_EMPTY.style.display = entries.length ? "none" : "block";
    for (const e of entries) {
      const li = document.createElement("li");
      li.className = e.done ? "item-done" : "";
      const time = document.createElement("span");
      time.className = "item-time";
      time.textContent = e.time || "全天";
      const main = document.createElement("div");
      main.className = "item-main";
      main.textContent = e.event || "（无事项）";
      if (e.repeat) {
        const rep = document.createElement("div");
        rep.className = "item-repeat";
        rep.textContent = "重复：" + e.repeat;
        main.appendChild(rep);
      }
      const actions = document.createElement("div");
      actions.className = "item-actions";
      const doneBtn = document.createElement("button");
      doneBtn.type = "button";
      doneBtn.title = e.done ? "已完成" : "标记完成";
      doneBtn.textContent = "✓";
      doneBtn.disabled = !!e.done;
      doneBtn.addEventListener("click", () => markScheduleDone(e.id));
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.title = "删除";
      delBtn.textContent = "✕";
      delBtn.addEventListener("click", () => deleteSchedule(e.id));
      actions.appendChild(doneBtn);
      actions.appendChild(delBtn);
      li.appendChild(time);
      li.appendChild(main);
      li.appendChild(actions);
      SCHED_LIST.appendChild(li);
    }
    setHint(SCHED_HINT, dateLabel ? "已显示 " + dateLabel + " 的日程（" + entries.length + " 条）" : "");
  }

  async function addSchedule(text) {
    if (!text.trim()) return;
    try {
      const resp = await fetch(API_SCHEDULE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text.trim() }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || ("HTTP " + resp.status));
      SCHED_INPUT.value = "";
      setHint(SCHED_HINT, "记下啦：" + data.date + " " + data.time + " " + data.event);
      loadSchedule(currentSchedDate());
    } catch (err) {
      setHint(SCHED_HINT, "没记上：" + err.message, true);
    }
  }

  async function markScheduleDone(id) {
    try {
      const resp = await fetch(API_SCHEDULE + "/" + id + "/done", { method: "POST" });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || ("HTTP " + resp.status));
      }
      loadSchedule(currentSchedDate());
    } catch (err) {
      setHint(SCHED_HINT, "操作失败：" + err.message, true);
    }
  }

  async function deleteSchedule(id) {
    try {
      const resp = await fetch(API_SCHEDULE + "/" + id, { method: "DELETE" });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || ("HTTP " + resp.status));
      }
      setHint(SCHED_HINT, "已删除该条日程");
      loadSchedule(currentSchedDate());
    } catch (err) {
      setHint(SCHED_HINT, "删除失败：" + err.message, true);
    }
  }

  // ---------- 规划 ----------

  async function loadPlans() {
    try {
      const resp = await fetch(API_PLANS);
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      PLANS_LIST.dataset.loaded = "1";
      renderPlans(data.plans || []);
    } catch (err) {
      setHint(PLANS_HINT, "规划列表加载失败：" + err.message, true);
    }
  }

  function renderPlans(plans) {
    PLANS_LIST.textContent = "";
    PLANS_EMPTY.style.display = plans.length ? "none" : "block";
    for (const p of plans) {
      const li = document.createElement("li");
      const main = document.createElement("div");
      main.className = "plan-item-goal";
      main.textContent = p.goal;
      const meta = document.createElement("div");
      meta.className = "plan-item-meta";
      meta.textContent = p.step_count + " 步 · " + (p.created_at || "");
      main.appendChild(meta);
      const actions = document.createElement("div");
      actions.className = "item-actions";
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.title = "删除计划";
      delBtn.textContent = "✕";
      delBtn.addEventListener("click", () => deletePlan(p.id));
      actions.appendChild(delBtn);
      li.appendChild(main);
      li.appendChild(actions);
      PLANS_LIST.appendChild(li);
    }
    setHint(PLANS_HINT, plans.length ? "共 " + plans.length + " 份计划" : "");
  }

  async function deletePlan(id) {
    try {
      const resp = await fetch(API_PLANS + "/" + id, { method: "DELETE" });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || ("HTTP " + resp.status));
      }
      setHint(PLANS_HINT, "已删除该计划");
      loadPlans();
    } catch (err) {
      setHint(PLANS_HINT, "删除失败：" + err.message, true);
    }
  }

  // ---------- 记忆 ----------

  async function loadMemory() {
    try {
      const resp = await fetch(API_MEMORY);
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      MEMORY_LIST.dataset.loaded = "1";
      renderMemory(data.memories || []);
    } catch (err) {
      setHint(MEMORY_HINT, "记忆加载失败：" + err.message, true);
    }
  }

  function renderMemory(memories) {
    MEMORY_LIST.textContent = "";
    MEMORY_EMPTY.style.display = memories.length ? "none" : "block";
    for (const m of memories) {
      const li = document.createElement("li");
      const kind = document.createElement("span");
      kind.className = "memory-kind " + (m.kind || "other");
      kind.textContent = m.kind || "other";
      const main = document.createElement("div");
      main.className = "item-main";
      main.textContent = m.content;
      const meta = document.createElement("div");
      meta.className = "plan-item-meta";
      meta.textContent = m.created_at || "";
      main.appendChild(meta);
      li.appendChild(kind);
      li.appendChild(main);
      MEMORY_LIST.appendChild(li);
    }
    setHint(MEMORY_HINT, memories.length ? "共 " + memories.length + " 条记忆" : "");
  }

  async function clearMemory() {
    // 清空属破坏性操作：先确认再调用（后端也要求 confirm=1 二次确认）
    if (!window.confirm("确定要清空 TA 的全部记忆吗？清空后不可恢复。")) return;
    try {
      const resp = await fetch(API_MEMORY + "?confirm=1", { method: "DELETE" });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || ("HTTP " + resp.status));
      setHint(MEMORY_HINT, "已清空 " + data.deleted + " 条记忆");
      delete MEMORY_LIST.dataset.loaded;
      loadMemory();
    } catch (err) {
      setHint(MEMORY_HINT, "清空失败：" + err.message, true);
    }
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

  /* ---------- M5.2：能力面板事件 ---------- */
  for (const tab of TABS) {
    tab.addEventListener("click", () => switchPanel(tab.dataset.panel));
  }
  for (const btn of SCHED_SEG_BTNS) {
    btn.addEventListener("click", () => {
      for (const b of SCHED_SEG_BTNS) {
        b.classList.toggle("active", b === btn);
        b.setAttribute("aria-selected", b === btn ? "true" : "false");
      }
      loadSchedule(btn.dataset.date);
    });
  }
  SCHED_REFRESH.addEventListener("click", () => loadSchedule(currentSchedDate()));
  SCHED_FORM.addEventListener("submit", (ev) => {
    ev.preventDefault();
    addSchedule(SCHED_INPUT.value);
  });
  PLANS_REFRESH.addEventListener("click", () => loadPlans());
  MEMORY_REFRESH.addEventListener("click", () => loadMemory());
  MEMORY_CLEAR.addEventListener("click", clearMemory);

  /* ---------- M5.3：面板折叠（纯布局行为，业务逻辑不变） ---------- */
  const PANELS_EL = document.querySelector(".panels");
  const PANELS_TOGGLE = document.getElementById("panels-toggle");
  if (PANELS_EL && PANELS_TOGGLE) {
    PANELS_TOGGLE.addEventListener("click", () => {
      const collapsed = PANELS_EL.classList.toggle("collapsed");
      PANELS_TOGGLE.setAttribute("aria-expanded", collapsed ? "false" : "true");
      PANELS_TOGGLE.title = collapsed ? "展开面板" : "收起面板";
    });
  }

  /* ---------- 启动 ---------- */
  initVoice();
  INPUT.focus();
  switchPanel("schedule"); // 默认打开日程面板（懒加载今日日程）
})();
