from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..storage.database import execute, fetch_all, fetch_one


def current_month() -> str:
    return date.today().strftime("%Y-%m")


def build_money_core_summary(month: str | None = None) -> dict[str, Any]:
    target_month = month or current_month()
    income = _income_summary(target_month)
    expenses = list_expenses(target_month)
    cards = list_card_usage(target_month)
    installments = list_installments(target_month)
    assets = list_assets_history()
    auto_transfers = list_auto_transfer()

    salary = int(income.get("salary") or 0)
    fixed_expense = int(income.get("fixed_expense") or 0)
    check_card = int(income.get("check_card") or 0)
    credit_card = int(income.get("credit_card") or 0)
    saving = int(income.get("saving") or 0)
    card_limit = int(income.get("card_limit") or 0)
    calculated_remaining = salary - (fixed_expense + check_card + credit_card)
    card_usage_rate = round(credit_card / card_limit, 4) if card_limit else 0.0

    previous_month = _previous_month(target_month)
    previous_expense_total = sum(int(item.get("amount") or 0) for item in list_expenses(previous_month))
    current_expense_total = sum(int(item.get("amount") or 0) for item in expenses)
    expense_change_rate = _change_rate(current_expense_total, previous_expense_total)
    asset_change = _asset_change(assets)

    return {
        "month": target_month,
        "salary": salary,
        "saving": saving,
        "fixed_expense": fixed_expense,
        "check_card": check_card,
        "credit_card": credit_card,
        "remaining_cash": calculated_remaining,
        "stored_remaining_cash": int(income.get("remaining_cash") or 0),
        "card_limit": card_limit,
        "card_usage_rate": card_usage_rate,
        "monthly_spend_total": fixed_expense + check_card + credit_card,
        "expense_category_total": current_expense_total,
        "expense_change_rate": expense_change_rate,
        "cards": cards,
        "installments": installments,
        "assets": assets,
        "asset_change": asset_change,
        "auto_transfers": auto_transfers,
        "saving_rate": round(saving / salary, 4) if salary else 0.0,
        "tips": build_saving_tips(
            salary=salary,
            fixed_expense=fixed_expense,
            check_card=check_card,
            credit_card=credit_card,
            remaining_cash=calculated_remaining,
            card_usage_rate=card_usage_rate,
            expense_change_rate=expense_change_rate,
            expenses=expenses,
        ),
    }


def list_expenses(month: str | None = None) -> list[dict[str, Any]]:
    target_month = month or current_month()
    rows = fetch_all(
        """
        SELECT MAX(id) AS id, category, SUM(amount) AS amount
        FROM expenses
        WHERE month = ?
        GROUP BY category
        ORDER BY amount DESC, category ASC
        """,
        (target_month,),
    )
    previous = {
        row["category"]: int(row.get("amount") or 0)
        for row in fetch_all(
            """
            SELECT category, SUM(amount) AS amount
            FROM expenses
            WHERE month = ?
            GROUP BY category
            """,
            (_previous_month(target_month),),
        )
    }
    return [
        {
            "category": row["category"],
            "id": int(row.get("id") or 0),
            "amount": int(row.get("amount") or 0),
            "previous_amount": previous.get(row["category"], 0),
            "change_rate": _change_rate(int(row.get("amount") or 0), previous.get(row["category"], 0)),
        }
        for row in rows
    ]


def list_card_usage(month: str | None = None) -> list[dict[str, Any]]:
    target_month = month or current_month()
    rows = fetch_all(
        """
        SELECT *
        FROM card_usage
        WHERE billing_cycle_start IS NULL
           OR billing_cycle_end IS NULL
           OR substr(billing_cycle_start, 1, 7) <= ?
          AND substr(billing_cycle_end, 1, 7) >= ?
        ORDER BY total_amount DESC, id DESC
        """,
        (target_month, target_month),
    )
    return [
        {
            "id": int(row.get("id") or 0),
            "card_name": row.get("card_name") or "",
            "total_amount": int(row.get("total_amount") or 0),
            "payment_amount": int(row.get("payment_amount") or 0),
            "billing_cycle_start": _stringify(row.get("billing_cycle_start")),
            "billing_cycle_end": _stringify(row.get("billing_cycle_end")),
        }
        for row in rows
    ]


def list_installments(month: str | None = None) -> list[dict[str, Any]]:
    target_month = month or current_month()
    rows = fetch_all(
        """
        SELECT *
        FROM installments
        ORDER BY start_date ASC, id ASC
        """
    )
    return [_installment_payload(row, target_month) for row in rows]


def list_assets_history() -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT *
        FROM assets_history
        ORDER BY month ASC
        """
    )
    return [{"month": row["month"], "total_asset": int(row.get("total_asset") or 0)} for row in rows]


def list_auto_transfer() -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT *
        FROM auto_transfer
        ORDER BY transfer_date ASC, amount DESC, id ASC
        """
    )
    return [
        {
            "id": int(row.get("id") or 0),
            "title": row.get("title") or "",
            "amount": int(row.get("amount") or 0),
            "transfer_date": _stringify(row.get("transfer_date")),
        }
        for row in rows
    ]


def save_income_summary(payload: dict[str, Any]) -> dict[str, Any]:
    month = _normalize_month(payload.get("month"))
    salary = _to_int(payload.get("salary"))
    saving = _to_int(payload.get("saving"))
    fixed_expense = _to_int(payload.get("fixed_expense"))
    check_card = _to_int(payload.get("check_card"))
    credit_card = _to_int(payload.get("credit_card"))
    card_limit = _to_int(payload.get("card_limit"))
    remaining_cash = salary - (fixed_expense + check_card + credit_card)
    existing = fetch_one("SELECT id FROM income_summary WHERE month = ?", (month,))
    if existing:
        execute(
            """
            UPDATE income_summary
            SET salary = ?, saving = ?, fixed_expense = ?, check_card = ?, credit_card = ?,
                remaining_cash = ?, card_limit = ?, updated_at = CURRENT_TIMESTAMP
            WHERE month = ?
            """,
            (salary, saving, fixed_expense, check_card, credit_card, remaining_cash, card_limit, month),
        )
    else:
        execute(
            """
            INSERT INTO income_summary (
                month, salary, saving, fixed_expense, check_card, credit_card, remaining_cash, card_limit
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (month, salary, saving, fixed_expense, check_card, credit_card, remaining_cash, card_limit),
        )
    return build_money_core_summary(month)


def create_expense(payload: dict[str, Any]) -> dict[str, Any]:
    month = _normalize_month(payload.get("month"))
    category = _required_text(payload.get("category"), "category")
    amount = _to_int(payload.get("amount"))
    item_id = execute(
        "INSERT INTO expenses (month, category, amount) VALUES (?, ?, ?)",
        (month, category, amount),
    )
    return {"id": item_id, "month": month, "category": category, "amount": amount}


def update_expense(item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    month = _normalize_month(payload.get("month"))
    category = _required_text(payload.get("category"), "category")
    amount = _to_int(payload.get("amount"))
    _ensure_money_item("expenses", item_id)
    execute(
        "UPDATE expenses SET month = ?, category = ?, amount = ? WHERE id = ?",
        (month, category, amount, item_id),
    )
    return {"id": item_id, "month": month, "category": category, "amount": amount}


def create_card_usage(payload: dict[str, Any]) -> dict[str, Any]:
    card_name = _required_text(payload.get("card_name"), "card_name")
    item_id = execute(
        """
        INSERT INTO card_usage (card_name, total_amount, payment_amount, billing_cycle_start, billing_cycle_end)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            card_name,
            _to_int(payload.get("total_amount")),
            _to_int(payload.get("payment_amount")),
            _optional_text(payload.get("billing_cycle_start")),
            _optional_text(payload.get("billing_cycle_end")),
        ),
    )
    return {"id": item_id, "card_name": card_name}


def update_card_usage(item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    card_name = _required_text(payload.get("card_name"), "card_name")
    _ensure_money_item("card_usage", item_id)
    execute(
        """
        UPDATE card_usage
        SET card_name = ?, total_amount = ?, payment_amount = ?,
            billing_cycle_start = ?, billing_cycle_end = ?
        WHERE id = ?
        """,
        (
            card_name,
            _to_int(payload.get("total_amount")),
            _to_int(payload.get("payment_amount")),
            _optional_text(payload.get("billing_cycle_start")),
            _optional_text(payload.get("billing_cycle_end")),
            item_id,
        ),
    )
    return {"id": item_id, "card_name": card_name}


def create_installment(payload: dict[str, Any]) -> dict[str, Any]:
    title = _required_text(payload.get("title"), "title")
    item_id = execute(
        """
        INSERT INTO installments (title, total_month, current_month, monthly_amount, card_name, start_date)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            max(1, _to_int(payload.get("total_month"), 1)),
            max(1, _to_int(payload.get("current_month"), 1)),
            _to_int(payload.get("monthly_amount")),
            str(payload.get("card_name") or ""),
            _optional_text(payload.get("start_date")),
        ),
    )
    return {"id": item_id, "title": title}


def update_installment(item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    title = _required_text(payload.get("title"), "title")
    _ensure_money_item("installments", item_id)
    execute(
        """
        UPDATE installments
        SET title = ?, total_month = ?, current_month = ?, monthly_amount = ?,
            card_name = ?, start_date = ?
        WHERE id = ?
        """,
        (
            title,
            max(1, _to_int(payload.get("total_month"), 1)),
            max(1, _to_int(payload.get("current_month"), 1)),
            _to_int(payload.get("monthly_amount")),
            str(payload.get("card_name") or ""),
            _optional_text(payload.get("start_date")),
            item_id,
        ),
    )
    return {"id": item_id, "title": title}


def save_asset_history(payload: dict[str, Any]) -> dict[str, Any]:
    month = _normalize_month(payload.get("month"))
    total_asset = _to_int(payload.get("total_asset"))
    existing = fetch_one("SELECT id FROM assets_history WHERE month = ?", (month,))
    if existing:
        execute("UPDATE assets_history SET total_asset = ? WHERE month = ?", (total_asset, month))
    else:
        execute("INSERT INTO assets_history (month, total_asset) VALUES (?, ?)", (month, total_asset))
    return {"month": month, "total_asset": total_asset}


def create_auto_transfer(payload: dict[str, Any]) -> dict[str, Any]:
    title = _required_text(payload.get("title"), "title")
    amount = _to_int(payload.get("amount"))
    item_id = execute(
        "INSERT INTO auto_transfer (title, amount, transfer_date) VALUES (?, ?, ?)",
        (title, amount, _optional_text(payload.get("transfer_date"))),
    )
    return {"id": item_id, "title": title, "amount": amount}


def update_auto_transfer(item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    title = _required_text(payload.get("title"), "title")
    amount = _to_int(payload.get("amount"))
    _ensure_money_item("auto_transfer", item_id)
    execute(
        "UPDATE auto_transfer SET title = ?, amount = ?, transfer_date = ? WHERE id = ?",
        (title, amount, _optional_text(payload.get("transfer_date")), item_id),
    )
    return {"id": item_id, "title": title, "amount": amount}


def delete_money_core_item(table_name: str, item_id: int) -> dict[str, Any]:
    allowed = {"expenses", "card_usage", "installments", "auto_transfer"}
    if table_name not in allowed:
        raise ValueError("삭제할 수 없는 Money Core 항목입니다.")
    _ensure_money_item(table_name, item_id)
    execute(f"DELETE FROM {table_name} WHERE id = ?", (item_id,))
    return {"deleted": True, "table": table_name, "id": item_id}


def build_saving_tips(
    salary: int,
    fixed_expense: int,
    check_card: int,
    credit_card: int,
    remaining_cash: int,
    card_usage_rate: float,
    expense_change_rate: float,
    expenses: list[dict[str, Any]],
) -> list[str]:
    tips: list[str] = []
    if remaining_cash < 0:
        tips.append(f"이번 달 계획상 {-remaining_cash:,}원이 부족합니다. 체크카드나 신용카드 변동비부터 줄이는 편이 좋겠습니다.")
    elif salary:
        tips.append(f"이번 달 예상 잔액은 {remaining_cash:,}원입니다. 남은 현금 흐름은 월급 대비 {remaining_cash / salary * 100:.1f}%입니다.")
    if card_usage_rate >= 1:
        tips.append("신용카드 사용액이 설정 한도를 넘었습니다. 다음 결제 전 할부와 플랫폼 결제를 먼저 점검해보세요.")
    elif card_usage_rate >= 0.8:
        tips.append("신용카드 사용률이 80%를 넘었습니다. 남은 기간에는 체크카드보다 현금 흐름 기준으로 보는 편이 안전합니다.")
    if expense_change_rate > 0.1:
        tips.append(f"카테고리 소비 합계가 지난달보다 {expense_change_rate * 100:.1f}% 높습니다. 가장 큰 카테고리부터 확인해보세요.")
    if expenses:
        top = expenses[0]
        tips.append(f"현재 가장 큰 소비 카테고리는 {top['category']}이며 {top['amount']:,}원입니다.")
    if not tips:
        tips.append("아직 분석할 재정 데이터가 많지 않습니다. 월급, 카드, 카테고리 소비부터 입력하면 절약 팁이 정교해집니다.")
    return tips[:4]


def _income_summary(month: str) -> dict[str, Any]:
    return fetch_one("SELECT * FROM income_summary WHERE month = ?", (month,)) or {
        "month": month,
        "salary": 0,
        "saving": 0,
        "fixed_expense": 0,
        "check_card": 0,
        "credit_card": 0,
        "remaining_cash": 0,
        "card_limit": 0,
    }


def _installment_payload(row: dict[str, Any], month: str) -> dict[str, Any]:
    total_month = max(1, int(row.get("total_month") or 1))
    stored_current = max(1, int(row.get("current_month") or 1))
    elapsed = _month_diff(str(row.get("start_date") or ""), month)
    computed_current = min(total_month, max(stored_current, elapsed + 1 if elapsed >= 0 else stored_current))
    remaining_month = max(total_month - computed_current, 0)
    return {
        "id": int(row.get("id") or 0),
        "title": row.get("title") or "",
        "total_month": total_month,
        "current_month": computed_current,
        "stored_current_month": stored_current,
        "remaining_month": remaining_month,
        "monthly_amount": int(row.get("monthly_amount") or 0),
        "card_name": row.get("card_name") or "",
        "start_date": _stringify(row.get("start_date")),
        "progress_rate": round(computed_current / total_month, 4),
    }


def _asset_change(assets: list[dict[str, Any]]) -> dict[str, Any]:
    if len(assets) < 2:
        latest = assets[-1]["total_asset"] if assets else 0
        return {"amount": 0, "rate": 0.0, "latest_total_asset": latest}
    latest = assets[-1]["total_asset"]
    previous = assets[-2]["total_asset"]
    return {"amount": latest - previous, "rate": _change_rate(latest, previous), "latest_total_asset": latest}


def _previous_month(month: str) -> str:
    year, raw_month = [int(part) for part in month.split("-", 1)]
    raw_month -= 1
    if raw_month == 0:
        year -= 1
        raw_month = 12
    return f"{year:04d}-{raw_month:02d}"


def _month_diff(start_date: str, month: str) -> int:
    try:
        start = datetime.strptime(start_date[:7], "%Y-%m")
        target = datetime.strptime(month, "%Y-%m")
    except ValueError:
        return -1
    return (target.year - start.year) * 12 + (target.month - start.month)


def _change_rate(current: int, previous: int) -> float:
    if previous == 0:
        return 0.0
    return round((current - previous) / previous, 4)


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _normalize_month(value: Any) -> str:
    text = str(value or current_month()).strip()
    try:
        datetime.strptime(text, "%Y-%m")
    except ValueError as error:
        raise ValueError("month는 YYYY-MM 형식이어야 합니다.") from error
    return text


def _to_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(str(value).replace(",", "").strip())


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 값이 필요합니다.")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _ensure_money_item(table_name: str, item_id: int) -> None:
    row = fetch_one(f"SELECT id FROM {table_name} WHERE id = ?", (item_id,))
    if row is None:
        raise ValueError("Money Core 항목을 찾을 수 없습니다.")
