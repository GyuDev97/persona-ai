import re


_SECRETS = re.compile(
    r"sk-[A-Za-z0-9_\-*.]{6,}|Bearer\s+[A-Za-z0-9\-._~+/]+=*|(?i:(?:api[_-]?key|token|secret|password)=)[^&\s\"']+"
)


def redact(value):
    """로그/추적 정보에 API 키·토큰이 섞이지 않도록 문자열을 마스킹한다(dict/list는 재귀)."""
    if isinstance(value, str):
        return _SECRETS.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def normalize(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower())


def _bigrams(text: str) -> set[str]:
    n = normalize(text)
    if len(n) < 2:
        return {n} if n else set()
    return {n[i : i + 2] for i in range(len(n) - 1)}


def similarity(a: str, b: str) -> float:
    """문자 bigram Dice 계수. 형태소 분석기 없이 한국어에도 동작한다."""
    sa, sb = _bigrams(a), _bigrams(b)
    if not sa or not sb:
        return 0.0
    return 2 * len(sa & sb) / (len(sa) + len(sb))
