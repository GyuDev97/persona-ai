const canvas = document.getElementById("c");
const ctx = canvas.getContext("2d");
const video = document.getElementById("video");
const statusEl = document.getElementById("status");
const voiceBtn = document.getElementById("voiceBtn");
const voiceState = document.getElementById("voiceState");
const jarvis = window.jarvis || {
  getDisplays: async () => [],
  moveMonitor: () => {},
  maximize: () => {},
  minimize: () => {},
  restore: () => {},
  toggleAlwaysOnTop: () => {},
  nudge: () => {},
  onStatus: () => {}
};

let W = innerWidth;
let H = innerHeight;
canvas.width = W;
canvas.height = H;

const graphCenter = { x: W * 0.22, y: H * 0.32 };
let graphRadius = Math.min(W, H) * 0.24;
let prevPalm = null;
let lastSwipe = 0;
let lastMaximize = 0;
let lastDrag = 0;
let voiceOn = false;
let recognition = null;
let hasWelcomedBoss = false;
let lastSeenAt = 0;
let gestureLockUntil = performance.now() + 3200;
const handMarkerHoldMs = 720;
const trackedHands = [];
const handConnections = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17]
];
const fingertipLandmarkIndexes = new Set([4, 8, 12, 16, 20]);
const palmLandmarkIndexes = [0, 5, 9, 13, 17];
let graphFollowX = graphCenter.x;
let graphFollowY = graphCenter.y;
let graphScale = 1;
let gestureScaleBoost = 1;
let selectedLabelIndex = -1;
let draggedLabelIndex = -1;
let dragOffsetX = 0;
let dragOffsetY = 0;
let expandedDetailIndex = -1;
let lastDetailExpand = 0;
let lastSelectedLabelIndex = -1;
let lastSelectedAt = 0;

const labels = [
  "JARVIS CORE",
  "Human Context",
  "Affective Loop",
  "Voice Control",
  "Spatial Reasoning",
  "Gesture Zoom",
  "Language Mesh",
  "Window Control",
  "Dream Archive",
  "Bio Signals",
  "Latent Motion",
  "Sensorium",
  "Signal Ethics",
  "Flight Deck",
  "Reflective Core",
  "Adaptive Will",
  "Soft Agency",
  "Context Bloom",
  "Perception Grid",
  "Temporal Drift",
  "Inference Skin",
  "Feedback Spine"
];

const nodes = labels.map((label, index) => {
  const ring = 0.3 + (index % 5) * 0.16;
  const angle = (index / labels.length) * Math.PI * 2 + (index % 2) * 0.12;
  return {
    label,
    x: graphCenter.x + Math.cos(angle) * graphRadius * ring,
    y: graphCenter.y + Math.sin(angle) * graphRadius * ring,
    homeX: graphCenter.x + Math.cos(angle) * graphRadius * ring,
    homeY: graphCenter.y + Math.sin(angle) * graphRadius * ring,
    vx: 0,
    vy: 0,
    size: 2.4 + (index % 4) * 0.7,
    alpha: 0.82,
    energy: Math.random(),
    showLabel: index % 3 === 0 || index === 0 || index === 5 || index === 7 || index === 13
  };
});

const edges = [];
for (let i = 0; i < nodes.length; i += 1) {
  edges.push([i, (i + 1) % nodes.length]);
  edges.push([i, (i + 4) % nodes.length]);
  edges.push([i, (i + 7) % nodes.length]);
  if (i % 3 === 0) edges.push([i, (i + 11) % nodes.length]);
}

const particles = Array.from({ length: 220 }, () => ({
  orbit: Math.random() * Math.PI * 2,
  ring: 0.18 + Math.random() * 1.05,
  drift: 0.3 + Math.random() * 1.4,
  size: 0.8 + Math.random() * 2.4,
  alpha: 0.22 + Math.random() * 0.5,
  offset: (Math.random() - 0.5) * graphRadius * 0.95,
  wobble: Math.random() * Math.PI * 2
}));

const clusterLabels = [
  { text: "대화 인터페이스", detail: "음성 · 텍스트 · TTS 응답", angle: -1.28, radius: 0.68, dx: -34, dy: -12, align: "left", nodeIndex: 5 },
  { text: "개인 운영 비서", detail: "브리핑 · 일정 · 루틴 체크", angle: -0.52, radius: 0.42, dx: 18, dy: -18, align: "left", nodeIndex: 0 },
  { text: "PC 에이전트", detail: "브라우저 · 검색 · 결과 요약", angle: 0.28, radius: 0.82, dx: 52, dy: 4, align: "left", nodeIndex: 7 },
  { text: "리마인드 / 실행", detail: "예약 · 할 일 · 빠른 메모", angle: 1.12, radius: 0.52, dx: -18, dy: 24, align: "left", nodeIndex: 3 },
  { text: "재정 비서", detail: "지출 · 자산 · 소비 흐름", angle: 2.38, radius: 0.7, dx: -56, dy: 18, align: "right", nodeIndex: 6 },
  { text: "개인 기억", detail: "성향 · 맥락 · 메모 기록", angle: 3.02, radius: 0.62, dx: -54, dy: -12, align: "right", nodeIndex: 4 }
];

const detailPanels = {
  "대화 인터페이스": {
    title: "대화 인터페이스",
    subtitle: "음성 · 텍스트 · TTS 응답",
    lines: [
      "음성 입력과 텍스트 입력을 함께 처리합니다.",
      "TTS 응답과 대화 히스토리를 연결합니다.",
      "애매한 질문에는 선택지를 제안합니다."
    ]
  },
  "개인 운영 비서": {
    title: "개인 운영 비서",
    subtitle: "브리핑 · 일정 · 루틴 체크",
    lines: [
      "오늘, 아침, 저녁 브리핑을 정리합니다.",
      "할 일 추천과 일정 정리를 지원합니다.",
      "루틴 체크로 하루 운영을 돕습니다."
    ]
  },
  "PC 에이전트": {
    title: "PC 에이전트",
    subtitle: "브라우저 · 검색 · 결과 요약",
    lines: [
      "브라우저 열기와 웹 검색을 실행합니다.",
      "뉴스, 날씨, 일반 검색 결과를 요약합니다.",
      "PC에서 반복 작업을 대행합니다."
    ]
  },
  "리마인드 / 실행": {
    title: "리마인드 / 실행",
    subtitle: "예약 · 할 일 · 빠른 메모",
    lines: [
      "리마인드를 예약하고 오늘 할 일을 안내합니다.",
      "일정과 할 일을 자동으로 분류합니다.",
      "빠른 메모를 즉시 저장합니다."
    ]
  },
  "재정 비서": {
    title: "재정 비서",
    subtitle: "지출 · 자산 · 소비 흐름",
    lines: [
      "지출 브리핑과 자산 관리를 제공합니다.",
      "자산 비중과 소비 흐름을 요약합니다.",
      "현금 목표 시뮬레이션을 지원합니다."
    ]
  },
  "개인 기억": {
    title: "개인 기억",
    subtitle: "성향 · 맥락 · 메모 기록",
    lines: [
      "사용자 성향과 생활 패턴을 기억합니다.",
      "대화 맥락과 메모 기록을 연결합니다.",
      "개인화된 응답에 필요한 기억을 불러옵니다."
    ]
  }
};

addEventListener("resize", () => {
  W = innerWidth;
  H = innerHeight;
  canvas.width = W;
  canvas.height = H;
  graphCenter.x = W * 0.22;
  graphCenter.y = H * 0.32;
  graphRadius = Math.min(W, H) * 0.24;

  nodes.forEach((node, index) => {
    const ring = 0.3 + (index % 5) * 0.16;
    const angle = (index / labels.length) * Math.PI * 2 + (index % 2) * 0.12;
    node.homeX = graphCenter.x + Math.cos(angle) * graphRadius * ring;
    node.homeY = graphCenter.y + Math.sin(angle) * graphRadius * ring;
  });
});

function setStatus(message) {
  statusEl.textContent = message;
}

jarvis.onStatus((msg) => setStatus(msg));

function speakWelcomeGreeting() {
  if (hasWelcomedBoss) return;
  const synth = window.speechSynthesis;
  if (!synth) {
    setStatus("음성 합성을 지원하지 않는 환경입니다.");
    return;
  }

  hasWelcomedBoss = true;
  const utterance = new SpeechSynthesisUtterance("어서오세요 보스");
  utterance.lang = "ko-KR";
  utterance.rate = 1;
  utterance.pitch = 0.92;
  utterance.onstart = () => {
    setStatus("어서오세요 보스");
  };
  utterance.onerror = () => {
    setStatus("음성 재생을 시작하지 못했습니다.");
  };

  synth.cancel();
  synth.speak(utterance);
}

function dist(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function isPinch(lm) {
  return dist(lm[4], lm[8]) < 0.055;
}

function pinchAmount(lm) {
  return clamp(dist(lm[4], lm[8]), 0.02, 0.24);
}

function getLandmarkBounds(lm) {
  return lm.reduce((bounds, point) => ({
    minX: Math.min(bounds.minX, point.x),
    maxX: Math.max(bounds.maxX, point.x),
    minY: Math.min(bounds.minY, point.y),
    maxY: Math.max(bounds.maxY, point.y)
  }), {
    minX: Infinity,
    maxX: -Infinity,
    minY: Infinity,
    maxY: -Infinity
  });
}

function isLikelyHand(lm, handedness) {
  if (!lm || lm.length < 21) return false;

  const bounds = getLandmarkBounds(lm);
  const width = (bounds.maxX - bounds.minX) * W;
  const height = (bounds.maxY - bounds.minY) * H;
  const diagonal = Math.hypot(width, height);
  const score = handedness?.score ?? 1;
  const wrist = lm[0];
  const fingertips = [lm[4], lm[8], lm[12], lm[16], lm[20]];
  const spread = fingertips.reduce((sum, point) => sum + dist(wrist, point), 0);

  return score >= 0.72 && diagonal >= 58 && spread >= 0.2;
}

function toTrackedHand(handLm) {
  const palm = handLm[0];
  const fingertips = [handLm[4], handLm[8], handLm[12], handLm[16], handLm[20]];
  const spread = fingertips.reduce((sum, point) => sum + dist(palm, point), 0);
  const fingertip = handLm[8];

  return {
    x: (1 - fingertip.x) * W,
    y: fingertip.y * H,
    radius: clamp(spread * 260, 110, 220),
    pinch: isPinch(handLm),
    landmarks: handLm,
    pinchDistance: pinchAmount(handLm)
  };
}

function distanceToRect(px, py, rect) {
  const dx = Math.max(rect.x - px, 0, px - (rect.x + rect.w));
  const dy = Math.max(rect.y - py, 0, py - (rect.y + rect.h));
  return Math.hypot(dx, dy);
}

function updateLabelInteraction(primaryHand) {
  if (!primaryHand) {
    selectedLabelIndex = -1;
    draggedLabelIndex = -1;
    return;
  }

  let nearestIndex = -1;
  let nearestDistance = Infinity;

  clusterLabels.forEach((label, index) => {
    if (!label.layout) return;
    const cardDistance = distanceToRect(primaryHand.x, primaryHand.y, label.layout.cardRect);
    const anchorDistance = Math.hypot(primaryHand.x - label.layout.anchorX, primaryHand.y - label.layout.anchorY);
    const distance = Math.min(cardDistance, anchorDistance);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  });

  if (primaryHand.pinch && draggedLabelIndex === -1 && nearestIndex !== -1 && nearestDistance < 84) {
    draggedLabelIndex = nearestIndex;
    const layout = clusterLabels[nearestIndex].layout;
    dragOffsetX = clusterLabels[nearestIndex].dx - (primaryHand.x - layout.anchorX);
    dragOffsetY = clusterLabels[nearestIndex].dy - (primaryHand.y - layout.anchorY);
  }

  if (!primaryHand.pinch) {
    draggedLabelIndex = -1;
  }

  if (draggedLabelIndex !== -1) {
    const label = clusterLabels[draggedLabelIndex];
    const layout = label.layout;
    label.dx = clamp((primaryHand.x - layout.anchorX) + dragOffsetX, -560, 560);
    label.dy = clamp((primaryHand.y - layout.anchorY) + dragOffsetY, -380, 380);
    selectedLabelIndex = draggedLabelIndex;
    lastSelectedLabelIndex = draggedLabelIndex;
    lastSelectedAt = performance.now();
    return;
  }

  selectedLabelIndex = nearestDistance < 110 ? nearestIndex : -1;
  if (selectedLabelIndex !== -1) {
    lastSelectedLabelIndex = selectedLabelIndex;
    lastSelectedAt = performance.now();
  }
}

function drawBackground() {
  ctx.clearRect(0, 0, W, H);

  if (video.readyState >= 2) {
    const vw = video.videoWidth || 640;
    const vh = video.videoHeight || 480;
    const scale = Math.max(W / vw, H / vh);
    const dw = vw * scale;
    const dh = vh * scale;
    const dx = (W - dw) / 2;
    const dy = (H - dh) / 2;

    ctx.save();
    ctx.translate(W, 0);
    ctx.scale(-1, 1);
    ctx.filter = "grayscale(0.05) brightness(0.48) contrast(1.02)";
    ctx.drawImage(video, dx, dy, dw, dh);
    ctx.restore();
    ctx.filter = "none";
  } else {
    const bg = ctx.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, "#21191d");
    bg.addColorStop(1, "#040404");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);
  }

  const overlay = ctx.createLinearGradient(0, 0, W, H);
  overlay.addColorStop(0, "rgba(8, 8, 10, 0.28)");
  overlay.addColorStop(0.5, "rgba(7, 7, 8, 0.22)");
  overlay.addColorStop(1, "rgba(4, 4, 5, 0.52)");
  ctx.fillStyle = overlay;
  ctx.fillRect(0, 0, W, H);

  const leftGlow = ctx.createRadialGradient(graphFollowX, graphFollowY, 40, graphFollowX, graphFollowY, graphRadius * graphScale * 1.4);
  leftGlow.addColorStop(0, "rgba(132, 255, 228, 0.16)");
  leftGlow.addColorStop(0.55, "rgba(132, 255, 228, 0.06)");
  leftGlow.addColorStop(1, "rgba(0, 0, 0, 0)");
  ctx.fillStyle = leftGlow;
  ctx.fillRect(0, 0, W, H);
}

function drawFrameMarks() {
  ctx.strokeStyle = "rgba(255,255,255,0.72)";
  ctx.lineWidth = 1;
  const marks = [[20, 96], [W - 54, 96], [20, H - 84], [W - 54, H - 84]];

  marks.forEach(([x, y], index) => {
    const dirX = index % 2 === 0 ? 1 : -1;
    const dirY = index < 2 ? 1 : -1;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 16 * dirX, y);
    ctx.moveTo(x, y);
    ctx.lineTo(x, y + 16 * dirY);
    ctx.stroke();
  });
}

function stepGraph() {
  const primaryHand = trackedHands[0];
  let targetCenterX = W * 0.22;
  let targetCenterY = H * 0.32;
  let targetScale = 1;

  if (primaryHand) {
    const influence = clamp(1 - (primaryHand.x / (W * 0.62)), 0, 1);
    targetCenterX = W * (0.22 + influence * 0.18);
    targetCenterY = H * (0.32 + ((primaryHand.y / H) - 0.5) * 0.16);
    targetScale = 1 + influence * 0.55 + ((primaryHand.radius - 110) / 110) * 0.18;
  }

  targetScale *= gestureScaleBoost;
  targetScale = clamp(targetScale, 0.72, 2.4);

  graphFollowX += (targetCenterX - graphFollowX) * 0.08;
  graphFollowY += (targetCenterY - graphFollowY) * 0.08;
  graphScale += (targetScale - graphScale) * 0.08;

  nodes.forEach((node, index) => {
    const homeDX = node.homeX - W * 0.22;
    const homeDY = node.homeY - H * 0.32;
    const scaledHomeX = graphFollowX + homeDX * graphScale;
    const scaledHomeY = graphFollowY + homeDY * graphScale;

    let fx = (scaledHomeX - node.x) * 0.028;
    let fy = (scaledHomeY - node.y) * 0.028;

    edges.forEach(([a, b]) => {
      if (a !== index && b !== index) return;
      const other = nodes[a === index ? b : a];
      const dx = other.x - node.x;
      const dy = other.y - node.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const desired = 78 * graphScale;
      const spring = (distance - desired) * 0.001;
      fx += dx * spring;
      fy += dy * spring;
    });

    trackedHands.forEach((hand) => {
      const dx = node.x - hand.x;
      const dy = node.y - hand.y;
      const distance = Math.max(18, Math.hypot(dx, dy));
      if (distance < hand.radius) {
        const push = ((hand.radius - distance) / hand.radius) * (hand.pinch ? 0.95 : 1.9);
        fx += (dx / distance) * push * 3.8;
        fy += (dy / distance) * push * 3.8;
        node.alpha = clamp(node.alpha + 0.06, 0.68, 1);
      }

      if (hand.pinch && hand.x < W * 0.55) {
        fx += (hand.x - node.x) * 0.0012;
        fy += (hand.y - node.y) * 0.0012;
      }
    });

    for (let otherIndex = index + 1; otherIndex < nodes.length; otherIndex += 1) {
      const other = nodes[otherIndex];
      const dx = other.x - node.x;
      const dy = other.y - node.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      if (distance < 36) {
        const push = (36 - distance) * 0.0022;
        fx -= dx * push;
        fy -= dy * push;
        other.vx += dx * push;
        other.vy += dy * push;
      }
    }

    node.vx = (node.vx + fx) * 0.91;
    node.vy = (node.vy + fy) * 0.91;
    node.x += node.vx;
    node.y += node.vy;
    node.alpha = clamp(node.alpha * 0.997, 0.68, 1);
    node.energy += 0.02;
  });
}

function drawParticles() {
  ctx.save();
  particles.forEach((particle, index) => {
    particle.orbit += 0.003 * particle.drift;
    particle.wobble += 0.01 * particle.drift;
    const pulse = 0.85 + Math.sin(performance.now() * 0.0014 * particle.drift + index) * 0.2;
    const radius = graphRadius * graphScale * particle.ring * pulse;
    let x = graphFollowX + Math.cos(particle.orbit) * radius;
    let y = graphFollowY + Math.sin(particle.orbit) * radius * 0.78;
    x += Math.cos(particle.wobble * 0.8 + index) * particle.offset * 0.32;
    y += Math.sin(particle.wobble + index * 0.35) * particle.offset * 0.52;

    trackedHands.forEach((hand) => {
      const dx = x - hand.x;
      const dy = y - hand.y;
      const distance = Math.max(10, Math.hypot(dx, dy));
      if (distance < hand.radius * 0.9) {
        const push = ((hand.radius * 0.9 - distance) / (hand.radius * 0.9)) * 24;
        x += (dx / distance) * push;
        y += (dy / distance) * push;
      }
    });

    ctx.beginPath();
    ctx.fillStyle = `rgba(154,255,227,${particle.alpha})`;
    ctx.shadowBlur = 12;
    ctx.shadowColor = "rgba(110,255,220,0.35)";
    ctx.arc(x, y, particle.size, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.restore();
}

function drawClusterLabels() {
  ctx.save();
  ctx.textBaseline = "middle";

  clusterLabels.forEach((label, index) => {
    const isSelected = index === selectedLabelIndex;
    const pulse = 0.9 + Math.sin(performance.now() * 0.0012 + index) * 0.08;
    const anchorRadius = graphRadius * graphScale * label.radius * pulse;
    const anchorX = graphFollowX + Math.cos(label.angle) * anchorRadius;
    const anchorY = graphFollowY + Math.sin(label.angle) * anchorRadius * 0.82;
    const selectedPull = isSelected ? 1.18 : 1;
    const x = anchorX + label.dx * selectedPull;
    const y = anchorY + label.dy * selectedPull;
    const mainFont = isSelected ? 36 : 26;
    const detailFont = isSelected ? 15 : 12;
    ctx.font = `${mainFont}px "Segoe UI", "Noto Sans KR", sans-serif`;
    const textWidth = ctx.measureText(label.text).width;
    ctx.font = `${detailFont}px "Segoe UI", "Noto Sans KR", sans-serif`;
    const detailWidth = ctx.measureText(label.detail).width;
    const cardWidth = Math.max(textWidth, detailWidth) + 22;
    const cardHeight = isSelected ? 64 : 42;
    const cardX = label.align === "right" ? x - cardWidth : x - 6;
    const lineEndX = label.align === "right" ? cardX + cardWidth - 8 : cardX + 8;

    ctx.strokeStyle = isSelected ? "rgba(184, 252, 255, 0.76)" : "rgba(126, 245, 255, 0.38)";
    ctx.lineWidth = isSelected ? 1.5 : 1.1;
    ctx.beginPath();
    ctx.moveTo(anchorX, anchorY);
    ctx.lineTo(lineEndX, y);
    ctx.stroke();

    ctx.beginPath();
    ctx.fillStyle = "rgba(159, 247, 255, 0.92)";
    ctx.arc(anchorX, anchorY, 2.8, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = isSelected ? "rgba(10, 46, 52, 0.62)" : "rgba(7, 35, 40, 0.34)";
    ctx.strokeStyle = isSelected ? "rgba(154, 248, 255, 0.62)" : "rgba(130, 246, 255, 0.18)";
    ctx.lineWidth = isSelected ? 1.3 : 1;
    ctx.beginPath();
    ctx.roundRect(cardX, y - cardHeight / 2, cardWidth, cardHeight, 7);
    ctx.fill();
    ctx.stroke();

    ctx.font = `${mainFont}px "Segoe UI", "Noto Sans KR", sans-serif`;
    ctx.fillStyle = "rgba(184, 249, 255, 0.97)";
    ctx.shadowBlur = 12;
    ctx.shadowColor = "rgba(88, 236, 255, 0.28)";
    ctx.fillText(label.text, cardX + 10, y - (isSelected ? 7 : 0));

    if (isSelected) {
      ctx.font = `${detailFont}px "Segoe UI", "Noto Sans KR", sans-serif`;
      ctx.fillStyle = "rgba(165, 242, 255, 0.84)";
      ctx.fillText(label.detail, cardX + 10, y + 10);
    }

    label.layout = {
      anchorX,
      anchorY,
      cardRect: {
        x: cardX,
        y: y - cardHeight / 2,
        w: cardWidth,
        h: cardHeight
      }
    };
  });

  ctx.restore();
}

function drawHandSkeletons() {
  ctx.save();
  trackedHands.forEach((hand) => {
    if (!hand.landmarks) return;

    const points = hand.landmarks.map((point) => ({
      x: (1 - point.x) * W,
      y: point.y * H
    }));

    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    ctx.shadowBlur = 20;
    ctx.shadowColor = "rgba(72, 235, 255, 0.56)";
    ctx.strokeStyle = "rgba(91, 241, 255, 0.18)";
    ctx.lineWidth = 8;

    handConnections.forEach(([a, b]) => {
      const p1 = points[a];
      const p2 = points[b];
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.stroke();
    });

    ctx.shadowBlur = 14;
    ctx.strokeStyle = "rgba(126, 247, 255, 0.96)";
    ctx.lineWidth = 2.2;

    handConnections.forEach(([a, b]) => {
      const p1 = points[a];
      const p2 = points[b];
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.stroke();
    });

    ctx.shadowBlur = 18;
    ctx.fillStyle = "rgba(18, 60, 66, 0.24)";
    ctx.strokeStyle = "rgba(167, 251, 255, 0.42)";
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    palmLandmarkIndexes.forEach((index, palmIndex) => {
      const point = points[index];
      if (palmIndex === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    points.forEach((point, index) => {
      const isFingertip = fingertipLandmarkIndexes.has(index);
      const isControlTip = index === 8 || index === 4;
      const radius = isControlTip ? 6.2 : isFingertip ? 4.8 : 3;

      ctx.beginPath();
      ctx.fillStyle = isControlTip ? "rgba(244, 255, 255, 0.98)" : "rgba(114, 246, 255, 0.9)";
      ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
      ctx.fill();

      ctx.beginPath();
      ctx.strokeStyle = isControlTip ? "rgba(255, 255, 255, 0.92)" : "rgba(161, 249, 255, 0.62)";
      ctx.lineWidth = isControlTip ? 1.7 : 1.1;
      ctx.arc(point.x, point.y, radius + (isControlTip ? 8 : 3.5), 0, Math.PI * 2);
      ctx.stroke();
    });

    if (hand.pinch) {
      const thumb = points[4];
      const index = points[8];
      ctx.strokeStyle = "rgba(255, 255, 255, 0.86)";
      ctx.lineWidth = 1.4;
      ctx.setLineDash([5, 5]);
      ctx.beginPath();
      ctx.moveTo(thumb.x, thumb.y);
      ctx.lineTo(index.x, index.y);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  });
  ctx.restore();
}

function drawGraph() {
  ctx.save();
  const selectedNodeIndex = selectedLabelIndex === -1 ? -1 : clusterLabels[selectedLabelIndex].nodeIndex;

  edges.forEach(([a, b], index) => {
    const na = nodes[a];
    const nb = nodes[b];
    const gradient = ctx.createLinearGradient(na.x, na.y, nb.x, nb.y);
    gradient.addColorStop(0, `rgba(255,255,255,${0.34 + (index % 3) * 0.08})`);
    gradient.addColorStop(1, "rgba(145,255,210,0.22)");
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 0.9;
    ctx.beginPath();
    ctx.moveTo(na.x, na.y);
    ctx.lineTo(nb.x, nb.y);
    ctx.stroke();
  });

  ctx.font = '11px "Segoe UI", "Noto Sans KR", sans-serif';
  ctx.textBaseline = "middle";

  nodes.forEach((node, index) => {
    const isSelected = index === selectedNodeIndex;
    const pulse = 0.72 + Math.sin(node.energy) * 0.28;
    ctx.shadowBlur = isSelected ? 30 : 18;
    ctx.shadowColor = isSelected ? "rgba(188,255,240,0.85)" : "rgba(148,255,207,0.5)";
    ctx.fillStyle = `rgba(248,252,255,${node.alpha})`;
    ctx.beginPath();
    ctx.arc(node.x, node.y, node.size + pulse * 0.8 + (isSelected ? 3.6 : 0), 0, Math.PI * 2);
    ctx.fill();

    ctx.shadowBlur = 0;
    ctx.fillStyle = `rgba(171,255,213,${clamp(node.alpha * 0.95, 0.48, 0.95)})`;
    ctx.font = isSelected
      ? '14px "Segoe UI", "Noto Sans KR", sans-serif'
      : '11px "Segoe UI", "Noto Sans KR", sans-serif';
    if (node.showLabel || node.alpha > 0.92) {
      ctx.fillText(node.label, node.x + 8, node.y - 10);
    }
  });

  ctx.restore();
}

function drawHands() {
  trackedHands.forEach((hand) => {
    const halo = ctx.createRadialGradient(hand.x, hand.y, 12, hand.x, hand.y, hand.radius);
    halo.addColorStop(0, `rgba(255,255,255,${hand.pinch ? 0.24 : 0.17})`);
    halo.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(hand.x, hand.y, hand.radius, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = `rgba(255,255,255,${hand.pinch ? 0.84 : 0.44})`;
    ctx.lineWidth = hand.pinch ? 1.7 : 1;
    ctx.beginPath();
    ctx.arc(hand.x, hand.y, hand.pinch ? 22 : 18, 0, Math.PI * 2);
    ctx.stroke();

    if (typeof hand.pinchDistance === "number") {
      ctx.font = '11px "Segoe UI", sans-serif';
      ctx.fillStyle = "rgba(189, 249, 255, 0.96)";
      ctx.fillText(`zoom ${Math.round(gestureScaleBoost * 100)}%`, hand.x + 18, hand.y - 18);
    }
  });
}

function drawMiniTopology() {
  const baseX = W - 190;
  const baseY = 188;
  const miniNodes = [[0, 0], [30, -18], [58, 2], [18, 32], [55, 40], [88, 16], [90, 52], [26, 68], [68, 76]];
  const miniEdges = [[0, 1], [0, 3], [1, 2], [1, 4], [2, 5], [3, 4], [3, 7], [4, 5], [4, 8], [5, 6], [7, 8], [6, 8]];

  ctx.save();
  ctx.translate(baseX, baseY);
  ctx.strokeStyle = "rgba(255,255,255,0.64)";
  ctx.fillStyle = "rgba(255,255,255,0.92)";

  miniEdges.forEach(([a, b]) => {
    ctx.beginPath();
    ctx.moveTo(miniNodes[a][0], miniNodes[a][1]);
    ctx.lineTo(miniNodes[b][0], miniNodes[b][1]);
    ctx.stroke();
  });

  miniNodes.forEach(([x, y]) => {
    ctx.beginPath();
    ctx.arc(x, y, 2.2, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.font = '10px "Segoe UI", sans-serif';
  ctx.fillStyle = "rgba(255,255,255,0.55)";
  ctx.fillText("distributed", 0, 102);
  ctx.fillText("notes connected by edges", 0, 116);
  ctx.fillText("gesture-reactive field", 0, 130);
  ctx.restore();
}

function drawScanlines() {
  ctx.save();
  ctx.strokeStyle = "rgba(255,255,255,0.03)";
  ctx.lineWidth = 1;
  for (let y = 0; y < H; y += 4) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
  }
  ctx.restore();
}

function drawDetailPanel() {
  if (expandedDetailIndex === -1) return;
  const label = clusterLabels[expandedDetailIndex];
  const panel = detailPanels[label.text];
  if (!panel) return;

  const width = Math.min(500, W * 0.42);
  const height = 210;
  const x = W - width - 36;
  const y = H - height - 36;

  ctx.save();
  ctx.fillStyle = "rgba(6, 27, 34, 0.82)";
  ctx.strokeStyle = "rgba(122, 243, 255, 0.42)";
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  ctx.roundRect(x, y, width, height, 18);
  ctx.fill();
  ctx.stroke();

  ctx.strokeStyle = "rgba(122, 243, 255, 0.24)";
  ctx.beginPath();
  ctx.moveTo(x + 22, y + 58);
  ctx.lineTo(x + width - 22, y + 58);
  ctx.stroke();

  ctx.fillStyle = "rgba(216, 252, 255, 0.98)";
  ctx.font = '28px "Segoe UI", "Noto Sans KR", sans-serif';
  ctx.fillText(panel.title, x + 22, y + 34);

  ctx.fillStyle = "rgba(156, 240, 255, 0.84)";
  ctx.font = '14px "Segoe UI", "Noto Sans KR", sans-serif';
  ctx.fillText(panel.subtitle, x + 22, y + 52);

  ctx.fillStyle = "rgba(198, 248, 255, 0.92)";
  ctx.font = '16px "Segoe UI", "Noto Sans KR", sans-serif';
  panel.lines.forEach((line, index) => {
    ctx.fillText(line, x + 24, y + 92 + index * 34);
  });

  ctx.fillStyle = "rgba(150, 242, 255, 0.72)";
  ctx.font = '13px "Segoe UI", "Noto Sans KR", sans-serif';
  ctx.fillText("양손 벌리기로 이 노드의 상세 정보를 열었습니다.", x + 24, y + height - 20);
  ctx.restore();
}

function draw() {
  requestAnimationFrame(draw);
  drawBackground();
  stepGraph();
  drawParticles();
  drawClusterLabels();
  drawHandSkeletons();
  drawHands();
  drawFrameMarks();
  drawScanlines();
}

function setupHands() {
  const hands = new Hands({
    locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`
  });

  hands.setOptions({
    maxNumHands: 2,
    modelComplexity: 1,
    minDetectionConfidence: 0.74,
    minTrackingConfidence: 0.74
  });

  hands.onResults((results) => {
    const now = performance.now();

    const handsArr = (results.multiHandLandmarks || [])
      .filter((handLm, index) => isLikelyHand(handLm, results.multiHandedness?.[index]));

    if (!handsArr.length) {
      prevPalm = null;
      if (now - lastSeenAt > handMarkerHoldMs) {
        trackedHands.length = 0;
      }
      if (now - lastSeenAt > 1600) {
        setStatus("손을 화면에 보여주면 그래프가 반응합니다.");
      }
      return;
    }

    trackedHands.length = 0;
    lastSeenAt = now;
    const lm = handsArr[0];
    const palm = lm[0];

    const primaryPinchDistance = pinchAmount(lm);
    gestureScaleBoost = clamp(0.75 + ((primaryPinchDistance - 0.02) / 0.22) * 1.55, 0.72, 2.4);

    handsArr.forEach((handLm) => {
      trackedHands.push(toTrackedHand(handLm));
    });

    updateLabelInteraction(trackedHands[0]);

    if (prevPalm) {
      const dx = palm.x - prevPalm.x;
      const dy = palm.y - prevPalm.y;

      if (now < gestureLockUntil) {
        prevPalm = { x: palm.x, y: palm.y };
        setStatus("제스처 안정화 중...");
        return;
      }

      if (now - lastSwipe > 900) {
        if (dx > 0.11) {
          jarvis.moveMonitor("right");
          setStatus("오른손 스와이프: 다음 모니터로 이동");
          lastSwipe = now;
        } else if (dx < -0.11) {
          jarvis.moveMonitor("left");
          setStatus("왼손 스와이프: 이전 모니터로 이동");
          lastSwipe = now;
        }
      }

      if (isPinch(lm) && now - lastDrag > 25) {
        if (Number.isFinite(dx) && Number.isFinite(dy)) {
          jarvis.nudge({ x: -dx * 2600, y: dy * 1800 });
        }
        setStatus("집는 동작으로 창 드래그 중");
        lastDrag = now;
      }
    }

    if (handsArr.length === 2) {
      const p1 = handsArr[0][8];
      const p2 = handsArr[1][8];
      const twoHandDist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
      const detailTargetIndex = selectedLabelIndex !== -1
        ? selectedLabelIndex
        : (now - lastSelectedAt < 1800 ? lastSelectedLabelIndex : -1);

      if (twoHandDist > 0.28 && ((detailTargetIndex !== -1 && now - lastDetailExpand > 1100) || (detailTargetIndex === -1 && now - lastMaximize > 2200))) {
        if (detailTargetIndex !== -1) {
          selectedLabelIndex = detailTargetIndex;
          setStatus(`${clusterLabels[detailTargetIndex].text} 노드 선택됨`);
          lastDetailExpand = now;
        } else {
          jarvis.maximize();
          setStatus("양손 벌리기: 창 최대화");
          lastMaximize = now;
        }
      }
    } else if (!isPinch(lm)) {
      setStatus(`엄지-검지 거리로 확대/축소: ${Math.round(gestureScaleBoost * 100)}%`);
    }

    prevPalm = { x: palm.x, y: palm.y };
  });

  const camera = new Camera(video, {
    onFrame: async () => {
      await hands.send({ image: video });
    },
    width: 960,
    height: 540
  });

  camera.start()
    .then(() => setStatus("카메라 준비 완료"))
    .catch(() => setStatus("카메라 권한을 허용해 주세요."));
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
    voiceState.textContent = "음성 ON / 대기 중";
    setStatus("음성 인식이 활성화되었습니다.");
  };

  recognition.onend = () => {
    voiceOn = false;
    voiceState.textContent = "음성 OFF";
  };

  recognition.onerror = (event) => {
    setStatus(`음성 인식 오류: ${event.error}`);
  };

  recognition.onresult = (event) => {
    const last = event.results[event.results.length - 1];
    const text = last[0].transcript.trim().toLowerCase();
    setStatus(`음성: ${text}`);

    if (text.includes("오른쪽") || text.includes("다음")) jarvis.moveMonitor("right");
    if (text.includes("왼쪽") || text.includes("이전")) jarvis.moveMonitor("left");
    if (text.includes("최대화") || text.includes("크게")) jarvis.maximize();
    if (text.includes("최소화") || text.includes("작게")) jarvis.minimize();
    if (text.includes("복원") || text.includes("되돌려")) jarvis.restore();
    if (text.includes("항상 위") || text.includes("고정")) jarvis.toggleAlwaysOnTop();
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
  if (e.key === "ArrowRight") jarvis.moveMonitor("right");
  if (e.key === "ArrowLeft") jarvis.moveMonitor("left");
  if (e.key === "ArrowUp") jarvis.maximize();
  if (e.key === "ArrowDown") jarvis.minimize();
  if (e.key.toLowerCase() === "t") jarvis.toggleAlwaysOnTop();
  if (e.key === "Escape") {
    expandedDetailIndex = -1;
    setStatus("선택 상태 초기화");
  }
});

draw();
setupHands();
setupVoice();

window.addEventListener("load", () => {
  setTimeout(() => {
    speakWelcomeGreeting();
  }, 700);
});
