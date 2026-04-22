from pathlib import Path

from ..domain.schemas import FinanceBriefingResponse


APP_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = APP_DIR / "data"
MONTHLY_WORKBOOK_NAME = "26년5월.xlsx"
TARGET_WORKBOOK_NAME = "3억_현금목표_시뮬레이션.xlsx"


def build_finance_briefing() -> FinanceBriefingResponse:
    monthly_path = DATA_DIR / MONTHLY_WORKBOOK_NAME
    target_path = DATA_DIR / TARGET_WORKBOOK_NAME

    if not _has_openpyxl():
        return FinanceBriefingResponse(
            source_month=monthly_path.stem,
            target_sheet=target_path.stem,
            headline="재정 브리핑을 쓰려면 `openpyxl` 패키지가 필요합니다.",
            bullets=["현재 venv에서 `pip install -r requirements.txt`만 한 번 실행하면 엑셀 브리핑을 바로 붙일 수 있습니다."],
            monthly_income=0,
            monthly_savings=0,
            fixed_cost=0,
            check_card_spend=0,
            credit_card_spend=0,
            monthly_spend_total=0,
            remaining_cash=0,
            savings_rate=0.0,
            spending_rate=0.0,
            credit_limit=0,
            credit_over_limit=0,
            current_cash_goal_year=None,
            current_cash_goal_amount=None,
        )

    if not monthly_path.exists() or not target_path.exists():
        return FinanceBriefingResponse(
            source_month=monthly_path.stem,
            target_sheet=target_path.stem,
            headline="재정 브리핑 파일이 아직 준비되지 않았습니다.",
            bullets=["`data` 폴더에 월별 지출 파일과 3억 목표 시뮬레이션 파일이 있으면 바로 요약할 수 있습니다."],
            monthly_income=0,
            monthly_savings=0,
            fixed_cost=0,
            check_card_spend=0,
            credit_card_spend=0,
            monthly_spend_total=0,
            remaining_cash=0,
            savings_rate=0.0,
            spending_rate=0.0,
            credit_limit=0,
            credit_over_limit=0,
            current_cash_goal_year=None,
            current_cash_goal_amount=None,
        )

    monthly = _read_monthly_finance(monthly_path)
    target = _read_cash_target(target_path)

    savings_rate = round(monthly["monthly_savings"] / monthly["monthly_income"], 4) if monthly["monthly_income"] else 0.0
    spending_rate = round(monthly["monthly_spend_total"] / monthly["monthly_income"], 4) if monthly["monthly_income"] else 0.0
    credit_over_limit = max(monthly["credit_card_spend"] - monthly["credit_limit"], 0)

    bullets = [
        f"이번 달 실지출은 {monthly['monthly_spend_total']:,}원이고, 월급 대비 {spending_rate * 100:.1f}% 수준입니다.",
        f"저축은 {monthly['monthly_savings']:,}원으로 잡혀 있어서 현재 저축 비중은 {savings_rate * 100:.1f}%입니다.",
    ]

    if monthly["remaining_cash"] >= 0:
        bullets.append(f"이번 달 남는 돈은 {monthly['remaining_cash']:,}원 정도로 보입니다. 아주 타이트하지만 아직 적자는 아닙니다.")
    else:
        bullets.append(f"현재 계획상 {-monthly['remaining_cash']:,}원 정도 부족합니다. 이번 달 소비를 조금만 줄여도 균형 맞추기 쉬워 보입니다.")

    if credit_over_limit > 0:
        bullets.append(f"신용카드는 한도 기준보다 {credit_over_limit:,}원 초과 상태라 이 부분은 가장 먼저 낮추는 게 좋겠습니다.")
    else:
        bullets.append("신용카드는 현재 설정한 최대치 안쪽이라, 큰 위험 신호까지는 아닙니다.")

    if target["goal_year"] is not None and target["goal_amount"] is not None:
        bullets.append(
            f"현재 시뮬레이션 기준으로 순수 현금 {target['goal_amount'] // 10000}억 목표는 {target['goal_year']}년에 처음 도달합니다."
        )
        headline = (
            f"이번 달은 {monthly['monthly_spend_total']:,}원 정도 쓰는 흐름이고, "
            f"지금 계획을 유지하면 {target['goal_year']}년에 현금 목표선에 닿는 그림입니다."
        )
    else:
        headline = (
            f"이번 달 소비는 {monthly['monthly_spend_total']:,}원 수준으로 보이고, "
            "현금 목표선은 아직 현재 시뮬레이션 범위 안에서 도달 시점이 잡히지 않았습니다."
        )

    return FinanceBriefingResponse(
        source_month=monthly["source_month"],
        target_sheet=target["target_sheet"],
        headline=headline,
        bullets=bullets,
        monthly_income=monthly["monthly_income"],
        monthly_savings=monthly["monthly_savings"],
        fixed_cost=monthly["fixed_cost"],
        check_card_spend=monthly["check_card_spend"],
        credit_card_spend=monthly["credit_card_spend"],
        monthly_spend_total=monthly["monthly_spend_total"],
        remaining_cash=monthly["remaining_cash"],
        savings_rate=savings_rate,
        spending_rate=spending_rate,
        credit_limit=monthly["credit_limit"],
        credit_over_limit=credit_over_limit,
        current_cash_goal_year=target["goal_year"],
        current_cash_goal_amount=target["goal_amount"],
    )


def _read_monthly_finance(path: Path) -> dict[str, int | str]:
    load_workbook = _load_workbook()
    workbook = load_workbook(path, data_only=True)
    sheet = workbook["분산"]

    monthly_income = _to_int(sheet["A3"].value)
    monthly_savings = _to_int(sheet["B3"].value)
    fixed_cost = _to_int(sheet["C3"].value)
    check_card_spend = _to_int(sheet["D3"].value)
    credit_card_spend = _to_int(sheet["E3"].value)
    remaining_cash = _to_int(sheet["F3"].value)
    credit_limit = _to_int(sheet["G3"].value)

    return {
        "source_month": path.stem,
        "monthly_income": monthly_income,
        "monthly_savings": monthly_savings,
        "fixed_cost": fixed_cost,
        "check_card_spend": check_card_spend,
        "credit_card_spend": credit_card_spend,
        "monthly_spend_total": fixed_cost + check_card_spend + credit_card_spend,
        "remaining_cash": remaining_cash,
        "credit_limit": credit_limit,
    }


def _read_cash_target(path: Path) -> dict[str, int | str | None]:
    load_workbook = _load_workbook()
    workbook = load_workbook(path, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]

    goal_year = None
    goal_amount = None
    target_amount = 300000000

    for row in range(4, sheet.max_row + 1):
        year = sheet[f"A{row}"].value
        year_end_balance_manwon = sheet[f"D{row}"].value
        if year is None or year_end_balance_manwon is None:
            continue
        year_end_balance_won = _to_int(year_end_balance_manwon) * 10000
        if year_end_balance_won >= target_amount:
            goal_year = int(year)
            goal_amount = target_amount
            break

    return {
        "target_sheet": sheet.title,
        "goal_year": goal_year,
        "goal_amount": goal_amount,
    }


def _to_int(value) -> int:
    if value is None or value == "":
        return 0
    return int(round(float(value)))


def _has_openpyxl() -> bool:
    try:
        from openpyxl import load_workbook as _  # noqa: F401
        return True
    except ImportError:
        return False


def _load_workbook():
    from openpyxl import load_workbook

    return load_workbook
