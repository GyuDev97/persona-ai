const canvas = document.getElementById("c");
const ctx = canvas.getContext("2d");
const video = document.getElementById("video");
const statusEl = document.getElementById("status");
const voiceBtn = document.getElementById("voiceBtn");
const voiceState = document.getElementById("voiceState");

let W = innerWidth;
let H = innerHeight;
canvas.width = W;
canvas.height = H;

addEventListener("resize", () => {
  W = innerWidth;
  H = innerHeight;
  canvas.width = W;
  canvas.height = H;
});

let orb = { x: W / 2, y: H / 2, r: 170, targetR: 170, vx: 0, vy: 0 };
let prevPalm = null;
let lastSwipe = 0;
let lastMaximize = 0;
let lastMinimize = 0;
let lastDrag = 0;
let voiceOn = false;
let gestureLockUntil = performance.now() + 3500;
let recognition = null;

const dots = [];
for (let i = 0; i < 950; i++) {
  dots.push({
    a: Math.random() * Math.PI * 2,
    t: Math.random() * Math.PI,
    s: Math.random() * 1 + 0.2
  });
}

function setStatus(msg) {
  statusEl.textContent = msg;
}

window.jarvis.onStatus((msg) => setStatus(msg));

function dist(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function draw() {
  requestAnimationFrame(draw);
  ctx.fillStyle = "rgba(0,0,0,.18)";
  ctx.fillRect(0, 0, W, H);

  orb.r += (orb.targetR - orb.r) * 0.1;
  orb.x += orb.vx;
  orb.y += orb.vy;
  orb.vx *= 0.9;
  orb.vy *= 0.9;

  ctx.save();
  ctx.translate(orb.x, orb.y);

  for (const p of dots) {
    p.a += 0.003 * p.s;
    p.t += 0.002 * p.s;

    const rr = orb.r * (0.45 + 0.55 * Math.sin(p.t));
    const x = Math.cos(p.a) * rr;
    const y = Math.sin(p.a) * rr;
    const alpha = 0.32 + 0.68 * Math.sin(p.t * 2);

    ctx.beginPath();
    ctx.fillStyle = `rgba(0,220,255,${alpha})`;
    ctx.shadowBlur = 12;
    ctx.shadowColor = "cyan";
    ctx.arc(x, y, 1.2 + p.s, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.restore();
}

draw();

function isFist(lm) {
  const palm = lm[0];
  const tips = [lm[8], lm[12], lm[16], lm[20]];
  const avg = tips.reduce((sum, tip) => sum + dist(palm, tip), 0) / tips.length;
  return avg < 0.16;
}

function isPinch(lm) {
  return dist(lm[4], lm[8]) < 0.055;
}

function setupHands() {
  const hands = new Hands({
    locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`
  });

  hands.setOptions({
    maxNumHands: 2,
    modelComplexity: 1,
    minDetectionConfidence: 0.6,
    minTrackingConfidence: 0.6
  });

  hands.onResults((results) => {
    if (!results.multiHandLandmarks || !results.multiHandLandmarks.length) {
      setStatus("손이 감지되지 않음");
      prevPalm = null;
      return;
    }

    const handsArr = results.multiHandLandmarks;
    const lm = handsArr[0];
    const palm = lm[0];
    const thumb = lm[4];
    const index = lm[8];
    const middle = lm[12];
    const ring = lm[16];
    const pinky = lm[20];

    const spread =
      dist(palm, thumb) +
      dist(palm, index) +
      dist(palm, middle) +
      dist(palm, ring) +
      dist(palm, pinky);

    let target = Math.max(90, Math.min(320, spread * 140));

    const px = (1 - palm.x) * W;
    const py = palm.y * H;
    orb.x += (px - orb.x) * 0.22;
    orb.y += (py - orb.y) * 0.22;

    const now = performance.now();

    if (prevPalm) {
      const dx = palm.x - prevPalm.x;
      const dy = palm.y - prevPalm.y;

      orb.vx += dx * 90;
      orb.vy += dy * 90;

      if (now < gestureLockUntil) { prevPalm = { x: palm.x, y: palm.y }; orb.targetR = target; setStatus('손 인식 안정화 중...'); return; }

      // 1) 손 좌/우 스와이프: 모니터 이동
      if (now - lastSwipe > 900) {
        if (dx > 0.11) {
          orb.vx += 65;
          window.jarvis.moveMonitor("right");
          setStatus("오른쪽 스와이프 → 다음 모니터");
          lastSwipe = now;
        } else if (dx < -0.11) {
          orb.vx -= 65;
          window.jarvis.moveMonitor("left");
          setStatus("왼쪽 스와이프 → 이전 모니터");
          lastSwipe = now;
        }
      }

      // 4) 집기: 창 잡아서 드래그
      if (isPinch(lm) && now - lastDrag > 25) {
        if(Number.isFinite(dx)&&Number.isFinite(dy)) window.jarvis.nudge({ x: -dx * 2600, y: dy * 1800 });
        setStatus("집기 드래그 중");
        lastDrag = now;
      }
    }

    // 3) 주먹: 안정화 버전에서는 최소화 비활성화
    if (isFist(lm) && now - lastMinimize > 2500) {
      lastMinimize = now;
      setStatus("주먹 감지");
    }

    if (handsArr.length === 2) {
      const p1 = handsArr[0][0];
      const p2 = handsArr[1][0];
      const twoHandDist = Math.hypot(p1.x - p2.x, p1.y - p2.y);

      target = Math.max(target, Math.min(430, twoHandDist * 900));

      const midx = ((1 - p1.x) * W + (1 - p2.x) * W) / 2;
      const midy = (p1.y * H + p2.y * H) / 2;
      orb.x += (midx - orb.x) * 0.18;
      orb.y += (midy - orb.y) * 0.18;

      // 2) 양손 펼치기: 최대화
      if (twoHandDist > 0.55 && now - lastMaximize > 2200) {
        window.jarvis.maximize();
        setStatus("양손 펼치기 → 최대화");
        lastMaximize = now;
      }
    }

    orb.targetR = target;
    prevPalm = { x: palm.x, y: palm.y };
    setStatus(handsArr.length === 2 ? "두 손 감지" : "한 손 감지");
  });

  const camera = new Camera(video, {
    onFrame: async () => {
      await hands.send({ image: video });
    },
    width: 640,
    height: 480
  });

  camera.start()
    .then(() => setStatus("카메라 준비 완료"))
    .catch(() => setStatus("카메라 권한을 허용해주세요."));
}

function setupVoice() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    voiceState.textContent = "음성 미지원";
    voiceBtn.disabled = true;
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "ko-KR";
  recognition.continuous = true;
  recognition.interimResults = false;

  recognition.onstart = () => {
    voiceOn = true;
    voiceState.textContent = "음성 ON / 한국어";
    setStatus("한국어 음성 인식 ON");
  };

  recognition.onend = () => {
    voiceOn = false;
    voiceState.textContent = "음성 OFF";
  };

  recognition.onerror = (event) => {
    setStatus("음성 인식 오류: " + event.error);
  };

  recognition.onresult = (event) => {
    const last = event.results[event.results.length - 1];
    const text = last[0].transcript.trim().toLowerCase();
    setStatus("음성: " + text);

    if (text.includes("오른쪽") || text.includes("다음") || text.includes("우측")) {
      window.jarvis.moveMonitor("right");
    }

    if (text.includes("왼쪽") || text.includes("이전") || text.includes("좌측")) {
      window.jarvis.moveMonitor("left");
    }

    if (text.includes("최대화") || text.includes("크게") || text.includes("전체")) {
      window.jarvis.maximize();
    }

    if (text.includes("최소화") || text.includes("작게") || text.includes("숨겨")) {
      window.jarvis.minimize();
    }

    if (text.includes("복원") || text.includes("돌아와")) {
      window.jarvis.restore();
    }

    if (text.includes("항상 위") || text.includes("위에 고정")) {
      window.jarvis.toggleAlwaysOnTop();
    }
  };

  voiceBtn.addEventListener("click", () => {
    if (!recognition) return;
    if (voiceOn) recognition.stop();
    else recognition.start();
  });

  window.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() === "v") {
      if (voiceOn) recognition.stop();
      else recognition.start();
    }
  });
}

window.addEventListener("keydown", (e) => {
  if (e.key === "ArrowRight") window.jarvis.moveMonitor("right");
  if (e.key === "ArrowLeft") window.jarvis.moveMonitor("left");
  if (e.key === "ArrowUp") window.jarvis.maximize();
  if (e.key === "ArrowDown") window.jarvis.minimize();
  if (e.key.toLowerCase() === "t") window.jarvis.toggleAlwaysOnTop();
});

setupHands();
setupVoice();
