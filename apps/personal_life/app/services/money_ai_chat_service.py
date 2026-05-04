from __future__ import annotations

import json
from typing import Any

from ..config import get_settings
from .money_core_service import (
    build_money_core_summary,
    list_assets_history,
    list_auto_transfer,
    list_card_usage,
    list_expenses,
    list_installments,
)

AI_TIMEOUT_SECONDS = 25


def ask_money_core_ai(question: str, month: str | None = None) -> dict[str, Any]:
    clean_question = " ".join(str(question or "").split())
    if not clean_question:
        raise ValueError("질문을 입력해주세요.")
    if len(clean_question) > 1000:
        raise ValueError("질문은 1000자 이하로 입력해주세요.")

    settings = get_settings()
    if not settings.has_openai:
        raise ValueError("OPENAI_API_KEY 설정이 필요합니다.")

    context = _build_money_context(month)
    answer = _call_openai(settings.openai_api_key, settings.openai_model, clean_question, context)
    return {
        "answer": answer,
        "model": settings.openai_model,
        "month": context["summary"].get("month"),
        "data_scope": "Money Core 요약 데이터",
    }


def _build_money_context(month: str | None) -> dict[str, Any]:
    summary = build_money_core_summary(month)
    target_month = summary.get("month")
    expenses = list_expenses(str(target_month))
    cards = list_card_usage()
    installments = list_installments(str(target_month))
    assets = list_assets_history()
    auto_transfers = list_auto_transfer()

    return {
        "summary": _pick(
            summary,
            (
                "month",
                "salary",
                "saving",
                "fixed_expense",
                "check_card",
                "credit_card",
                "remaining_cash",
                "monthly_spend_total",
                "expense_category_total",
                "installment_total",
                "saving_rate",
                "card_usage_rate",
                "asset_change",
            ),
        ),
        "expenses_by_category": expenses[:20],
        "card_usage": [
            _pick(item, ("card_name", "total_amount", "payment_amount", "billing_cycle_start", "billing_cycle_end"))
            for item in cards[:20]
        ],
        "installments": [
            _pick(item, ("title", "total_month", "current_month", "remaining_month", "monthly_amount", "card_name"))
            for item in installments[:20]
        ],
        "assets_history": [_pick(item, ("month", "total_asset")) for item in assets[-24:]],
        "auto_transfers": [_pick(item, ("title", "amount", "transfer_date")) for item in auto_transfers[:30]],
    }


def _call_openai(api_key: str | None, model: str, question: str, context: dict[str, Any]) -> str:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise ValueError("openai 패키지가 설치되어 있지 않습니다.") from error

    prompt = (
        "You are GYUVIS Money Core, a Korean personal finance analysis assistant.\n"
        "Answer in Korean with a warm but practical tone.\n"
        "Use only the provided Money Core data. If data is missing, say what is missing.\n"
        "This is not certified financial, investment, tax, or loan advice. Do not guarantee outcomes.\n"
        "Never tell the user to make a payment, transfer, investment, or loan action automatically.\n"
        "When the user asks about buying a house, estimate with clear assumptions: current assets, monthly surplus, "
        "saving pace, target price, and possible down payment gap. Keep it realistic and easy to understand.\n"
        "Prefer concrete numbers, short sections, and 3-5 bullet points.\n"
    )
    user_payload = {
        "question": question,
        "money_core_data": context,
    }
    client = OpenAI(api_key=api_key, timeout=AI_TIMEOUT_SECONDS)
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}]},
        ],
    )
    answer = (getattr(response, "output_text", "") or "").strip()
    if not answer:
        raise ValueError("Money Core AI 답변을 생성하지 못했습니다.")
    return answer


def _pick(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: source.get(key) for key in keys}
