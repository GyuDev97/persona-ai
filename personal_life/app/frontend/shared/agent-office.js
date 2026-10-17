(() => {
  "use strict";

  const API = {
    report: "/agent/report-center/data",
    tasks: "/agent/tasks?limit=20",
    detail: (agentId) => `/agent/standby-status/detail/${agentId}`,
    focus: (agentId) => `/agent/standby-status/focus/${agentId}`,
  };

  const AGENT_META = {
    1: { color: "green", name: "오전 10시~오후 6시 IT 뉴스 요약", fallbackTask: "최신 IT 뉴스 5건을 조사 중입니다. 기사 기준, 요약, 핵심 인사이트를 정리합니다.", time: "오전 11:03", progress: 100 },
    2: { color: "orange", name: "IT/모바일 관련 블로그 초안 추천", fallbackTask: "블로그 초안 AI 준비 완료. 익숙함에서 편리함으로 이어지는 콘텐츠 흐름을 정리합니다.", time: "오전 11:03", progress: 100 },
    3: { color: "blue", name: "코딩 / 앱 업데이트 처리", fallbackTask: "승인된 코딩 작업과 앱 업데이트 요청을 확인하고 있습니다.", time: "오전 10:18", progress: 35 },
    4: { color: "purple", name: "유튜브 아이디어 탐색", fallbackTask: "새로운 콘텐츠 아이디어와 주제를 탐색하고 있습니다.", time: "오전 11:03", progress: 60 },
  };

  const MOCK = {
    updatedAt: new Date().toISOString(),
    agents: [
      { id: 1, name: "오전 10시~오후 6시 IT 뉴스 요약", task: "최신 IT 뉴스 5건을 조사 중입니다. 오늘 기사 기준, 요약, 핵심 인사이트를 정리합니다.", status: "완료", time: "오전 11:03", progress: 100 },
      { id: 2, name: "IT/모바일 관련 블로그 초안 추천", task: "블로그 초안 AI 준비 완료. 익숙함에서 편리함으로 이어지는 콘텐츠 흐름입니다.", status: "완성", time: "오전 11:03", progress: 100 },
      { id: 3, name: "코딩 / 앱 업데이트 처리", task: "대기 중인 코딩 작업과 앱 업데이트 요청을 확인합니다.", status: "대기 중", time: "오전 10:18", progress: 35 },
      { id: 4, name: "유튜브 아이디어 탐색", task: "최근 작업 확인이 필요합니다.", status: "확인 필요", time: "오전 11:03", progress: 60 },
    ],
    metrics: [
      { key: "news", label: "자료", value: 23, icon: "folder", color: "#3d87ed" },
      { key: "drafts", label: "블로그 초안", value: 8, icon: "document", color: "#20b26b" },
      { key: "queue", label: "작업 큐", value: 20, icon: "queue", color: "#8d63e8" },
      { key: "ideas", label: "아이디어", value: 1, icon: "idea", color: "#f28a38" },
    ],
    activities: [
      { time: "10:36", agentId: 1, title: "Agent 01 → Agent 02", content: "자료 23건 전달 완료" },
      { time: "10:18", agentId: 3, title: "Agent 03", content: "승인 검토 완료" },
      { time: "10:00", agentId: 2, title: "Agent 02", content: "블로그 초안 작성 시작" },
      { time: "06:00", agentId: 4, title: "Agent 04", content: "아이디어 정리 시작" },
    ],
    progress: [
      { agentId: 2, title: "블로그 초안 작성", progress: 40, status: "작업 중" },
      { agentId: 4, title: "아이디어 정리", progress: 60, status: "진행 중" },
    ],
  };

  const state = { data: structuredClone(MOCK), selectedAgentId: null, usingMock: true };
  const $ = (id) => document.getElementById(id);

  const icons = {
    home: '<svg viewBox="0 0 24 24"><path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10M9 20v-6h6v6"/></svg>',
    agents: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><path d="M3.5 19v-2a5.5 5.5 0 0 1 11 0v2"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.2A4.5 4.5 0 0 1 21 18v1"/></svg>',
    archive: '<svg viewBox="0 0 24 24"><path d="M4 7h16v13H4zM3 4h18v3H3zM9 11h6"/></svg>',
    queue: '<svg viewBox="0 0 24 24"><path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r=".7"/><circle cx="3.5" cy="12" r=".7"/><circle cx="3.5" cy="18" r=".7"/></svg>',
    idea: '<svg viewBox="0 0 24 24"><path d="M9 18h6M10 22h4"/><path d="M8.2 15.4A7 7 0 1 1 15.8 15.4C15 16 15 17 15 18H9c0-1 0-2-.8-2.6Z"/></svg>',
    report: '<svg viewBox="0 0 24 24"><path d="M5 3h14v18H5zM8 8h8M8 12h8M8 16h5"/></svg>',
    settings: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l-2.8 2.8a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6h-4a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-2.8-2.8a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14v-4a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l2.8-2.8a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3h4a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l2.8 2.8a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1v4a1.7 1.7 0 0 0-1.6 1Z"/></svg>',
    chat: '<svg viewBox="0 0 24 24"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/><path d="M8 9h8M8 13h5"/></svg>',
    refresh: '<svg viewBox="0 0 24 24"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 8A7 7 0 0 1 18 6l2 3M17.9 16A7 7 0 0 1 6 18l-2-3"/></svg>',
    folder: '<svg viewBox="0 0 24 24"><path d="M3 6h7l2 2h9v11H3z"/></svg>',
    document: '<svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6zM14 3v5h5M9 12h6M9 16h6"/></svg>',
    file: '<svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6zM14 3v5h5"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>',
    desk: '<svg viewBox="0 0 32 32"><rect x="7" y="5" width="18" height="12" rx="2"/><path d="M4 20h24M7 20v7M25 20v7M13 17v3M19 17v3"/></svg>',
  };

  function installIcons(root = document) {
    root.querySelectorAll("[data-icon]").forEach((node) => {
      const icon = icons[node.dataset.icon];
      if (icon) node.innerHTML = icon;
    });
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  }

  function cleanText(value, fallback = "") {
    const text = String(value ?? "").replace(/\s+/g, " ").trim();
    if (!text || text.includes("�")) return fallback;
    return text.length > 92 ? `${text.slice(0, 91)}…` : text;
  }

  function timeLabel(value, fallback = "방금 전") {
    if (!value) return fallback;
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return fallback;
    return new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: true }).format(parsed);
  }

  function numeric(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  async function getJson(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function postJson(url, payload = {}) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function inferAgentId(task) {
    const type = String(task?.task_type || "");
    if (type.includes("agent1") || type.includes("news")) return 1;
    if (type.includes("agent2") || type.includes("blog") || type.includes("naver")) return 2;
    if (type.includes("agent3") || type.includes("coding") || type.includes("finance")) return 3;
    if (type.includes("agent4") || type.includes("youtube") || type.includes("idea")) return 4;
    return numeric(task?.agent_id, 0);
  }

  function normalizeApiData(report, taskPayload) {
    const tasks = Array.isArray(taskPayload) ? taskPayload : taskPayload?.tasks || taskPayload?.items || [];
    const reportCards = Array.isArray(report?.cards) ? report.cards : [];
    const agents = [1, 2, 3, 4].map((id) => {
      const meta = AGENT_META[id];
      const card = reportCards.find((item) => numeric(item.agent_id) === id) || {};
      const agentTasks = tasks.filter((item) => inferAgentId(item) === id);
      const activeTask = agentTasks.find((item) => ["pending", "claimed", "running", "in_progress"].includes(String(item.status).toLowerCase()));
      const rawStatus = cleanText(card.status, activeTask ? "작업 중" : "진행 중");
      const task = cleanText(card.latest_result_summary || activeTask?.command_text || activeTask?.result_summary, meta.fallbackTask);
      return {
        id,
        name: cleanText(card.title, meta.name),
        task,
        status: normalizeStatus(rawStatus),
        time: timeLabel(card.updated_at || activeTask?.updated_at || activeTask?.created_at, meta.time),
        progress: activeTask ? taskProgress(activeTask, meta.progress) : meta.progress,
        description: cleanText(card.description, meta.fallbackTask),
        highlights: Array.isArray(card.highlights) ? card.highlights.filter(Boolean).slice(0, 4) : [],
      };
    });

    const metrics = [
      { key: "news", label: "자료", value: numeric(report?.agent1?.display_count ?? report?.agent1?.selected_count ?? report?.agent1?.collected_count, 0), icon: "folder", color: "#3d87ed" },
      { key: "drafts", label: "블로그 초안", value: report?.agent2?.drafts?.length ?? MOCK.metrics[1].value, icon: "document", color: "#20b26b" },
      { key: "queue", label: "작업 큐", value: tasks.length || MOCK.metrics[2].value, icon: "queue", color: "#8d63e8" },
      { key: "ideas", label: "아이디어", value: report?.agent4?.ideas?.length ?? MOCK.metrics[3].value, icon: "idea", color: "#f28a38" },
    ];

    const messages = Array.isArray(report?.collaboration?.messages) ? report.collaboration.messages : [];
    const activities = messages.length ? messages.slice(0, 8).map((message) => {
      const agentId = numeric(message.from_agent_id || message.agent_id, 1);
      const targetId = numeric(message.to_agent_id, 0);
      return {
        time: timeLabel(message.created_at || message.updated_at, "--:--").replace(/^(오전|오후)\s*/, ""),
        agentId: Math.min(Math.max(agentId, 1), 4),
        title: targetId ? `Agent ${pad(agentId)} → Agent ${pad(targetId)}` : `Agent ${pad(agentId)}`,
        content: cleanText(message.message || message.content || message.summary, "협업 상태가 업데이트되었습니다."),
      };
    }) : MOCK.activities;

    const activeTasks = tasks.filter((task) => ["pending", "claimed", "running", "in_progress"].includes(String(task.status || "").toLowerCase()));
    const progress = activeTasks.length ? activeTasks.slice(0, 5).map((task) => {
      const agentId = inferAgentId(task) || 3;
      return {
        agentId,
        title: cleanText(task.command_text || task.result_summary, AGENT_META[agentId]?.name || "진행 작업"),
        progress: taskProgress(task, AGENT_META[agentId]?.progress || 35),
        status: normalizeStatus(task.status),
      };
    }) : MOCK.progress;

    return { updatedAt: report?.updated_at || new Date().toISOString(), agents, metrics, activities, progress };
  }

  function normalizeStatus(status) {
    const value = String(status || "").toLowerCase();
    if (["pending", "queued", "대기"].some((word) => value.includes(word))) return "대기 중";
    if (["completed", "done", "완료"].some((word) => value.includes(word))) return "진행 중";
    if (["failed", "error", "실패", "오류"].some((word) => value.includes(word))) return "확인 필요";
    return value && value.length < 14 ? status : "작업 중";
  }

  function taskProgress(task, fallback) {
    const explicit = numeric(task.progress ?? task.progress_percent, -1);
    if (explicit >= 0) return Math.min(100, explicit);
    const status = String(task.status || "").toLowerCase();
    if (["completed", "done"].includes(status)) return 100;
    if (["claimed", "running", "in_progress"].includes(status)) return Math.max(fallback, 55);
    return fallback;
  }

  function pad(value) {
    return String(value || 0).padStart(2, "0");
  }

  function render() {
    renderAgents();
    renderMetrics();
    renderActivities();
    renderProgress();
    renderHeaderMetrics();
    $("updatedTime").textContent = state.usingMock ? "mock 데이터" : `${timeLabel(state.data.updatedAt)} 업데이트`;
    $("sceneSummary").textContent = state.usingMock ? "미리보기 데이터로 운영 현황을 표시합니다." : "실시간 Agent 데이터와 연결되었습니다.";
    installIcons();
  }

  function renderAgents() {
    $("agentGrid").innerHTML = state.data.agents.map((agent) => `
      <button class="agent-card" type="button" data-agent="${agent.id}" aria-label="Agent ${pad(agent.id)} ${escapeHtml(agent.name)} 상세 보기">
        <div>
          <span class="agent-number">AGENT ${pad(agent.id)}</span>
          <h2 class="agent-name">${escapeHtml(agent.name)}</h2>
          <p class="agent-task">${escapeHtml(agent.task)}</p>
          <div class="agent-meta"><span class="state"><i></i>${escapeHtml(agent.status)}</span><span class="separator">·</span><time>${escapeHtml(agent.time)}</time></div>
        </div>
        <span class="desk-icon" aria-hidden="true">${icons.desk}</span>
        <img class="agent-visual" src="/shared/assets/agent-office/agent-${pad(agent.id)}.png" alt="" aria-hidden="true">
        <span class="card-arrow" aria-hidden="true">↗</span>
      </button>`).join("");
  }

  function renderMetrics() {
    $("metricGrid").innerHTML = state.data.metrics.map((metric) => `
      <article class="metric-card" style="--metric-color:${metric.color}">
        <span class="metric-icon"><span data-icon="${metric.icon}"></span></span>
        <div><b>${numeric(metric.value)}</b><small>${escapeHtml(metric.label)}</small></div>
      </article>`).join("");
  }

  function renderHeaderMetrics() {
    $("headerMetrics").innerHTML = state.data.metrics.map((metric) => `<div class="header-metric"><b>${numeric(metric.value)}</b><span>${escapeHtml(metric.label)}</span></div>`).join("");
    syncGlobalHeader();
  }

  function renderActivities() {
    $("activityList").innerHTML = state.data.activities.length ? state.data.activities.map((item) => `
      <button class="activity-item" type="button" data-highlight-agent="${item.agentId}" style="--agent-color:var(--${AGENT_META[item.agentId]?.color || "green"})">
        <time class="activity-time">${escapeHtml(item.time)}</time><span class="activity-dot"></span>
        <span class="activity-copy"><strong>${escapeHtml(item.title)}</strong>${escapeHtml(item.content)}</span>
      </button>`).join("") : '<div class="empty-state">최근 협업 로그가 없습니다.</div>';
  }

  function renderProgress() {
    $("taskCount").textContent = state.data.progress.length;
    $("progressList").innerHTML = state.data.progress.length ? state.data.progress.map((item) => {
      const progress = Math.min(100, Math.max(0, numeric(item.progress)));
      return `<article class="progress-item" style="--agent-color:var(--${AGENT_META[item.agentId]?.color || "green"})">
        <div class="progress-top"><div><strong class="progress-title">${escapeHtml(item.title)}</strong><span class="progress-agent">Agent ${pad(item.agentId)}</span></div><span class="status-label">${escapeHtml(item.status)}</span></div>
        <div class="progress-meta"><span>진행률</span><b>${progress}%</b></div><div class="progress-track"><div class="progress-bar" style="width:${progress}%"></div></div>
      </article>`;
    }).join("") : '<div class="empty-state">진행 중인 작업이 없습니다.</div>';
  }

  function renderDrawer(agent) {
    const meta = AGENT_META[agent.id];
    $("drawerTitle").textContent = `Agent ${pad(agent.id)} 상세`;
    $("drawerBody").innerHTML = `
      <section class="drawer-agent-hero" style="--agent-color:var(--${meta.color})">
        <span class="desk-icon">${icons.desk}</span><div><h3>${escapeHtml(agent.name)}</h3><p>${escapeHtml(agent.description || agent.task)}</p></div>
      </section>
      <div class="detail-grid">
        <div class="detail-field"><span>현재 상태</span><strong>${escapeHtml(agent.status)}</strong></div>
        <div class="detail-field"><span>마지막 업데이트</span><strong>${escapeHtml(agent.time)}</strong></div>
        <div class="detail-field"><span>작업 진행률</span><strong>${numeric(agent.progress)}%</strong></div>
        <div class="detail-field"><span>데이터 소스</span><strong>${state.usingMock ? "Mock" : "Live API"}</strong></div>
      </div>
      <section class="detail-summary"><h4>현재 작업</h4><p>${escapeHtml(agent.task)}</p></section>
      ${agent.highlights?.length ? `<section class="detail-summary"><h4>최근 결과</h4><p>${agent.highlights.map((item) => `• ${escapeHtml(item)}`).join("<br>")}</p></section>` : ""}`;
  }

  function openDrawer(agentId) {
    const agent = state.data.agents.find((item) => item.id === numeric(agentId));
    if (!agent) return;
    state.selectedAgentId = agent.id;
    renderDrawer(agent);
    document.querySelectorAll(".agent-card").forEach((card) => card.classList.toggle("selected", numeric(card.dataset.agent) === agent.id));
    $("drawerBackdrop").hidden = false;
    $("detailDrawer").classList.add("open");
    $("detailDrawer").setAttribute("aria-hidden", "false");
    postJson(API.detail(agent.id)).catch(() => {});
  }

  function closeDrawer() {
    $("detailDrawer").classList.remove("open");
    $("detailDrawer").setAttribute("aria-hidden", "true");
    $("drawerBackdrop").hidden = true;
    document.querySelectorAll(".agent-card").forEach((card) => card.classList.remove("selected"));
  }

  function highlightAgent(agentId) {
    const card = document.querySelector(`.agent-card[data-agent="${numeric(agentId)}"]`);
    if (!card) return;
    card.classList.add("highlighted");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => card.classList.remove("highlighted"), 1500);
  }

  function showToast(message) {
    $("toast").textContent = message;
    $("toast").classList.add("show");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => $("toast").classList.remove("show"), 2600);
  }

  function setConnection(connected) {
    $("connectionPill").classList.toggle("offline", !connected);
    $("liveState").textContent = connected ? "GyuNexus 연결됨" : "Mock 모드";
    syncGlobalHeader(connected);
  }

  function syncGlobalHeader(connected = !state.usingMock) {
    window.dispatchEvent(new CustomEvent("gyunexus:header-state", { detail: { connected, metrics: state.data.metrics } }));
  }

  async function loadData({ quiet = false } = {}) {
    const refreshButton = $("refreshButton");
    refreshButton.disabled = true;
    try {
      const [report, tasks] = await Promise.all([getJson(API.report), getJson(API.tasks).catch(() => [])]);
      state.data = normalizeApiData(report, tasks);
      state.usingMock = false;
      setConnection(true);
      render();
      if (!quiet) showToast("최신 Agent 상태로 업데이트했습니다.");
    } catch (error) {
      state.data = structuredClone(MOCK);
      state.usingMock = true;
      setConnection(false);
      render();
      if (!quiet) showToast("API 연결 전이라 mock 데이터로 표시합니다.");
    } finally {
      refreshButton.disabled = false;
    }
  }

  function openChat() {
    $("chatModal").hidden = false;
    window.setTimeout(() => $("chatInput").focus(), 0);
  }

  function closeChat() {
    $("chatModal").hidden = true;
  }

  function chatReply(question) {
    const normalized = question.replace(/\s+/g, " ").trim();
    const active = state.data.progress;
    if (/자료|뉴스|수집/.test(normalized)) return `현재 자료 ${state.data.metrics[0].value}건이 등록되어 있습니다. Agent 01이 수집과 분류를 담당하고 있습니다.`;
    if (/작업|진행|상황/.test(normalized)) return active.length ? `현재 ${active.length}개 작업이 진행 중입니다.\n${active.map((item) => `• Agent ${pad(item.agentId)} · ${item.title} (${item.progress}%)`).join("\n")}` : "현재 진행 중인 작업이 없습니다.";
    return `4개 Agent가 정상적으로 운영 중입니다. 자료 ${state.data.metrics[0].value}건, 블로그 초안 ${state.data.metrics[1].value}건, 작업 큐 ${state.data.metrics[2].value}건을 확인했습니다.`;
  }

  function addChatMessage(role, text) {
    const log = $("chatLog");
    if (log.querySelector(".chat-empty")) log.innerHTML = "";
    const message = document.createElement("div");
    message.className = `chat-message${role === "user" ? " user" : ""}`;
    const label = document.createElement("strong");
    label.textContent = role === "user" ? "You" : "GyuNexus Core";
    message.append(label, document.createTextNode(text));
    log.appendChild(message);
    log.scrollTop = log.scrollHeight;
  }

  function bindEvents() {
    $("agentGrid").addEventListener("click", (event) => {
      const card = event.target.closest(".agent-card");
      if (card) openDrawer(card.dataset.agent);
    });
    $("activityList").addEventListener("click", (event) => {
      const item = event.target.closest("[data-highlight-agent]");
      if (item) highlightAgent(item.dataset.highlightAgent);
    });
    $("drawerClose").addEventListener("click", closeDrawer);
    $("drawerBackdrop").addEventListener("click", closeDrawer);
    $("drawerFocusButton").addEventListener("click", async () => {
      if (!state.selectedAgentId) return;
      try { await postJson(API.focus(state.selectedAgentId)); } catch (_) { /* Mock mode keeps this interaction local. */ }
      highlightAgent(state.selectedAgentId);
      closeDrawer();
      showToast(`Agent ${pad(state.selectedAgentId)}에 집중 모드를 적용했습니다.`);
    });
    $("coreHub").addEventListener("click", () => showToast("GyuNexus Core가 모든 Agent를 정상적으로 조율하고 있습니다."));
    $("refreshButton").addEventListener("click", () => loadData());
    $("agentChatButton").addEventListener("click", openChat);
    $("chatClose").addEventListener("click", closeChat);
    $("chatModal").addEventListener("click", (event) => { if (event.target === $("chatModal")) closeChat(); });
    document.querySelectorAll("[data-question]").forEach((button) => button.addEventListener("click", () => {
      $("chatInput").value = button.dataset.question;
      $("chatForm").requestSubmit();
    }));
    $("chatForm").addEventListener("submit", (event) => {
      event.preventDefault();
      const question = $("chatInput").value.trim();
      if (!question) return;
      addChatMessage("user", question);
      $("chatInput").value = "";
      window.setTimeout(() => addChatMessage("agent", chatReply(question)), 180);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (!$("chatModal").hidden) closeChat();
      else closeDrawer();
    });
  }

  installIcons();
  render();
  bindEvents();
  loadData({ quiet: true });
  window.setInterval(() => loadData({ quiet: true }), 30000);
})();
