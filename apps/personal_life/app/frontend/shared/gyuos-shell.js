const GYUNEXUS_NAV_ITEMS = [
  ["home", "/", "home", "홈"],
  ["agents", "/agent/live-office", "agents", "에이전트"],
  ["archive", "/memory.html", "archive", "자료실"],
  ["queue", "/agent/report-center?view=queue", "queue", "작업 큐"],
  ["ideas", "/creator.html", "idea", "아이디어"],
  ["reports", "/agent/report-center", "report", "보고서"],
  ["settings", "/settings.html", "settings", "설정"],
];

const GYUNEXUS_ICONS = {
  home: '<svg viewBox="0 0 24 24"><path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10M9 20v-6h6v6"/></svg>',
  agents: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><path d="M3.5 19v-2a5.5 5.5 0 0 1 11 0v2"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.2A4.5 4.5 0 0 1 21 18v1"/></svg>',
  archive: '<svg viewBox="0 0 24 24"><path d="M4 7h16v13H4zM3 4h18v3H3zM9 11h6"/></svg>',
  queue: '<svg viewBox="0 0 24 24"><path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r=".7"/><circle cx="3.5" cy="12" r=".7"/><circle cx="3.5" cy="18" r=".7"/></svg>',
  idea: '<svg viewBox="0 0 24 24"><path d="M9 18h6M10 22h4"/><path d="M8.2 15.4A7 7 0 1 1 15.8 15.4C15 16 15 17 15 18H9c0-1 0-2-.8-2.6Z"/></svg>',
  report: '<svg viewBox="0 0 24 24"><path d="M5 3h14v18H5zM8 8h8M8 12h8M8 16h5"/></svg>',
  settings: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l-2.8 2.8a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6h-4a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-2.8-2.8a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14v-4a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l2.8-2.8a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3h4a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l2.8 2.8a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1v4a1.7 1.7 0 0 0-1.6 1Z"/></svg>',
  bell: '<svg viewBox="0 0 24 24"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 8A7 7 0 0 1 18 6l2 3M17.9 16A7 7 0 0 1 6 18l-2-3"/></svg>',
  headerBot: '<svg viewBox="0 0 24 24"><rect x="5" y="8" width="14" height="10" rx="4"/><path d="M12 8V4M8 4h8"/><circle cx="9" cy="13" r="1"/><circle cx="15" cy="13" r="1"/></svg>',
};

const GYUNEXUS_ACTIVE_ALIASES = {
  home: "home", briefing: "home", schedule: "home", money: "home", drive: "home", memo: "home", routine: "home",
  agent: "agents", agents: "agents", memory: "archive", archive: "archive", creator: "ideas", ideas: "ideas", settings: "settings",
  queue: "queue", reports: "reports",
};

class GyuNexusGlobalHeader extends HTMLElement {
  connectedCallback() {
    if (this.dataset.ready) return;
    this.dataset.ready = "true";
    this.innerHTML = `
      <header class="gyn-global-header">
        <a class="gyn-global-brand" href="/" aria-label="GyuNexus 홈으로 이동">
          <span class="gyn-brand-mark">G</span>
          <span class="gyn-brand-copy"><strong>GyuNexus</strong><small>Personal AI OS</small></span>
        </a>
        <div class="gyn-global-actions">
          <div class="gyn-connection" data-gyn-connection role="status"><i></i><span>연결 확인 중</span></div>
          <div class="gyn-header-metrics" data-gyn-metrics aria-label="Agent Office 요약"></div>
          <button class="gyn-icon-button gyn-notification" type="button" aria-label="알림">${GYUNEXUS_ICONS.bell}<b>3</b></button>
          <a class="gyn-icon-button" href="/settings.html" aria-label="설정">${GYUNEXUS_ICONS.settings}</a>
        </div>
      </header>`;
    this.renderState({ connected: false, metrics: defaultHeaderMetrics() });
    this._stateListener = (event) => this.renderState(event.detail || {});
    window.addEventListener("gyunexus:header-state", this._stateListener);
    loadGlobalHeaderState();
  }

  disconnectedCallback() {
    window.removeEventListener("gyunexus:header-state", this._stateListener);
  }

  renderState({ connected = false, metrics = defaultHeaderMetrics() }) {
    const connection = this.querySelector("[data-gyn-connection]");
    if (connection) {
      connection.classList.toggle("offline", !connected);
      connection.querySelector("span").textContent = connected ? "GyuNexus 연결됨" : "Mock 모드";
    }
    const metricRoot = this.querySelector("[data-gyn-metrics]");
    if (metricRoot) metricRoot.innerHTML = metrics.map((metric) => `<div class="gyn-header-metric"><b>${Number(metric.value) || 0}</b><span>${escapeShellHtml(metric.label)}</span></div>`).join("");
  }
}

class GyuosSidebar extends HTMLElement {
  connectedCallback() {
    const declared = GYUNEXUS_ACTIVE_ALIASES[this.getAttribute("active") || ""] || "";
    const active = resolveActiveNav(declared);
    this.innerHTML = `
      <aside class="gy-sidebar-shell">
        <nav class="gy-nav" aria-label="주요 메뉴">
          ${GYUNEXUS_NAV_ITEMS.map(([key, href, icon, label]) => `
            <a class="${key === active ? "active" : ""}" href="${href}" ${key === active ? 'aria-current="page"' : ""}>
              <span class="gy-ico">${GYUNEXUS_ICONS[icon]}</span><span>${label}</span>
            </a>`).join("")}
        </nav>
        <div class="gy-side-status"><i></i><div><b>GyuNexus 연결됨</b><small>모든 시스템 정상</small></div></div>
      </aside>`;
  }
}

class GyuosHeader extends HTMLElement {
  connectedCallback() {
    const title = this.getAttribute("title") || "GyuNexus";
    const subtitle = this.getAttribute("subtitle") || "Personal AI OS";
    const date = this.getAttribute("date") || "";
    const updated = this.getAttribute("updated") || "";
    this.innerHTML = `
      <section class="gy-page-header">
        <div class="gy-title-wrap">
          <div class="gy-header-icon">${GYUNEXUS_ICONS.headerBot}</div>
          <div><h1>${escapeShellHtml(title)}</h1><p>${escapeShellHtml(subtitle)}</p></div>
        </div>
        <div class="gy-top-actions">
          ${date || updated ? `<div class="gy-updated"><div data-gy-date>${escapeShellHtml(date)}</div><div data-gy-updated>${escapeShellHtml(updated)}</div></div>` : ""}
          <button class="gy-icon-button" type="button" aria-label="새로고침" data-gy-refresh>${GYUNEXUS_ICONS.refresh}</button>
        </div>
      </section>`;
    this.querySelector("[data-gy-refresh]")?.addEventListener("click", () => window.dispatchEvent(new CustomEvent("gyuos:refresh")));
  }
}

function resolveActiveNav(declared) {
  if (new URLSearchParams(window.location.search).get("view") === "queue") return "queue";
  if (declared) return declared;
  const path = window.location.pathname;
  if (path === "/" || path.endsWith("/index.html")) return "home";
  if (path.includes("/agent/live")) return "agents";
  if (path.includes("/agent/report")) return new URLSearchParams(window.location.search).get("view") === "queue" ? "queue" : "reports";
  if (path.includes("memory")) return "archive";
  if (path.includes("creator")) return "ideas";
  if (path.includes("settings")) return "settings";
  return "home";
}

function defaultHeaderMetrics() {
  return [
    { label: "자료", value: 0 }, { label: "블로그 초안", value: 0 }, { label: "작업 큐", value: 0 }, { label: "아이디어", value: 0 },
  ];
}

function escapeShellHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

async function loadGlobalHeaderState() {
  if (window.__gyunexusHeaderLoading) return;
  window.__gyunexusHeaderLoading = true;
  try {
    const [reportResponse, taskResponse] = await Promise.all([
      fetch("/agent/report-center/data", { headers: { Accept: "application/json" } }),
      fetch("/agent/tasks?limit=20", { headers: { Accept: "application/json" } }).catch(() => null),
    ]);
    if (!reportResponse.ok) throw new Error(`HTTP ${reportResponse.status}`);
    const report = await reportResponse.json();
    const taskPayload = taskResponse?.ok ? await taskResponse.json() : [];
    const tasks = Array.isArray(taskPayload) ? taskPayload : taskPayload?.tasks || taskPayload?.items || [];
    window.dispatchEvent(new CustomEvent("gyunexus:header-state", { detail: {
      connected: true,
      metrics: [
        { label: "자료", value: Number(report?.agent1?.display_count ?? report?.agent1?.selected_count ?? report?.agent1?.collected_count) || 0 },
        { label: "블로그 초안", value: report?.agent2?.drafts?.length || 0 },
        { label: "작업 큐", value: Array.isArray(tasks) ? tasks.length : 0 },
        { label: "아이디어", value: report?.agent4?.ideas?.length || 0 },
      ],
    } }));
  } catch (_) {
    window.dispatchEvent(new CustomEvent("gyunexus:header-state", { detail: { connected: false, metrics: defaultHeaderMetrics() } }));
  } finally {
    window.__gyunexusHeaderLoading = false;
  }
}

function installGlobalShell() {
  document.body.classList.add("gy-has-global-shell");
  if (!document.querySelector("gyunexus-global-header")) document.body.prepend(document.createElement("gyunexus-global-header"));
  if (document.body.dataset.gyShell === "overlay" && !document.querySelector("gyuos-sidebar")) {
    const sidebar = document.createElement("gyuos-sidebar");
    sidebar.classList.add("gy-overlay-sidebar");
    sidebar.setAttribute("active", "agent");
    document.body.prepend(sidebar);
  }
}

if (!customElements.get("gyunexus-global-header")) customElements.define("gyunexus-global-header", GyuNexusGlobalHeader);
if (!customElements.get("gyuos-sidebar")) customElements.define("gyuos-sidebar", GyuosSidebar);
if (!customElements.get("gyuos-header")) customElements.define("gyuos-header", GyuosHeader);

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", installGlobalShell, { once: true });
else installGlobalShell();
