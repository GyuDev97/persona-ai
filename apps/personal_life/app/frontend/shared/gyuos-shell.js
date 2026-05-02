const GYUOS_NAV_ITEMS = [
  ["home", "/", "home", "홈"],
  ["briefing", "/briefing.html", "briefing", "브리핑"],
  ["schedule", "/schedule.html", "calendar", "일정"],
  ["money", "/money-core", "money", "Money Core"],
  ["drive", "/drive.html", "car", "자동차"],
  ["creator", "/creator.html", "sparkles", "Creator Studio"],
  ["agent", "/agent/report-center", "grid", "Agent Report"],
  ["memory", "/memory.html", "search", "기억 검색"],
  ["memo", "/memo.html", "memo", "메모"],
  ["routine", "/routine.html", "target", "루틴 & 목표"],
  ["settings", "/settings.html", "settings", "설정"],
];

const GYUOS_ICONS = {
  home: '<svg viewBox="0 0 24 24"><path d="M4 11.5 12 5l8 6.5"></path><path d="M6.5 10.5V20h11v-9.5"></path></svg>',
  briefing: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"></circle><path d="M12 8v8M8 12h8"></path></svg>',
  calendar: '<svg viewBox="0 0 24 24"><rect x="5" y="6" width="14" height="14" rx="2"></rect><path d="M8 4v4M16 4v4M5 10h14"></path></svg>',
  money: '<svg viewBox="0 0 24 24"><rect x="5" y="6" width="14" height="12" rx="3"></rect><path d="M8 10h8M8 14h4"></path><circle cx="16" cy="14" r="1.5"></circle></svg>',
  car: '<svg viewBox="0 0 24 24"><path d="M4 15h16"></path><path d="m6 15 2.2-5h7.6L18 15"></path><path d="M7 17h.01M17 17h.01"></path></svg>',
  sparkles: '<svg viewBox="0 0 24 24"><path d="M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8L12 3Z"></path><path d="M19 14l.9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9L19 14Z"></path></svg>',
  grid: '<svg viewBox="0 0 24 24"><path d="M5 5h4v4H5zM10 5h4v4h-4zM15 5h4v4h-4zM5 10h4v4H5zM10 10h4v4h-4zM15 10h4v4h-4zM5 15h4v4H5zM10 15h4v4h-4zM15 15h4v4h-4z"></path></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="4.5"></circle><path d="m14 14 5 5"></path></svg>',
  memo: '<svg viewBox="0 0 24 24"><path d="M6 5h12M6 9h12M6 13h12M6 17h12"></path></svg>',
  target: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"></circle><circle cx="12" cy="12" r="4.8"></circle><circle cx="12" cy="12" r="1.8"></circle></svg>',
  settings: '<svg viewBox="0 0 24 24"><path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z"></path><path d="M18.5 13.5v-3l-2-.5-.8-1.8 1.1-1.8-2.1-2.1-1.8 1.1-1.8-.8-.6-2h-3l-.5 2-1.8.8-1.8-1.1-2.1 2.1 1.1 1.8-.8 1.8-2 .5v3l2 .5.8 1.8-1.1 1.8 2.1 2.1 1.8-1.1 1.8.8.5 2h3l.6-2 1.8-.8 1.8 1.1 2.1-2.1-1.1-1.8.8-1.8 2-.5Z"></path></svg>',
  bell: '<svg viewBox="0 0 24 24"><path d="M7 10a5 5 0 0 1 10 0v3.5l1.7 2.7H5.3L7 13.5V10Z"></path><path d="M10 19a2 2 0 0 0 4 0"></path></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M20 7v5h-5"></path><path d="M4 17v-5h5"></path><path d="M6.2 9A7 7 0 0 1 18 7.6L20 12"></path><path d="M17.8 15A7 7 0 0 1 6 16.4L4 12"></path></svg>',
  headerBot: '<svg viewBox="0 0 24 24"><rect x="5" y="8" width="14" height="10" rx="4"></rect><path d="M12 8V4"></path><path d="M8 4h8"></path><circle cx="9" cy="13" r="1"></circle><circle cx="15" cy="13" r="1"></circle></svg>',
};

class GyuosSidebar extends HTMLElement {
  connectedCallback(){
    const active = this.getAttribute("active") || "";
    const variant = this.getAttribute("variant") || "";
    const cardTitle = this.getAttribute("card-title") || "Gyu Assistant";
    const cardText = this.getAttribute("card-text") || "무엇이든 물어보세요.";
    const nav = GYUOS_NAV_ITEMS.map(([key, href, icon, label]) => `
      <a class="${key === active ? "active" : ""}" href="${href}">
        <span class="gy-ico">${GYUOS_ICONS[icon] || icon}</span><span>${label}</span>
      </a>
    `).join("");
    this.innerHTML = `
      <aside class="gy-sidebar-shell ${variant}">
        <div>
          <a class="gy-brand-link" href="/" aria-label="GyuOS 메인 화면으로 이동">
            <div class="gy-logo">GyuOS</div>
            <div class="gy-sub">Personal AI OS</div>
          </a>
          <nav class="gy-nav">${nav}</nav>
        </div>
        <div class="gy-side-card">
          <div class="gy-side-orb"></div>
          <b>${cardTitle}</b>
          <p>${cardText}</p>
        </div>
        <div class="gy-profile">
          <div class="gy-avatar">G</div>
          <div><b>Gyu</b><small>Premium Plan</small></div>
        </div>
      </aside>
    `;
  }
}

class GyuosHeader extends HTMLElement {
  connectedCallback(){
    const title = this.getAttribute("title") || "GyuOS";
    const subtitle = this.getAttribute("subtitle") || "Personal AI OS";
    const date = this.getAttribute("date") || "-";
    const updated = this.getAttribute("updated") || "updated -";
    this.innerHTML = `
      <section class="gy-page-header">
        <div class="gy-title-wrap">
          <div class="gy-header-icon">${GYUOS_ICONS.headerBot}</div>
          <div><h1>${title}</h1><p>${subtitle}</p></div>
        </div>
        <div class="gy-top-actions">
          <button class="gy-icon-button" type="button" aria-label="알림">${GYUOS_ICONS.bell}</button>
          <button class="gy-icon-button" type="button" aria-label="새로고침" data-gy-refresh>${GYUOS_ICONS.refresh}</button>
          <div class="gy-updated"><div data-gy-date>${date}</div><div data-gy-updated>${updated}</div></div>
        </div>
      </section>
    `;
    this.querySelector("[data-gy-refresh]")?.addEventListener("click", () => window.dispatchEvent(new CustomEvent("gyuos:refresh")));
  }
}

customElements.define("gyuos-sidebar", GyuosSidebar);
customElements.define("gyuos-header", GyuosHeader);
