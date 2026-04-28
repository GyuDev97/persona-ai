(() => {
  const rootId = "jarvisStandbyOverlay";
  let root = null;

  function ensureStyles() {
    if (document.getElementById("jarvisStandbyStyles")) return;
    const style = document.createElement("style");
    style.id = "jarvisStandbyStyles";
    style.textContent = `
      #${rootId} {
        position: fixed;
        inset: 0;
        z-index: 80;
        display: grid;
        place-items: center;
        opacity: 0;
        pointer-events: none;
        background:
          radial-gradient(circle at 50% 45%, rgba(41, 240, 255, 0.18), transparent 34%),
          linear-gradient(180deg, rgba(0, 8, 12, 0.2), rgba(0, 0, 0, 0.68));
        backdrop-filter: blur(2px);
        transition: opacity 260ms ease;
      }

      #${rootId}.is-active {
        opacity: 1;
        pointer-events: auto;
      }

      .standby-hud {
        position: relative;
        width: min(78vmin, 680px);
        aspect-ratio: 1;
        display: grid;
        place-items: center;
        color: #eaffff;
      }

      .standby-ring,
      .standby-ring::before,
      .standby-ring::after {
        position: absolute;
        inset: 8%;
        border: 1px solid rgba(91, 241, 255, 0.22);
        border-radius: 50%;
        box-shadow: 0 0 36px rgba(65, 220, 255, 0.18), inset 0 0 34px rgba(65, 220, 255, 0.08);
        animation: standbySpin 18s linear infinite;
      }

      .standby-ring::before,
      .standby-ring::after {
        content: "";
        inset: 11%;
      }

      .standby-ring::before {
        border-style: dashed;
        animation: standbySpin 12s linear infinite reverse;
      }

      .standby-ring::after {
        inset: 24%;
        border-color: rgba(149, 255, 229, 0.3);
        animation-duration: 8s;
      }

      .standby-orb {
        position: relative;
        width: min(31vmin, 230px);
        aspect-ratio: 1;
        border-radius: 50%;
        background:
          radial-gradient(circle at 48% 42%, #eaffff 0 4%, #90fff0 8%, #24e0ff 24%, rgba(9, 88, 118, 0.52) 54%, rgba(0, 8, 12, 0.18) 72%),
          radial-gradient(circle, rgba(65, 220, 255, 0.95), rgba(65, 220, 255, 0.08));
        box-shadow:
          0 0 28px rgba(128, 255, 239, 0.8),
          0 0 86px rgba(42, 218, 255, 0.42),
          inset 0 0 48px rgba(255, 255, 255, 0.18);
        animation: standbyPulse 2.8s ease-in-out infinite;
      }

      .standby-orb::after {
        content: "";
        position: absolute;
        inset: -18%;
        border-radius: 50%;
        border: 1px solid rgba(165, 255, 242, 0.28);
        animation: standbyPing 2s ease-out infinite;
      }

      .standby-text {
        position: absolute;
        bottom: 15%;
        text-align: center;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        text-shadow: 0 0 18px rgba(91, 241, 255, 0.7);
      }

      .standby-title {
        font-size: clamp(18px, 3vmin, 28px);
        margin-bottom: 12px;
      }

      .standby-transcript {
        min-height: 24px;
        font-size: 13px;
        letter-spacing: 0;
        color: rgba(219, 252, 255, 0.82);
      }

      .standby-wave {
        position: absolute;
        bottom: 8%;
        display: flex;
        align-items: end;
        gap: 7px;
        height: 38px;
      }

      .standby-wave span {
        width: 4px;
        min-height: 7px;
        border-radius: 999px;
        background: rgba(138, 255, 238, 0.8);
        box-shadow: 0 0 14px rgba(96, 236, 255, 0.65);
        animation: standbyWave 920ms ease-in-out infinite;
      }

      .standby-wave span:nth-child(2n) { animation-delay: 120ms; }
      .standby-wave span:nth-child(3n) { animation-delay: 220ms; }

      .standby-agents {
        position: absolute;
        top: 12%;
        display: grid;
        grid-template-columns: repeat(4, minmax(70px, 1fr));
        gap: 10px;
        width: min(72vw, 520px);
      }

      .standby-agent {
        border: 1px solid rgba(93, 237, 255, 0.22);
        background: rgba(5, 28, 36, 0.34);
        padding: 9px 10px;
        font-size: 11px;
        color: rgba(220, 253, 255, 0.86);
        text-align: center;
        box-shadow: inset 0 0 18px rgba(86, 222, 255, 0.08);
      }

      @keyframes standbySpin { to { transform: rotate(360deg); } }
      @keyframes standbyPulse {
        0%, 100% { transform: scale(0.98); filter: brightness(0.96); }
        50% { transform: scale(1.035); filter: brightness(1.14); }
      }
      @keyframes standbyPing {
        0% { transform: scale(0.9); opacity: 0.5; }
        100% { transform: scale(1.25); opacity: 0; }
      }
      @keyframes standbyWave {
        0%, 100% { height: 9px; opacity: 0.55; }
        50% { height: 34px; opacity: 1; }
      }

      @media (max-width: 720px) {
        .standby-agents {
          grid-template-columns: repeat(2, minmax(80px, 1fr));
          top: 7%;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function ensureRoot() {
    if (root) return root;
    ensureStyles();
    root = document.createElement("div");
    root.id = rootId;
    root.innerHTML = `
      <div class="standby-hud" role="dialog" aria-live="polite" aria-label="GYUVIS standby">
        <div class="standby-agents">
          <div class="standby-agent">AGENT 01<br>READY</div>
          <div class="standby-agent">AGENT 02<br>READY</div>
          <div class="standby-agent">AGENT 03<br>READY</div>
          <div class="standby-agent">AGENT 04<br>READY</div>
        </div>
        <div class="standby-ring"></div>
        <div class="standby-orb"></div>
        <div class="standby-text">
          <div class="standby-title">Listening...</div>
          <div class="standby-transcript"></div>
        </div>
        <div class="standby-wave">
          <span></span><span></span><span></span><span></span><span></span><span></span><span></span>
        </div>
      </div>
    `;
    document.body.appendChild(root);
    return root;
  }

  function show(message = "준비되었습니다.") {
    const overlay = ensureRoot();
    overlay.classList.add("is-active");
    setTranscript(message);
  }

  function hide() {
    if (!root) return;
    root.classList.remove("is-active");
  }

  function setTranscript(text) {
    const overlay = ensureRoot();
    const transcript = overlay.querySelector(".standby-transcript");
    transcript.textContent = text || "";
  }

  function setAgentState(active = true) {
    const overlay = ensureRoot();
    overlay.querySelectorAll(".standby-agent").forEach((agent, index) => {
      agent.innerHTML = `AGENT 0${index + 1}<br>${active ? "ACTIVE" : "READY"}`;
    });
  }

  window.JarvisStandbyUI = { show, hide, setTranscript, setAgentState };
})();
