(() => {
  const wakeWords = ["일어나", "규비스"];
  const affirmativeWords = ["네", "좋아", "진행해", "부탁해", "응", "그래"];
  const state = {
    standby: false,
    awaitingEveningBriefing: false,
    lastWakeAt: 0
  };

  function normalize(text) {
    return (text || "").trim().toLowerCase();
  }

  function hasAny(text, words) {
    return words.some((word) => text.includes(word));
  }

  function isEvening() {
    return new Date().getHours() >= 18;
  }

  async function activateStandby() {
    state.standby = true;
    state.lastWakeAt = Date.now();
    window.JarvisStandbyUI?.show("네 보스. 듣고 있습니다.");

    if (isEvening()) {
      state.awaitingEveningBriefing = true;
      const greeting = "안녕하세요 보스. 오늘 하루도 고생하셨습니다. 저녁 브리핑을 진행해드릴까요?";
      window.JarvisStandbyUI?.setTranscript("저녁 브리핑을 진행해드릴까요?");
      await window.JarvisTTS?.speak(greeting);
    } else {
      state.awaitingEveningBriefing = false;
      await window.JarvisTTS?.speak("네 보스. 준비되었습니다.");
    }
  }

  async function handleTranscript(rawText) {
    const text = normalize(rawText);
    if (!text) return false;

    window.JarvisStandbyUI?.setTranscript(text);

    if (hasAny(text, wakeWords)) {
      await activateStandby();
      return true;
    }

    if (!state.standby) return false;

    if (state.awaitingEveningBriefing && hasAny(text, affirmativeWords)) {
      state.awaitingEveningBriefing = false;
      await window.JarvisTTS?.speak("네 알겠습니다 보스.");
      await window.JarvisBriefing?.runEveningBriefing();
      return true;
    }

    if (text.includes("브리핑") && (text.includes("진행") || text.includes("시작") || text.includes("해줘"))) {
      state.awaitingEveningBriefing = false;
      await window.JarvisTTS?.speak("네 알겠습니다 보스.");
      await window.JarvisBriefing?.runEveningBriefing();
      return true;
    }

    const browserResult = window.JarvisBrowserActions?.handle(text);
    if (browserResult?.handled) {
      window.JarvisStandbyUI?.setTranscript(browserResult.reply);
      await window.JarvisTTS?.speak(browserResult.reply);
      return true;
    }

    if (text.includes("취소") || text.includes("대기 종료") || text.includes("꺼져")) {
      state.awaitingEveningBriefing = false;
      state.standby = false;
      window.JarvisStandbyUI?.hide();
      await window.JarvisTTS?.speak("대기 모드를 종료하겠습니다.");
      return true;
    }

    return false;
  }

  window.JarvisWakeword = {
    handleTranscript,
    activateStandby,
    isStandby: () => state.standby,
    simulate: handleTranscript
  };
})();
