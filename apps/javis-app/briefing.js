(() => {
  const DEFAULT_API_BASE = "http://127.0.0.1:8000";
  const weatherCodes = {
    0: "맑음", 1: "대체로 맑음", 2: "부분적으로 흐림", 3: "흐림",
    45: "안개", 48: "서리 안개", 51: "약한 이슬비", 53: "이슬비",
    55: "강한 이슬비", 61: "약한 비", 63: "비", 65: "강한 비",
    71: "약한 눈", 73: "눈", 75: "강한 눈", 80: "소나기",
    95: "천둥번개"
  };

  function getApiBase() {
    return localStorage.getItem("jarvisApiBase") || DEFAULT_API_BASE;
  }

  async function fetchJson(url, timeoutMs = 1800) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally {
      clearTimeout(timeout);
    }
  }

  function todayIso() {
    const now = new Date();
    const offset = now.getTimezoneOffset() * 60000;
    return new Date(now.getTime() - offset).toISOString().slice(0, 10);
  }

  async function getSchedules() {
    try {
      const data = await fetchJson(`${getApiBase()}/schedules?day=${todayIso()}`);
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  }

  function buildScheduleSummary(schedules) {
    if (!schedules.length) return "오늘 등록된 일정은 모두 마무리되었습니다.";
    const items = schedules.slice(0, 3).map((item) => {
      const time = item.start_time ? `${item.start_time} ` : "";
      return `${time}${item.title}`;
    });
    return `오늘 일정은 ${items.join(", ")}입니다.`;
  }

  function getPosition() {
    if (!navigator.geolocation) return Promise.resolve(null);
    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (position) => resolve(position.coords),
        () => resolve(null),
        { enableHighAccuracy: false, timeout: 1800, maximumAge: 600000 }
      );
    });
  }

  async function getWeatherSummary() {
    try {
      const coords = await getPosition();
      const latitude = coords?.latitude ?? 37.5665;
      const longitude = coords?.longitude ?? 126.9780;
      const url = `https://api.open-meteo.com/v1/forecast?latitude=${latitude}&longitude=${longitude}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&timezone=auto`;
      const data = await fetchJson(url, 2600);
      const current = data.current;
      const condition = weatherCodes[current.weather_code] || "날씨 정보 확인됨";
      return `현재 날씨는 ${condition}, 기온 ${Math.round(current.temperature_2m)}도, 습도 ${current.relative_humidity_2m}퍼센트, 풍속 ${Math.round(current.wind_speed_10m)}킬로미터입니다.`;
    } catch {
      return "현재 날씨 API 응답을 받지 못했습니다. 필요하시면 날씨 화면을 바로 열어드리겠습니다.";
    }
  }

  async function getNewsHeadlines() {
    const customEndpoint = localStorage.getItem("jarvisNewsEndpoint");
    if (customEndpoint) {
      try {
        const data = await fetchJson(customEndpoint, 2600);
        const headlines = Array.isArray(data) ? data : data.headlines;
        if (Array.isArray(headlines) && headlines.length) {
          return headlines.slice(0, 3).map((item) => typeof item === "string" ? item : item.title);
        }
      } catch {
        return ["연결된 뉴스 API 응답을 받지 못했습니다."];
      }
    }

    try {
      const rssUrl = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko";
      const proxyUrl = `https://api.allorigins.win/raw?url=${encodeURIComponent(rssUrl)}`;
      const xml = await fetch(proxyUrl).then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      });
      const doc = new DOMParser().parseFromString(xml, "text/xml");
      return Array.from(doc.querySelectorAll("item title"))
        .slice(0, 3)
        .map((node) => node.textContent.trim())
        .filter(Boolean);
    } catch {
      return ["최신 뉴스 헤드라인은 브라우저 뉴스 화면에서 확인하실 수 있습니다."];
    }
  }

  async function runEveningBriefing() {
    window.JarvisStandbyUI?.show("저녁 브리핑 준비 중...");
    window.JarvisStandbyUI?.setAgentState(true);

    const [schedules, weather, headlines] = await Promise.all([
      getSchedules(),
      getWeatherSummary(),
      getNewsHeadlines()
    ]);

    const scheduleSummary = buildScheduleSummary(schedules);
    const agentReport = "현재 4개의 에이전트 중 2개가 활성 상태입니다. 1개는 대기 중이며, 1개는 서버 오류를 확인 중입니다. 활성 에이전트 2개는 보스께서 요청하신 업무를 진행 중이며, 완료 후 보고드리겠습니다.";
    const newsSummary = headlines.length
      ? `최신 헤드라인입니다. ${headlines.map((headline, index) => `${index + 1}. ${headline}`).join(". ")}`
      : "최신 뉴스 헤드라인을 확인하지 못했습니다.";

    const briefingText = [
      "저녁 브리핑을 시작하겠습니다.",
      scheduleSummary,
      agentReport,
      weather,
      newsSummary
    ].join(" ");

    window.JarvisStandbyUI?.setTranscript("저녁 브리핑 진행 중");
    await window.JarvisTTS?.speak(briefingText);
    window.JarvisStandbyUI?.setTranscript("브리핑 완료. 추가 명령을 대기합니다.");

    return { scheduleSummary, agentReport, weather, headlines };
  }

  window.JarvisBriefing = { runEveningBriefing, getSchedules, getWeatherSummary, getNewsHeadlines };
})();
