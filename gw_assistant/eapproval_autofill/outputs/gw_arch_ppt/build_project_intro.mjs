import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "file:///C:/Users/bglee/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const W = 1280;
const H = 720;
const OUT_DIR = path.resolve("D:/github/persona-ai/apps/gw_assistant/eapproval_autofill/outputs/gw_arch_ppt");
const SCRATCH_DIR = path.resolve("D:/github/persona-ai/apps/gw_assistant/eapproval_autofill/outputs/gw_arch_ppt/tmp_intro");
const PREVIEW_DIR = path.join(SCRATCH_DIR, "preview");

const COLORS = {
  bg: "#F6FAFD",
  paper: "#FFFFFF",
  ink: "#1A2940",
  muted: "#62748B",
  blue: "#0EA5E9",
  blueSoft: "#EAF7FF",
  green: "#12B981",
  greenSoft: "#EBFBF5",
  amber: "#F59E0B",
  amberSoft: "#FFF4DB",
  border: "#D7E3EE",
  slate: "#EEF4F9",
  coral: "#F97316",
};

const TITLE = "Poppins";
const BODY = "Lato";
const MONO = "Aptos Mono";

async function ensureDirs() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.mkdir(PREVIEW_DIR, { recursive: true });
}

function line(fill = COLORS.border, width = 1) {
  return { style: "solid", fill, width };
}

function addShape(slide, geometry, x, y, w, h, fill, stroke = COLORS.border, strokeWidth = 1) {
  return slide.shapes.add({
    geometry,
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: line(stroke, strokeWidth),
  });
}

function addText(slide, text, x, y, w, h, options = {}) {
  const {
    size = 20,
    color = COLORS.ink,
    bold = false,
    face = BODY,
    align = "left",
    valign = "top",
  } = options;
  const shape = addShape(slide, "rect", x, y, w, h, "#FFFFFF00", "#FFFFFF00", 0);
  shape.text = text;
  shape.text.fontSize = size;
  shape.text.color = color;
  shape.text.bold = bold;
  shape.text.typeface = face;
  shape.text.alignment = align;
  shape.text.verticalAlignment = valign;
  shape.text.insets = { left: 0, right: 0, top: 0, bottom: 0 };
  shape.text.autoFit = "shrinkText";
  return shape;
}

function header(slide, label, page, total) {
  addText(slide, label.toUpperCase(), 64, 28, 360, 20, {
    size: 12,
    color: COLORS.blue,
    bold: true,
    face: MONO,
  });
  addText(slide, `${String(page).padStart(2, "0")} / ${String(total).padStart(2, "0")}`, 1110, 28, 110, 20, {
    size: 12,
    color: COLORS.blue,
    bold: true,
    face: MONO,
    align: "right",
  });
  addShape(slide, "rect", 64, 56, 1152, 2, COLORS.blue, COLORS.blue, 0);
}

function metricCard(slide, value, label, x, y, w) {
  addShape(slide, "roundRect", x, y, w, 96, COLORS.paper, COLORS.border, 1);
  addText(slide, value, x + 18, y + 16, w - 36, 34, {
    size: 28,
    color: COLORS.ink,
    bold: true,
    face: TITLE,
  });
  addText(slide, label, x + 18, y + 56, w - 36, 22, {
    size: 14,
    color: COLORS.muted,
  });
}

function bulletCard(slide, title, bullets, x, y, w, h, tone = "blue") {
  const fill = tone === "green" ? COLORS.greenSoft : tone === "amber" ? COLORS.amberSoft : COLORS.blueSoft;
  const accent = tone === "green" ? COLORS.green : tone === "amber" ? COLORS.amber : COLORS.blue;
  addShape(slide, "roundRect", x, y, w, h, fill, accent, 1.4);
  addText(slide, title, x + 20, y + 18, w - 40, 26, {
    size: 20,
    color: COLORS.ink,
    bold: true,
    face: TITLE,
  });
  bullets.forEach((item, idx) => {
    addShape(slide, "ellipse", x + 22, y + 58 + idx * 34, 10, 10, accent, accent, 0);
    addText(slide, item, x + 42, y + 52 + idx * 34, w - 62, 28, {
      size: 15,
      color: COLORS.ink,
    });
  });
}

function flowBox(slide, title, body, x, y, w, h, tone = "blue") {
  const fill = tone === "green" ? COLORS.greenSoft : tone === "amber" ? COLORS.amberSoft : COLORS.blueSoft;
  const accent = tone === "green" ? COLORS.green : tone === "amber" ? COLORS.amber : COLORS.blue;
  addShape(slide, "roundRect", x, y, w, h, fill, accent, 1.4);
  addText(slide, title, x + 18, y + 16, w - 36, 30, {
    size: 18,
    color: COLORS.ink,
    bold: true,
    face: TITLE,
  });
  addText(slide, body, x + 18, y + 52, w - 36, h - 66, {
    size: 14,
    color: COLORS.ink,
  });
}

function arrow(slide, x, y, w = 52, h = 30, fill = COLORS.blue) {
  addShape(slide, "rightArrow", x, y, w, h, fill, fill, 0);
}

function tableRow(slide, cells, y, isHeader = false) {
  const widths = [150, 255, 255, 160, 170, 162];
  let x = 64;
  cells.forEach((cell, idx) => {
    const width = widths[idx];
    addShape(slide, "rect", x, y, width, 50, isHeader ? "#E7EEF5" : COLORS.paper, COLORS.border, 1);
    addText(slide, cell, x + 10, y + 12, width - 20, 24, {
      size: isHeader ? 15 : 14,
      color: COLORS.ink,
      bold: isHeader,
      align: idx >= 3 ? "center" : "left",
      valign: "middle",
    });
    x += width;
  });
}

async function saveBlobToFile(blob, filePath) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  await fs.writeFile(filePath, bytes);
}

async function build() {
  await ensureDirs();

  const presentation = Presentation.create({ slideSize: { width: W, height: H } });
  presentation.theme.colorScheme = {
    name: "GW Intro",
    themeColors: {
      accent1: COLORS.blue,
      accent2: COLORS.green,
      accent3: COLORS.amber,
      bg1: COLORS.bg,
      tx1: COLORS.ink,
      tx2: COLORS.muted,
    },
  };

  const total = 5;

  {
    const slide = presentation.slides.add();
    slide.background.fill = COLORS.bg;
    header(slide, "Project Intro", 1, total);

    addShape(slide, "roundRect", 64, 92, 602, 534, COLORS.paper, COLORS.border, 1);
    addShape(slide, "roundRect", 700, 92, 516, 250, COLORS.blueSoft, COLORS.blue, 1.4);
    addShape(slide, "roundRect", 700, 362, 248, 264, COLORS.greenSoft, COLORS.green, 1.4);
    addShape(slide, "roundRect", 968, 362, 248, 264, COLORS.amberSoft, COLORS.amber, 1.4);

    addText(slide, "GW 전자결재 AI 자동입력", 96, 132, 520, 54, {
      size: 34,
      bold: true,
      face: TITLE,
    });
    addText(slide, "프로젝트 소개", 96, 188, 220, 40, {
      size: 26,
      color: COLORS.blue,
      bold: true,
      face: TITLE,
    });
    addText(slide, "첨부파일을 기반으로 전자결재 양식 초안을 자동으로 생성하고, 사용자가 검토 후 수정하여 반영할 수 있도록 돕는 그룹웨어 지원 프로젝트입니다.", 96, 274, 510, 92, {
      size: 19,
      color: COLORS.muted,
    });

    metricCard(slide, "자동입력", "요청부서 / 납품요청일 / 품목행", 96, 412, 220);
    metricCard(slide, "검토형", "모달 팝업에서 수정 후 반영", 334, 412, 220);
    metricCard(slide, "확장형", "스프링 그룹웨어와 API 연동", 96, 522, 458);

    addText(slide, "프로젝트 한 줄 소개", 728, 120, 180, 24, {
      size: 15,
      color: COLORS.blue,
      bold: true,
      face: MONO,
    });
    addText(slide, "문서를 읽고 전자결재 양식에 필요한 항목을 자동으로 채우는 업무형 AI Assist 프로젝트", 728, 160, 430, 110, {
      size: 23,
      bold: true,
      face: TITLE,
    });

    addText(slide, "현재 구현", 724, 388, 120, 24, {
      size: 15,
      color: COLORS.green,
      bold: true,
      face: MONO,
    });
    addText(slide, "엑셀 / PDF 업로드\n자동입력 모달\n주요 필드 추출", 724, 430, 190, 130, {
      size: 20,
      bold: true,
      face: TITLE,
    });

    addText(slide, "지향점", 992, 388, 120, 24, {
      size: 15,
      color: COLORS.amber,
      bold: true,
      face: MONO,
    });
    addText(slide, "결재 작성 시간 단축\n오입력 감소\n그룹웨어 내 자연스러운 UX", 992, 430, 180, 136, {
      size: 20,
      bold: true,
      face: TITLE,
    });
  }

  {
    const slide = presentation.slides.add();
    slide.background.fill = COLORS.bg;
    header(slide, "Overview", 2, total);
    addText(slide, "왜 이 프로젝트가 필요한가", 64, 90, 440, 48, {
      size: 31,
      bold: true,
      face: TITLE,
    });
    addText(slide, "전자결재 작성은 반복 입력이 많고, 첨부문서가 있어도 결재양식에 다시 옮겨 적는 작업이 필요합니다.", 64, 148, 720, 40, {
      size: 17,
      color: COLORS.muted,
    });

    bulletCard(slide, "현업 불편", [
      "첨부 문서를 보고 필드를 다시 수기 입력",
      "품목, 금액, 납기 등을 반복 입력",
      "승인자 입장에서 핵심 내용을 한 번에 보기 어려움",
    ], 64, 224, 356, 256, "blue");

    bulletCard(slide, "프로젝트 목표", [
      "첨부파일 기반 자동입력",
      "사용자 검토 후 반영",
      "기존 그룹웨어 흐름과 자연스럽게 연결",
    ], 462, 224, 356, 256, "green");

    bulletCard(slide, "핵심 가치", [
      "작은 성공 화면부터 빠르게 검증",
      "자주 쓰는 양식 기준으로 정확도 확보",
      "향후 LLM과 OCR로 단계적 확장",
    ], 860, 224, 356, 256, "amber");

    addShape(slide, "roundRect", 64, 514, 1152, 120, COLORS.paper, COLORS.border, 1);
    addText(slide, "프로젝트 포지션", 92, 540, 120, 22, {
      size: 14,
      color: COLORS.blue,
      bold: true,
      face: MONO,
    });
    addText(slide, "이 프로젝트는 'AI가 다 해주는 결재'가 아니라, 실제 결재양식 작성의 반복작업을 줄이는 업무 지원 도구로 출발합니다.", 92, 572, 1070, 38, {
      size: 23,
      bold: true,
      face: TITLE,
    });
  }

  {
    const slide = presentation.slides.add();
    slide.background.fill = COLORS.bg;
    header(slide, "Features", 3, total);
    addText(slide, "현재 구현된 핵심 기능", 64, 90, 400, 48, {
      size: 31,
      bold: true,
      face: TITLE,
    });
    addText(slide, "데모 기준으로는 업로드, 필드 추출, 검토형 팝업 UX까지 연결되어 있습니다.", 64, 148, 660, 36, {
      size: 17,
      color: COLORS.muted,
    });

    flowBox(slide, "1. 첨부 업로드", "엑셀과 PDF 파일을 업로드하거나 텍스트를 직접 입력", 64, 238, 220, 150, "blue");
    arrow(slide, 296, 296);
    flowBox(slide, "2. 문서 파싱", "시트 텍스트 또는 PDF 텍스트를 읽어 공통 문자열로 변환", 360, 238, 220, 150, "green");
    arrow(slide, 592, 296);
    flowBox(slide, "3. 필드 추출", "요청부서, 납품요청일, 품목/규격/수량/단가/금액을 탐지", 656, 238, 220, 150, "amber");
    arrow(slide, 888, 296);
    flowBox(slide, "4. 검토형 모달", "제목과 품목행을 포함한 팝업에서 직접 수정 가능", 952, 238, 264, 150, "blue");

    addShape(slide, "roundRect", 64, 432, 530, 190, COLORS.paper, COLORS.border, 1);
    addText(slide, "자동입력 대상 항목", 92, 454, 180, 24, {
      size: 15,
      color: COLORS.green,
      bold: true,
      face: MONO,
    });
    addText(slide, "제목\n요청부서\n납품요청일\n품목 / 규격 / 수량 / 단가 / 금액", 92, 492, 220, 106, {
      size: 24,
      bold: true,
      face: TITLE,
    });

    addShape(slide, "roundRect", 628, 432, 588, 190, COLORS.paper, COLORS.border, 1);
    addText(slide, "화면 특징", 656, 454, 140, 24, {
      size: 15,
      color: COLORS.amber,
      bold: true,
      face: MONO,
    });
    addText(slide, "메인 화면에는 추출 근거와 경고를 우선 표시하고,\n자동입력 실행 후에는 그룹웨어 양식 느낌의 팝업을 열어 사용자가 바로 수정할 수 있도록 구성했습니다.", 656, 492, 510, 88, {
      size: 22,
      bold: true,
      face: TITLE,
    });
  }

  {
    const slide = presentation.slides.add();
    slide.background.fill = COLORS.bg;
    header(slide, "Architecture", 4, total);
    addText(slide, "프로젝트 기술 구성", 64, 90, 360, 48, {
      size: 31,
      bold: true,
      face: TITLE,
    });
    addText(slide, "현재 데모는 프런트, 추출 API, 문서 파서로 구성되며, 향후 스프링 그룹웨어와 API 방식으로 연결하는 구조를 염두에 두고 있습니다.", 64, 148, 880, 40, {
      size: 17,
      color: COLORS.muted,
    });

    addShape(slide, "roundRect", 64, 232, 320, 350, COLORS.paper, COLORS.blue, 1.5);
    addShape(slide, "roundRect", 480, 232, 320, 350, COLORS.paper, COLORS.green, 1.5);
    addShape(slide, "roundRect", 896, 232, 320, 350, COLORS.paper, COLORS.amber, 1.5);

    addText(slide, "프런트 UI", 92, 260, 200, 28, {
      size: 24,
      bold: true,
      face: TITLE,
    });
    addText(slide, "첨부 업로드 화면\n자동입력 버튼\n근거/경고 표시\n검토형 팝업", 92, 320, 220, 170, {
      size: 21,
      color: COLORS.ink,
    });

    addText(slide, "FastAPI 추출 서비스", 508, 260, 220, 28, {
      size: 24,
      bold: true,
      face: TITLE,
    });
    addText(slide, "파일 업로드 엔드포인트\n텍스트 추출\n필드 매핑\nJSON 응답 반환", 508, 320, 220, 180, {
      size: 21,
      color: COLORS.ink,
    });

    addText(slide, "문서 이해 레이어", 924, 260, 220, 28, {
      size: 24,
      bold: true,
      face: TITLE,
    });
    addText(slide, "XLSX 시트 읽기\nPDF 텍스트 추출\n라벨 규칙 매칭\n품목행 정규식 파싱", 924, 320, 220, 180, {
      size: 21,
      color: COLORS.ink,
    });

    arrow(slide, 392, 392, 64, 36, COLORS.blue);
    arrow(slide, 808, 392, 64, 36, COLORS.green);

    addShape(slide, "roundRect", 64, 610, 1152, 52, COLORS.blueSoft, COLORS.blue, 1);
    addText(slide, "향후 실제 그룹웨어 장착 시에는 Spring이 메인 시스템 역할을 하고, 현재 추출 서비스는 별도 API 엔진으로 연결하는 방향이 적합합니다.", 90, 625, 1100, 24, {
      size: 20,
      bold: true,
      face: TITLE,
      align: "center",
      valign: "middle",
    });
  }

  {
    const slide = presentation.slides.add();
    slide.background.fill = COLORS.bg;
    header(slide, "Roadmap", 5, total);
    addText(slide, "확장 방향과 기대효과", 64, 90, 420, 48, {
      size: 31,
      bold: true,
      face: TITLE,
    });
    addText(slide, "이 프로젝트는 작은 자동입력 성공 화면에서 시작해, 실제 그룹웨어 내 업무 도우미로 확장될 수 있습니다.", 64, 148, 740, 40, {
      size: 17,
      color: COLORS.muted,
    });

    tableRow(slide, ["구분", "현재 상태", "다음 단계", "대상", "검증 포인트", "효과"], 222, true);
    tableRow(slide, ["기능", "자동입력 데모 완성", "실양식 반영", "구매품의", "사용자 수정 빈도", "작성시간 단축"], 272, false);
    tableRow(slide, ["문서", "엑셀 / 텍스트 PDF", "스캔 PDF OCR", "견적서/발주서", "추출 성공률", "지원범위 확대"], 322, false);
    tableRow(slide, ["연동", "FastAPI 단독 동작", "Spring API 연결", "그룹웨어 서버", "DTO 매핑 성공", "실서비스 적용"], 372, false);

    bulletCard(slide, "프로젝트 강점", [
      "실제 양식 기준으로 바로 시연 가능",
      "사용자 검토형이라 운영 리스크가 낮음",
      "스프링 그룹웨어와 분리 가능한 구조",
    ], 64, 470, 360, 160, "green");

    bulletCard(slide, "다음 단계", [
      "실제 샘플 문서 기준 패턴 보강",
      "OCR 추가로 스캔 PDF 대응",
      "Spring WebClient 연동 구현",
    ], 460, 470, 360, 160, "blue");

    bulletCard(slide, "기대효과", [
      "결재 작성 생산성 향상",
      "반복 입력과 오입력 감소",
      "프로젝트형 AI에서 업무형 AI로 확장",
    ], 856, 470, 360, 160, "amber");
  }

  for (let i = 0; i < presentation.slides.items.length; i += 1) {
    const preview = await presentation.export({ slide: presentation.slides.items[i], format: "png", scale: 1 });
    await saveBlobToFile(preview, path.join(PREVIEW_DIR, `slide-${String(i + 1).padStart(2, "0")}.png`));
  }

  const pptx = await PresentationFile.exportPptx(presentation);
  const outputPath = path.join(OUT_DIR, "output.pptx");
  await pptx.save(outputPath);
  console.log(outputPath);
}

await build();
