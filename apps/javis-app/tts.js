(() => {
  const DEFAULT_VOICE_HINTS = ["Google 한국의", "Microsoft Heami", "Microsoft SunHi", "ko-KR"];

  function getKoreanVoice() {
    const synth = window.speechSynthesis;
    if (!synth) return null;

    const voices = synth.getVoices();
    return voices.find((voice) => DEFAULT_VOICE_HINTS.some((hint) => voice.name.includes(hint)))
      || voices.find((voice) => voice.lang && voice.lang.toLowerCase().startsWith("ko"))
      || voices[0]
      || null;
  }

  function speak(text, options = {}) {
    const synth = window.speechSynthesis;
    if (!synth || !window.SpeechSynthesisUtterance) {
      options.onUnsupported?.();
      return Promise.resolve(false);
    }

    return new Promise((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "ko-KR";
      utterance.rate = options.rate ?? 1.15;
      utterance.pitch = options.pitch ?? 0.9;
      utterance.volume = options.volume ?? 1;

      const voice = getKoreanVoice();
      if (voice) utterance.voice = voice;

      utterance.onstart = () => options.onStart?.();
      utterance.onend = () => resolve(true);
      utterance.onerror = () => resolve(false);

      if (options.interrupt !== false) synth.cancel();
      synth.speak(utterance);
    });
  }

  function stop() {
    window.speechSynthesis?.cancel();
  }

  window.JarvisTTS = { speak, stop };
})();
