(() => {
  const pages = [
    { keys: ["네이버"], label: "네이버", url: "https://www.naver.com" },
    { keys: ["구글", "google"], label: "구글", url: "https://www.google.com" },
    { keys: ["유튜브", "youtube"], label: "유튜브", url: "https://www.youtube.com" },
    { keys: ["gpt", "지피티", "챗지피티", "chatgpt"], label: "GPT", url: "https://chatgpt.com" }
  ];

  function normalize(text) {
    return (text || "").trim().toLowerCase();
  }

  function openUrl(url) {
    if (window.jarvis?.openExternal) {
      window.jarvis.openExternal(url);
      return;
    }
    window.open(url, "_blank", "noopener,noreferrer");
  }

  function openYouTubeMusic(text) {
    const query = text.includes("ncs")
      ? "NCS music playlist"
      : text.replace(/유튜브에서|유튜브|틀어줘|재생해|음악|노래/g, "").trim() || "NCS music playlist";
    openUrl(`https://www.youtube.com/results?search_query=${encodeURIComponent(query)}`);
    return {
      handled: true,
      reply: "네 보스. 유튜브에서 요청하신 음악을 검색하겠습니다."
    };
  }

  function handle(text) {
    const command = normalize(text);
    if (!command) return { handled: false };

    if (command.includes("유튜브") && (command.includes("틀어") || command.includes("재생") || command.includes("ncs"))) {
      return openYouTubeMusic(command);
    }

    if (command.includes("뉴스") && (command.includes("보여") || command.includes("열어"))) {
      openUrl("https://news.google.com/topstories?hl=ko&gl=KR&ceid=KR:ko");
      return { handled: true, reply: "네 보스. 최신 뉴스 화면을 열겠습니다." };
    }

    if (command.includes("날씨") && (command.includes("보여") || command.includes("열어"))) {
      openUrl("https://www.google.com/search?q=%ED%98%84%EC%9E%AC+%EB%82%A0%EC%94%A8");
      return { handled: true, reply: "네 보스. 현재 날씨 정보를 열겠습니다." };
    }

    const page = pages.find((item) => item.keys.some((key) => command.includes(key)));
    if (page && (command.includes("열어") || command.includes("켜줘") || command.includes("보여") || command === page.keys[0])) {
      openUrl(page.url);
      return { handled: true, reply: `네 보스. ${page.label}를 열겠습니다.` };
    }

    return { handled: false };
  }

  window.JarvisBrowserActions = { handle, openUrl };
})();
