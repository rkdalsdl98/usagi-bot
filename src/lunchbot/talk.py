"""우사기 1:1 대화에서 채팅 읽기: 낱말 다듬기."""
from . import chat

# 낱말 끝의 조사 (긴 것부터 봄). 떼고 남는 글자가 2자 이상일 때만 뗌 (나는 → 나는, 점심은 → 점심)
PARTICLES = ("에서", "이야", "은", "는", "이", "가", "을", "를", "에", "도", "야", "요")


def strip(token: str) -> str:
    """낱말 하나를 다듬습니다: 문장부호·웃음(ㅋㅎ) 떼기, 끝 조사 떼기."""
    word = chat._word(token)
    for p in PARTICLES:
        if word.endswith(p) and len(word) - len(p) >= 2:
            return word[: -len(p)]
    return word


def words(text: str) -> frozenset[str]:
    return frozenset(w for w in (strip(t) for t in chat._clean(text).split()) if w)
