from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...domain.schemas import AssetCreate, AssetResponse, AssetSummaryResponse, AssetUpdate, FinanceBriefingResponse
from ...services.asset_service import build_asset_summary, create_asset, list_assets, update_asset
from ...services.finance_service import build_finance_briefing
from ...services.money_ai_chat_service import ask_money_core_ai
from ...services.money_core_service import (
    build_money_core_summary,
    create_auto_transfer,
    create_card_usage,
    create_expense,
    create_installment,
    delete_money_core_item,
    list_assets_history,
    list_auto_transfer,
    list_card_usage,
    list_expenses,
    list_installments,
    save_asset_history,
    save_income_summary,
    update_auto_transfer,
    update_card_usage,
    update_expense,
    update_installment,
)


router = APIRouter()


class MoneyAiChatPayload(BaseModel):
    question: str
    month: str | None = None


@router.get("/finance/briefing", response_model=FinanceBriefingResponse)
def get_finance_briefing() -> FinanceBriefingResponse:
    return build_finance_briefing()


@router.get("/finance/summary")
def get_money_core_summary(month: str | None = None) -> dict:
    return build_money_core_summary(month)


@router.post("/finance/summary")
def post_money_core_summary(payload: dict) -> dict:
    try:
        return save_income_summary(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/finance/ai-chat")
def post_money_core_ai_chat(payload: MoneyAiChatPayload) -> dict:
    try:
        return ask_money_core_ai(payload.question, payload.month)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/finance/expenses")
def get_money_core_expenses(month: str | None = None) -> list[dict]:
    return list_expenses(month)


@router.post("/finance/expenses")
def post_money_core_expense(payload: dict) -> dict:
    try:
        return create_expense(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put("/finance/expenses/{item_id}")
def put_money_core_expense(item_id: int, payload: dict) -> dict:
    try:
        return update_expense(item_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/finance/expenses/{item_id}")
def delete_money_core_expense(item_id: int) -> dict:
    try:
        return delete_money_core_item("expenses", item_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/finance/card")
def get_money_core_card(month: str | None = None) -> list[dict]:
    return list_card_usage(month)


@router.post("/finance/card")
def post_money_core_card(payload: dict) -> dict:
    try:
        return create_card_usage(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put("/finance/card/{item_id}")
def put_money_core_card(item_id: int, payload: dict) -> dict:
    try:
        return update_card_usage(item_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/finance/card/{item_id}")
def delete_money_core_card(item_id: int) -> dict:
    try:
        return delete_money_core_item("card_usage", item_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/finance/installments")
def get_money_core_installments(month: str | None = None) -> list[dict]:
    return list_installments(month)


@router.post("/finance/installments")
def post_money_core_installment(payload: dict) -> dict:
    try:
        return create_installment(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put("/finance/installments/{item_id}")
def put_money_core_installment(item_id: int, payload: dict) -> dict:
    try:
        return update_installment(item_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/finance/installments/{item_id}")
def delete_money_core_installment(item_id: int) -> dict:
    try:
        return delete_money_core_item("installments", item_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/finance/assets")
def get_money_core_assets() -> list[dict]:
    return list_assets_history()


@router.post("/finance/assets")
def post_money_core_asset(payload: dict) -> dict:
    try:
        return save_asset_history(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/finance/auto-transfer")
def get_money_core_auto_transfer() -> list[dict]:
    return list_auto_transfer()


@router.post("/finance/auto-transfer")
def post_money_core_auto_transfer(payload: dict) -> dict:
    try:
        return create_auto_transfer(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put("/finance/auto-transfer/{item_id}")
def put_money_core_auto_transfer(item_id: int, payload: dict) -> dict:
    try:
        return update_auto_transfer(item_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/finance/auto-transfer/{item_id}")
def delete_money_core_auto_transfer(item_id: int) -> dict:
    try:
        return delete_money_core_item("auto_transfer", item_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/assets", response_model=AssetResponse)
def post_asset(payload: AssetCreate) -> AssetResponse:
    return create_asset(payload)


@router.get("/assets", response_model=list[AssetResponse])
def get_assets(limit: int = 100) -> list[AssetResponse]:
    return list_assets(limit=limit)


@router.get("/assets/summary", response_model=AssetSummaryResponse)
def get_asset_summary() -> AssetSummaryResponse:
    return build_asset_summary()


@router.put("/assets/{asset_id}", response_model=AssetResponse)
def put_asset(asset_id: int, payload: AssetUpdate) -> AssetResponse:
    asset = update_asset(asset_id, payload)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset
