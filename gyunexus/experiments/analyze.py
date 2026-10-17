"""실험 결과 집계. results/ 를 읽어 analysis.md, summary.json, review_blind.md, review_key.json 을 만든다. LLM 호출 없음."""

from __future__ import annotations

import json
import math
import pathlib
import random
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from topics import TOPICS  # noqa: E402
from run_experiment import CRITERIA, present  # noqa: E402

RES = HERE / "results"
TOPIC = {t["id"]: t for t in TOPICS}
TIE = 0.25


def load(pattern):
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RES.glob(pattern))]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else float("nan")


def overall(scores: dict) -> float:
    return mean([scores[c] for c in CRITERIA])


def sign_test_p(wins, losses):
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2**n)


def bootstrap_ci(diffs, n=10000, seed=0):
    rng = random.Random(seed)
    ms = sorted(mean([rng.choice(diffs) for _ in diffs]) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def scores_from(pattern: str) -> dict:
    out = {}
    for c in load(pattern):
        per: dict[str, list] = {}
        for o in c["orders"]:
            for m, v in (o.get("result") or {}).items():
                per.setdefault(m, []).append(v["scores"])
        for m, lst in per.items():
            out[(c["topic"], m)] = {cr: mean([s[cr] for s in lst]) for cr in CRITERIA}
    return out


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def f(x, d=2):
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def main():
    raw = {(r["topic"], r["method"]): r for r in load("raw/*.json")}
    meter = json.loads((RES / "meter.json").read_text(encoding="utf-8"))
    md: list[str] = ["# 분석 결과 (자동 생성)\n"]
    summary: dict = {}

    # ---- 실행 현황
    ran = sorted({t for t, _ in raw})
    md.append("## 1. 실행 현황\n")
    rows = []
    for m in ["A", "B", "C", "A0"]:
        cells = [r for (t, mm), r in raw.items() if mm == m]
        rows.append([m, len(cells), sum(1 for r in cells if r["ok"]), sum(1 for r in cells if not r["ok"])])
    md.append(table(["방식", "실행", "성공", "실패/미완료"], rows))
    md.append(f"\n실행한 주제 {len(ran)}개/{len(TOPICS)}개: {', '.join(ran)}")
    not_run = [t["id"] for t in TOPICS if t["id"] not in ran]
    md.append(f"미실행 주제: {', '.join(not_run) or '없음'}\n")
    failed = [(t, m, r["error"]) for (t, m), r in raw.items() if not r["ok"]]
    for t, m, e in failed:
        md.append(f"- 실패 기록 {t}/{m}: {e}")

    # ---- 비용·지연
    md.append("\n## 2. 비용·토큰·호출·지연 (생성 단계, 방식별 평균/총합)\n")
    rows = []
    gen_total = 0.0
    for m in ["A", "A0", "B", "C"]:
        cells = [r for (t, mm), r in raw.items() if mm == m]
        if not cells:
            continue
        u = [r["usage"] for r in cells]
        total = sum(x["cost_usd"] for x in u)
        gen_total += total
        rows.append([m, len(cells), f(mean([x["calls"] for x in u]), 1), f(mean([x["prompt_tokens"] + x["completion_tokens"] for x in u]), 0),
                     f(mean([x["cost_usd"] for x in u]), 5), f(total, 4), f(mean([r["secs"] for r in cells]), 1)])
    md.append(table(["방식", "n", "호출/건", "토큰/건", "비용/건($)", "총비용($)", "지연/건(초)"], rows))
    judge_cost = sum(c["cost"] for c in meter["calls"] if c["label"].startswith("judge"))
    bundle_cost = sum(c["cost"] for c in meter["calls"] if c["label"].endswith(":bundle"))
    md.append(f"\n생성 합계 ${gen_total:.4f}, 평가·검토 단계 ${judge_cost:.4f}, 전체 실제 지출 ${meter['spent']:.4f} (상한 $0.50). 번들 조회 비용 ${bundle_cost:.4f}\n")
    summary["cost"] = {"generation": gen_total, "judging": judge_cost, "total": meter["spent"]}

    # ---- 평가 점수
    comps = {c["topic"]: c for c in load("judge/*__compare.json")}
    scores: dict[tuple[str, str], dict] = {}  # (topic, method) -> {criterion: mean over valid orders}, plus per-order list
    pos_scores = {"first": [], "last": []}
    order_pairs = []
    for tid, c in comps.items():
        per_method: dict[str, list[dict]] = {}
        for oi, o in enumerate(c["orders"]):
            for pos, m in enumerate(o.get("order", [])):
                if m in o.get("result", {}):
                    s = o["result"][m]["scores"]
                    per_method.setdefault(m, []).append(s)
                    (pos_scores["first"] if pos == 0 else pos_scores["last"] if pos == len(o["order"]) - 1 else []).append(overall(s))
        for m, lst in per_method.items():
            scores[(tid, m)] = {cr: mean([s[cr] for s in lst]) for cr in CRITERIA}
            scores[(tid, m)]["_n"] = len(lst)
            if len(lst) == 2:
                order_pairs.append((overall(lst[0]), overall(lst[1])))
    md.append("## 3. LLM 평가 점수 (gpt-4.1-mini, 블라인드·순서 2회 평균, 종합=6기준 평균)\n")
    methods = [m for m in ["A", "B", "C", "A0"] if any(k[1] == m for k in scores)]
    rows = []
    for m in methods:
        cells = [v for (t, mm), v in scores.items() if mm == m]
        rows.append([m, len(cells)] + [f(mean([v[cr] for v in cells])) for cr in CRITERIA] + [f(mean([overall(v) for v in cells]))])
    md.append(table(["방식", "n"] + CRITERIA + ["종합"], rows))
    summary["judge_means"] = {m: mean([overall(v) for (t, mm), v in scores.items() if mm == m]) for m in methods}

    md.append("\n### 주제별 종합 점수\n")
    rows = []
    for tid in [t["id"] for t in TOPICS if t["id"] in comps]:
        rows.append([tid, TOPIC[tid]["area"]] + [f(overall(scores[(tid, m)])) if (tid, m) in scores else "-" for m in ["A", "B", "C", "A0"]])
    md.append(table(["주제", "영역", "A", "B", "C", "A0(증거없음)"], rows))

    md.append("\n### 영역/유형별 종합 평균\n")
    groups = {}
    for t in TOPICS:
        groups.setdefault(t["area"], []).append(t["id"])
    groups["사실 주제(은하수·기상)"] = [t["id"] for t in TOPICS if t["bundle"]]
    groups["소프트웨어·AI 주제(전체-은하수)"] = [t["id"] for t in TOPICS if not t["bundle"]]
    rows = []
    for g, ids in groups.items():
        cell = []
        for m in ["A", "B", "C"]:
            xs = [overall(scores[(t, m)]) for t in ids if (t, m) in scores]
            cell.append(f"{f(mean(xs))} (n={len(xs)})")
        rows.append([g] + cell)
    md.append(table(["그룹", "A", "B", "C"], rows))

    md.append("\n### A 대비 차이 (주제 단위 종합 점수 차)\n")
    rows = []
    summary["vs_A"] = {}
    for m in ["B", "C"]:
        ds = [overall(scores[(t, m)]) - overall(scores[(t, "A")]) for t in comps if (t, m) in scores and (t, "A") in scores]
        if not ds:
            continue
        w, l_, ti = sum(1 for d in ds if d >= TIE), sum(1 for d in ds if d <= -TIE), sum(1 for d in ds if abs(d) < TIE)
        lo, hi = bootstrap_ci(ds)
        rows.append([f"{m} - A", len(ds), f(mean(ds), 3), f"[{lo:.2f}, {hi:.2f}]", f"{w}/{ti}/{l_}", f(sign_test_p(w, l_), 3)])
        summary["vs_A"][m] = {"n": len(ds), "mean_diff": mean(ds), "ci": [lo, hi], "win_tie_loss": [w, ti, l_]}
    md.append(table(["비교", "n", "평균차", "부트스트랩 95% CI", "승/무/패(|차|<0.25=무)", "부호검정 p"], rows))
    ds = [overall(scores[(t, "C")]) - overall(scores[(t, "B")]) for t in comps if (t, "C") in scores and (t, "B") in scores]
    if ds:
        w, l_ = sum(1 for d in ds if d >= TIE), sum(1 for d in ds if d <= -TIE)
        lo, hi = bootstrap_ci(ds)
        md.append(f"\nC - B: n={len(ds)}, 평균차 {mean(ds):.3f}, CI [{lo:.2f}, {hi:.2f}], 승/무/패 {w}/{len(ds) - w - l_}/{l_}, 부호검정 p={sign_test_p(w, l_):.3f}")
    skyA = [t for t in comps if TOPIC[t]["bundle"] and (t, "A0") in scores and (t, "A") in scores]
    if skyA:
        md.append(f"\nA(증거 있음) - A0(증거 없음), 사실 주제 n={len(skyA)}: 종합 평균차 {mean([overall(scores[(t, 'A')]) - overall(scores[(t, 'A0')]) for t in skyA]):.2f}; "
                  f"accuracy 평균차 {mean([scores[(t, 'A')]['accuracy'] - scores[(t, 'A0')]['accuracy'] for t in skyA]):.2f}")

    md.append("\n### 평가자 편향 점검\n")
    if pos_scores["first"]:
        md.append(f"- 위치: 첫 번째 제시 평균 {mean(pos_scores['first']):.2f} vs 마지막 제시 평균 {mean(pos_scores['last']):.2f}")
    if order_pairs:
        xs, ys = [a for a, _ in order_pairs], [b for _, b in order_pairs]
        mx, my = mean(xs), mean(ys)
        cov = sum((x - mx) * (y - my) for x, y in order_pairs)
        den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
        md.append(f"- 두 제시 순서 간 같은 후보 점수 상관(Pearson) {cov / den if den else float('nan'):.2f} (n={len(order_pairs)}), 평균 절대 차이 {mean([abs(a - b) for a, b in order_pairs]):.2f}")
    cells = [(raw[k]["metrics"]["chars"], overall(v)) for k, v in scores.items() if k in raw and raw[k].get("metrics")]
    if len(cells) > 3:
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        mx, my = mean(xs), mean(ys)
        cov = sum((x - mx) * (y - my) for x, y in cells)
        den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
        md.append(f"- 길이-점수 상관(Pearson, 글자 수 vs 종합) {cov / den if den else float('nan'):.2f} (n={len(cells)}). 방식별 평균 글자 수: "
                  + ", ".join(f"{m} {mean([r['metrics']['chars'] for (t, mm), r in raw.items() if mm == m and r.get('metrics')]):.0f}" for m in ['A', 'B', 'C']))

    # ---- 사후 점검: 다른 평가자 / 증거 합집합
    md.append("\n### 사후 점검 (프로토콜 이후 추가): 평가자 모델·증거 제공 방식 민감도\n")
    variants = {"gpt-4.1-mini(원 평가, 2순서)": scores}
    for name, pat in [("gpt-4o-mini(2순서)", "judge/*__compare_gpt-4o-mini.json"), ("gpt-4.1(1순서, 더 강한 평가자)", "judge/*__compare_gpt-4.1.json")]:
        variants[name] = scores_from(pat)
    rows = []
    summary["judge_variants"] = {}
    for name, sc in variants.items():
        if not sc:
            continue
        cells = {m: [overall(v) for (t, mm), v in sc.items() if mm == m] for m in ["A", "B", "C"]}
        dB = [overall(sc[(t, "B")]) - overall(sc[(t, "A")]) for t in TOPIC if (t, "B") in sc and (t, "A") in sc]
        dC = [overall(sc[(t, "C")]) - overall(sc[(t, "A")]) for t in TOPIC if (t, "C") in sc and (t, "A") in sc]
        wB = (sum(1 for d in dB if d >= TIE), sum(1 for d in dB if abs(d) < TIE), sum(1 for d in dB if d <= -TIE))
        wC = (sum(1 for d in dC if d >= TIE), sum(1 for d in dC if abs(d) < TIE), sum(1 for d in dC if d <= -TIE))
        rows.append([name, len(dB)] + [f(mean(cells[m])) for m in ["A", "B", "C"]] + [f(mean(dB), 2), "/".join(map(str, wB)), f(mean(dC), 2), "/".join(map(str, wC))])
        summary["judge_variants"][name] = {m: mean(cells[m]) for m in cells}
    md.append(table(["평가자", "n", "A", "B", "C", "B-A", "승/무/패", "C-A", "승/무/패"], rows))
    union = scores_from("judge/*__compare_union.json")
    if union:
        rows = []
        for tid in [t for t in TOPIC if TOPIC[t]["bundle"]]:
            rows.append([tid] + [f"{f(overall(scores[(tid, m)]))} → {f(overall(union[(tid, m)]))}" if (tid, m) in union and (tid, m) in scores else "-" for m in ["A", "B", "C"]]
                        + [f"{f(scores[(tid, m)]['accuracy'])} → {f(union[(tid, m)]['accuracy'])}" if (tid, m) in union and (tid, m) in scores else "-" for m in ["B"]])
        md.append("\n사실 주제에서 평가자에게 B/C가 직접 조회한 증거까지 제공했을 때(종합 원점수 → 보정 점수, 마지막 열은 B의 accuracy):\n")
        md.append(table(["주제", "A", "B", "C", "B accuracy"], rows))
        summary["union"] = {m: mean([overall(union[(t, m)]) for t in TOPIC if (t, m) in union]) for m in ["A", "B", "C"]}

    # ---- 사후 절제 실험: Critic 제거(D)
    abl = scores_from("judge/*__compare_ablation.json")
    if abl:
        ids = sorted({t for t, m in abl if m == "D"})
        rows = []
        for tid in ids:
            rows.append([tid] + [f(overall(abl[(tid, m)])) if (tid, m) in abl else "-" for m in ["A", "B", "D"]])
        md.append("\n### 사후 절제 실험: D = B에서 Critic만 제거 (A, B, D를 같은 평가에서 블라인드 비교)\n")
        md.append(table(["주제", "A", "B(Critic 있음)", "D(Critic 없음)"], rows))
        dB = [overall(abl[(t, "B")]) - overall(abl[(t, "D")]) for t in ids]
        dA = [overall(abl[(t, "A")]) - overall(abl[(t, "D")]) for t in ids]
        lo, hi = bootstrap_ci(dB)
        md.append(f"\n평균: A {mean([overall(abl[(t, 'A')]) for t in ids]):.2f} / B {mean([overall(abl[(t, 'B')]) for t in ids]):.2f} / D {mean([overall(abl[(t, 'D')]) for t in ids]):.2f}. "
                  f"B - D(= Critic이 포함된 구조의 효과) 평균 {mean(dB):.2f}, CI [{lo:.2f}, {hi:.2f}], 승/무/패 "
                  f"{sum(1 for d in dB if d >= TIE)}/{sum(1 for d in dB if abs(d) < TIE)}/{sum(1 for d in dB if d <= -TIE)}; A - D 평균 {mean(dA):.2f}")
        dcells = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((RES / "raw").glob("*__D.json"))]
        if dcells:
            md.append(f"D 비용/건 ${mean([c['usage']['cost_usd'] for c in dcells]):.5f}, 지연 {mean([c['secs'] for c in dcells]):.1f}초, 호출 {mean([c['usage']['calls'] for c in dcells]):.1f}회 "
                      f"(같은 8주제 B: ${mean([raw[(t, 'B')]['usage']['cost_usd'] for t in ids]):.5f}, {mean([raw[(t, 'B')]['secs'] for t in ids]):.1f}초)")

    # ---- 객관 지표
    md.append("\n## 4. 코드 기반 객관 지표 (평가자와 독립)\n")
    rows = []
    for m in ["A", "A0", "B", "C"]:
        ms = [r["metrics"] for (t, mm), r in raw.items() if mm == m and r.get("metrics")]
        fact = [r["metrics"] for (t, mm), r in raw.items() if mm == m and r.get("metrics") and TOPIC[t]["bundle"]]
        if not ms:
            continue
        rows.append([m, len(ms), f(mean([x["n_ideas"] for x in ms]), 1), f(mean([x["with_next_steps"] for x in ms])), f(mean([x["with_risks"] for x in ms])),
                     f(mean([x["chars"] for x in ms]), 0), f(mean([x["unsupported_pct"] for x in fact]), 2) if fact else "-",
                     f(mean([x["warning_coverage"] for x in fact if x["warning_coverage"] is not None])) if fact else "-"])
    md.append(table(["방식", "n", "아이디어 수", "다음단계 비율", "위험 비율", "글자 수", "근거없는 % 수치(사실주제)", "경고 반영률(사실주제)"], rows))
    md.append("\n(아이디어 수는 폐기된 아이디어를 제외한 최종 결과 기준)\n")

    # ---- B/C 토론 통계
    md.append("\n## 5. 멀티 에이전트 토론 동작 (B/C)\n")
    rows = []
    for m in ["B", "C"]:
        cs = [r for (t, mm), r in raw.items() if mm == m and r["raw"] and r["raw"].get("debate")]
        stops = {}
        for r in cs:
            stops[r["raw"]["debate"]["stop_reason"]] = stops.get(r["raw"]["debate"]["stop_reason"], 0) + 1
        statuses = {}
        n_ideas_all = 0
        for r in cs:
            for i in r["raw"]["ideas"]:
                statuses[i["status"]] = statuses.get(i["status"], 0) + 1
                n_ideas_all += 1
        res_status = {}
        for r in cs:
            s = (r["raw"].get("result") or {}).get("status")
            res_status[s] = res_status.get(s, 0) + 1
        ev = {"retry": 0, "reject": 0, "preserved": 0, "consensus_ignored": 0, "sem_rej": 0}
        for r in cs:
            e = r["raw"]["events"]
            ev["retry"] += e.get("critic.retry", 0); ev["reject"] += e.get("critic.rejected", 0); ev["preserved"] += e.get("preserved.dropped", 0)
            ev["consensus_ignored"] += e.get("consensus.ignored", 0); ev["sem_rej"] += e.get("review.rebuttal_rejected", 0)
        rows.append([m, len(cs), json.dumps(stops, ensure_ascii=False), f(mean([r["raw"]["debate"]["rounds"] for r in cs]), 1),
                     json.dumps(statuses, ensure_ascii=False), json.dumps(res_status, ensure_ascii=False), json.dumps(ev, ensure_ascii=False),
                     f(mean([len(r["raw"]["evidence"]) for r in cs]), 1)])
    md.append(table(["방식", "토론 수", "종료 원인", "평균 완료 라운드", "아이디어 상태(전체)", "결과 상태", "이벤트 합계", "증거 수/건"], rows))
    rs = {}
    for (t, m), r in raw.items():
        if m == "C" and r["raw"]:
            for k, v in (r["raw"].get("review_stats") or {}).items():
                rs[k] = rs.get(k, 0) + v
    md.append(f"\nC의 LLM 검토 개입 합계: {json.dumps(rs, ensure_ascii=False)}\n")
    summary["review_stats"] = rs

    # ---- 토론 전후
    md.append("\n## 6. 토론 전후: Idea 1라운드 발언(초안) vs 최종 결과 (블라인드 평가)\n")
    pairs = [p for p in load("judge/*__draft.json") if p.get("draft_scores") and p.get("final_scores")]
    rows = []
    for m in ["B", "C"]:
        ps = [p for p in pairs if p["method"] == m and _valid(p)]
        if not ps:
            continue
        d_o, f_o = [overall(p["draft_scores"]) for p in ps], [overall(p["final_scores"]) for p in ps]
        verdicts = {}
        for p in ps:
            verdicts[p.get("verdict")] = verdicts.get(p.get("verdict"), 0) + 1
        rows.append([m, len(ps), f(mean(d_o)), f(mean(f_o)), f(mean(f_o) - mean(d_o), 2)]
                    + [f(mean([p["final_scores"][c] - p["draft_scores"][c] for p in ps]), 2) for c in CRITERIA] + [json.dumps(verdicts, ensure_ascii=False)])
    md.append(table(["방식", "n", "초안", "최종", "차이"] + [f"Δ{c}" for c in CRITERIA] + ["평가자 verdict"], rows))
    weak = [(p["topic"], p["method"], p["weakened_points"]) for p in pairs if p.get("weakened_points")]
    md.append("\n약화·손실로 지적된 사례(평가자 판단):")
    for t, m, w in weak[:12]:
        md.append(f"- {t}/{m}: {'; '.join(map(str, w))[:220]}")

    # ---- 탐지기
    md.append("\n## 7. 의미 충돌 탐지: 규칙 vs LLM 검토 (평가자 gpt-4.1-mini 판정 대비)\n")
    det = [d for d in load("judge/*__detector.json") if "statements" in d]
    tot = {"rule": [0, 0, 0, 0], "llm": [0, 0, 0, 0]}
    review_lines = []
    for d in det:
        n = len(d["statements"])
        gold = set(d["gold"])
        for name in ("rule", "llm"):
            pred = set(d[name])
            tp, fp, fn = len(pred & gold), len(pred - gold), len(gold - pred)
            tn = n - tp - fp - fn
            for i, v in enumerate((tp, fp, fn, tn)):
                tot[name][i] += v
        for i, s in enumerate(d["statements"], 1):
            if i in d["rule"] or i in d["llm"] or i in d["gold"]:
                review_lines.append(f"- [{d['topic']}/{d['method']}#{i}] 규칙={'Y' if i in d['rule'] else 'n'} LLM={'Y' if i in d['llm'] else 'n'} 평가자={'Y' if i in d['gold'] else 'n'} :: {s[:200]}")
    rows = []
    for name, (tp, fp, fn, tn) in tot.items():
        rows.append([name, tp, fp, fn, tn, f(tp / (tp + fp) if tp + fp else float("nan")), f(tp / (tp + fn) if tp + fn else float("nan"))])
    md.append(table(["탐지기", "TP", "FP", "FN", "TN", "정밀도", "재현율"], rows))
    md.append(f"\n(서술 {sum(len(d['statements']) for d in det)}건, 평가자가 '실제 모순'으로 본 것 {sum(len(d['gold']) for d in det)}건. 평가자 판정은 정답이 아니라 근사 기준이며 아래 목록으로 사람이 확인할 수 있다.)\n")
    md.append("\n<details><summary>탐지 대상 전체(규칙/LLM/평가자 중 하나라도 표시한 서술)</summary>\n\n" + "\n".join(review_lines) + "\n\n</details>\n")
    summary["detector"] = tot

    # ---- 블라인드 검토 파일
    key, review = {}, ["# 블라인드 검토용 (방식 라벨 제거). 매핑은 review_key.json\n"]
    for tid, c in comps.items():
        order = c["orders"][0].get("order", [])
        labels = {m: "XYZW"[i] for i, m in enumerate(order)}
        key[tid] = labels
        review.append(f"\n## {tid}: {TOPIC[tid]['title']}\n")
        for m in order:
            if (tid, m) in raw and raw[(tid, m)]["norm"]:
                review.append(f"### 후보 {labels[m]}\n```\n{present(raw[(tid, m)]['norm'])}\n```\n")
    (RES / "review_blind.md").write_text("\n".join(review), encoding="utf-8")
    (RES / "review_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")

    (RES / "analysis.md").write_text("\n".join(md), encoding="utf-8")
    (RES / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("\n".join(md))


def _valid(p):
    return all(isinstance(p[k].get(c), (int, float)) for k in ("draft_scores", "final_scores") for c in CRITERIA)


if __name__ == "__main__":
    main()
