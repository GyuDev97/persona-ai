"""런타임에 바뀌는 값(토글, 타임스탬프)을 저장하는 작은 key/value 저장소."""

from typing import Any

from sqlalchemy.orm import Session

from .models import Setting


def get_value(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Setting, key)
    return default if row is None else row.value


def set_value(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
