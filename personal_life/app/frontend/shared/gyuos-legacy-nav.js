(function(){
  const items = [
    ["home", "/", "home", "홈"],
    ["briefing", "/briefing.html", "briefing", "브리핑"],
    ["schedule", "/schedule.html", "calendar", "일정"],
    ["money", "/money-core", "money", "돈 관리"],
    ["drive", "/drive.html", "car", "자동차"],
    ["creator", "/creator.html", "sparkles", "Creator Studio"],
    ["agent", "/agent/report-center", "grid", "에이전트 대시보드"],
    ["memory", "/memory.html", "search", "기억 검색"],
    ["memo", "/memo.html", "memo", "메모"],
    ["routine", "/routine.html", "target", "루틴 & 목표"],
    ["settings", "/settings.html", "settings", "설정"],
  ];
  const icons = window.GYUOS_ICONS || {
    home: '<svg viewBox="0 0 24 24"><path d="M4 11.5 12 5l8 6.5"></path><path d="M6.5 10.5V20h11v-9.5"></path></svg>',
    briefing: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"></circle><path d="M12 8v8M8 12h8"></path></svg>',
    calendar: '<svg viewBox="0 0 24 24"><rect x="5" y="6" width="14" height="14" rx="2"></rect><path d="M8 4v4M16 4v4M5 10h14"></path></svg>',
    money: '<svg viewBox="0 0 24 24"><rect x="6" y="5" width="12" height="14" rx="2"></rect><path d="M9 9h6M9 13h4"></path><circle cx="16" cy="16" r="1.4"></circle></svg>',
    car: '<svg viewBox="0 0 24 24"><path d="M4 15h16"></path><path d="m6 15 2.2-5h7.6L18 15"></path><path d="M7 17h.01M17 17h.01"></path></svg>',
    sparkles: '<svg viewBox="0 0 24 24"><path d="M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8L12 3Z"></path><path d="M19 14l.9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9L19 14Z"></path></svg>',
    grid: '<svg viewBox="0 0 24 24"><path d="M5 5h4v4H5zM10 5h4v4h-4zM15 5h4v4h-4zM5 10h4v4H5zM10 10h4v4h-4zM15 10h4v4h-4zM5 15h4v4H5zM10 15h4v4h-4zM15 15h4v4h-4z"></path></svg>',
    search: '<svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="4.5"></circle><path d="m14 14 5 5"></path></svg>',
    memo: '<svg viewBox="0 0 24 24"><path d="M6 5h12M6 9h12M6 13h12M6 17h12"></path></svg>',
    target: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"></circle><circle cx="12" cy="12" r="4.8"></circle><circle cx="12" cy="12" r="1.8"></circle></svg>',
    settings: '<svg viewBox="0 0 24 24"><path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z"></path><path d="M18.5 13.5v-3l-2-.5-.8-1.8 1.1-1.8-2.1-2.1-1.8 1.1-1.8-.8-.6-2h-3l-.5 2-1.8.8-1.8-1.1-2.1 2.1 1.1 1.8-.8 1.8-2 .5v3l2 .5.8 1.8-1.1 1.8 2.1 2.1 1.8-1.1 1.8.8.5 2h3l.6-2 1.8-.8 1.8 1.1 2.1-2.1-1.1-1.8.8-1.8 2-.5Z"></path></svg>',
  };
  const path = location.pathname;
  const active = path.includes("schedule") ? "schedule" : path.includes("money") ? "money" : path.includes("drive") ? "drive" : path.includes("memory") ? "memory" : path.includes("memo") ? "memo" : path.includes("routine") ? "routine" : path.includes("settings") ? "settings" : path.includes("creator") ? "creator" : path.includes("briefing") ? "briefing" : "home";
  const style = document.createElement("style");
  style.textContent = ".logo{cursor:pointer}.nav .ico svg{width:19px;height:19px;stroke:currentColor;stroke-width:1.9;fill:none;stroke-linecap:round;stroke-linejoin:round}.nav a{font-family:\"Malgun Gothic\",\"맑은 고딕\",\"Nanum Gothic\",\"나눔고딕\",Arial,sans-serif}";
  document.head.appendChild(style);
  const logo = document.querySelector(".logo");
  if(logo){
    logo.setAttribute("role","link");
    logo.setAttribute("tabindex","0");
    logo.addEventListener("click",()=>{location.href="/"});
    logo.addEventListener("keydown",(event)=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();location.href="/";}});
  }
  const nav = document.querySelector(".nav");
  if(nav){
    nav.innerHTML = items.map(([key, href, icon, label]) => `<a href="${href}" class="${key===active?"active":""}"><span class="ico">${icons[icon]||""}</span>${label}</a>`).join("");
  }
})();
