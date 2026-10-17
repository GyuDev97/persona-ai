from datetime import timedelta

from sqlalchemy import select

from .activity import Activity
from .db import Database
from .llm import LLMError, LLMGateway
from .models import Memory, utcnow
from .textutil import similarity

KINDS = ("preference", "interest", "routine", "fact", "goal")
DUPLICATE_THRESHOLD = 0.7

EXTRACT_SYSTEM = """당신은 사용자 장기기억 추출기입니다. 아래 대화에서 사용자에 대해 오래 유효한 정보만 뽑습니다.
- 대상: 취향(preference), 관심사/취미(interest), 생활 루틴(routine), 개인 사실(fact), 목표(goal)
- 일시적 요청, 인사, 잡담, 비서(AI) 자신에 대한 내용은 제외합니다. 사용자가 직접 말한 것만 추출하고 추측하지 않습니다.
- content는 "사용자는 ..." 형태의 짧은 한국어 문장 하나로 씁니다.
- importance는 1~10 정수입니다(오래 반복해서 도움이 될수록 높음).
JSON만 출력: {"memories":[{"kind":"...","content":"...","importance":5}]}  추출할 것이 없으면 {"memories":[]}"""


class MemoryManager:
    def __init__(self, db: Database, llm: LLMGateway, activity: Activity, top_k: int):
        self.db = db
        self.llm = llm
        self.activity = activity
        self.top_k = top_k

    def add(self, kind: str, content: str, importance: int = 5, source: str = "chat") -> tuple[Memory, bool]:
        """기억을 저장한다. 거의 같은 기억이 있으면 기존 것을 강화한다. (memory, 새로 생성 여부)를 반환."""
        content = content.strip()
        if kind not in KINDS:
            kind = "fact"
        importance = max(1, min(10, int(importance)))
        with self.db.session() as s:
            for m in s.scalars(select(Memory).where(Memory.kind == kind)):
                if similarity(m.content, content) >= DUPLICATE_THRESHOLD:
                    m.last_seen_at = utcnow()
                    m.importance = max(m.importance, importance)
                    return m, False
            m = Memory(kind=kind, content=content, importance=importance, source=source)
            s.add(m)
            s.flush()
            return m, True

    def all(self) -> list[Memory]:
        with self.db.session() as s:
            return list(s.scalars(select(Memory).order_by(Memory.importance.desc(), Memory.id.desc())))

    def delete(self, memory_id: int) -> bool:
        with self.db.session() as s:
            m = s.get(Memory, memory_id)
            if m is None:
                return False
            s.delete(m)
            return True

    def retrieve(self, query: str, k: int | None = None) -> list[Memory]:
        """bigram 관련도 + 중요도 + 최신성으로 순위를 매긴다. MVP에서는 임베딩을 쓰지 않는다."""
        k = k or self.top_k
        now = utcnow()
        with self.db.session() as s:
            mems = list(s.scalars(select(Memory)))
            scored = []
            for m in mems:
                age_days = (now - m.last_seen_at).total_seconds() / 86400
                recency = max(0.0, 1 - age_days / 90)
                scored.append((3 * similarity(query, m.content) + m.importance / 10 + 0.3 * recency, m))
            top = [m for _, m in sorted(scored, key=lambda x: x[0], reverse=True)[:k]]
            for m in top:
                m.use_count += 1
                m.last_used_at = now
            return top

    def top(self, k: int = 10) -> list[Memory]:
        with self.db.session() as s:
            return list(s.scalars(select(Memory).order_by(Memory.importance.desc(), Memory.last_seen_at.desc()).limit(k)))

    async def extract_and_store(self, user_text: str, assistant_text: str) -> list[Memory]:
        """대화 한 번에서 오래 유효한 사실을 학습한다. 새로 생성된 기억만 반환."""
        if len(user_text.strip()) < 6:
            return []
        try:
            data, _ = await self.llm.json(
                "memory_extract",
                [
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {"role": "user", "content": f"사용자: {user_text}\n비서: {assistant_text}"},
                ],
                max_tokens=600,
            )
        except LLMError as e:
            self.activity.record("gyuvis", "memory.extract_failed", level="warn", error=str(e))
            return []
        created = []
        for item in data.get("memories", [])[:5]:
            try:
                content = str(item["content"]).strip()
                if not content:
                    continue
                m, is_new = self.add(str(item.get("kind", "fact")), content, int(item.get("importance", 5)))
            except (KeyError, TypeError, ValueError):
                continue
            if is_new:
                created.append(m)
                self.activity.record("gyuvis", "memory.created", id=m.id, kind=m.kind, content=m.content)
        return created
