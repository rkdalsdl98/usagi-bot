"""우사기 1:1 대화에서 채팅 읽기: 물음의 화제와 의도, 앞 문맥 이어받기, 가르치는 말 알아보기.

물음은 (화제, 물음) 한 쌍으로 읽습니다: "오늘 점심 뭐야?" → (lunch, what). 화제 없이 짧게 물으면("그럼 저녁은?",
"왜?", "너는?") 바로 앞 문맥에서 빠진 쪽을 이어받고, "거기"·"그 집"은 방금 말한 식당입니다.
모르는 물음에 그 사람이 뜻이나 답을 알려 주면(teaching) 기억했다가, 다음에 그 말이 나오면 씁니다.
디스코드·저장소와 상관없는 규칙이고, 바로 앞 문맥(Context)은 우사기 봇이 메모리에만 둡니다.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from . import chat

# 낱말 끝의 조사 (긴 것부터 봄). 떼고 남는 글자가 2자 이상일 때만 뗌 (나는 → 나는, 점심은 → 점심)
PARTICLES = ("에서", "이야", "은", "는", "이", "가", "을", "를", "에", "도", "야", "요")

CONTEXT_S = 600  # 바로 앞 문맥을 이어받는 시간 (10분)
TEACH_S = 300  # 모르는 물음 뒤 설명을 기다리는 시간 (5분)
SIMILAR = 0.5  # 가르친 답을 쓸 만큼 비슷한 물음 (낱말 겹침)
REPLY_WORDS = 3  # 우사기가 되물은 것에 대한 답으로 볼 짧은 채팅
ANSWER_CHARS = 100  # 알려 준 답 문장 길이

# 화제: 채팅에서 가장 먼저 나온 것. '=' 로 시작하면 낱말 전체가 같아야 함 (너 → 너, 너무 X)
TOPICS = {
    "lunch": ("점심", "오점뭐"),
    "dinner": ("저녁", "오저뭐", "야식"),
    "last": ("지난번", "저번에", "저번 ", "어제 뭐"),
    "birthday": ("생일",),
    "game": ("게임", "점수"),
    "rank": ("등급", "갑옷"),
    "time": ("몇 시", "몇시", "지금 몇", "시간"),
    "off": ("퇴근", "칼퇴"),
    "usagi": ("우사기", "=너", "=넌", "=너는", "=너도", "=니"),
    "hachiware": ("하치와레",),
    "me": ("내가", "나를", "날 기억", "나 기억", "나 알아", "나에 대해", "=나"),
    "talk": ("얘기했", "이야기했", "대화했", "마지막으로"),
    "bored": ("심심", "할 거 없", "할거없"),
    "tired": ("힘들", "힘든", "힘드", "피곤", "지쳐", "지친", "우울"),
    "food": ("먹을까", "뭐 먹", "메뉴 추천", "배고"),
    "place": ("거기", "그 집", "그집", "그거", "그 식당", "그 가게"),
}
# 물음: 앞에 있을수록 먼저 봄 ("뭐 좋아해?" 는 what 이 아니라 like)
ASKS = {
    "like": ("좋아",),
    "remember": ("기억",),
    "eat": ("밥 먹었", "밥은 먹", "밥 먹어", "식사했"),
    "who": ("누구", "누군"),
    "why": ("=왜", "어째서"),
    "really": ("=진짜", "=정말", "=레알"),
    "when": ("언제", "얼마나", "남았"),
    "how": ("어때", "어떡", "어떻게", "맛있"),
    "where": ("어디",),
    "what": ("뭐", "뭘", "무슨", "몇", "정해졌", "정했", "골랐"),
}
TO_USAGI = ("eat", "who", "like")  # 화제 없이 이렇게 물으면 우사기에게 묻는 것 ("밥 먹었어?")
MEANING_MARKS = ("라는 뜻", "란 뜻", "뜻이야", "말하는 거", "의미")
# 가르친 말을 기억할 때 빼는 부탁말 (물음말이 든 낱말도 뺌): "점메추 해줘?" → 점메추
REQUEST_WORDS = frozenset({"해", "해줘", "해줄래", "해주라", "해봐", "줘", "줄래", "주라", "좀", "알려줘", "말해", "말해줘",
                           "부탁해"})
_QUOTED = re.compile(r"['\"‘“]([^'\"‘’“”]+)['\"’”]\s*(?:이)?라고")


@dataclass
class Context:
    """바로 앞 문맥 (사람마다, 메모리에만)."""
    topic: str | None
    ask: str | None
    target: str | None  # 방금 말한 식당
    asked: str | None  # 우사기가 되물은 화제 (다음 채팅을 그 답으로 읽음)
    unknown: frozenset | None  # 방금 모른다고 한 물음의 낱말 (다음 채팅이 설명이면 배움)
    at: datetime


@dataclass
class Turn:
    kind: str  # question, taught, unknown, teach, reply, chat
    topic: str | None = None
    ask: str | None = None
    words: frozenset = field(default_factory=frozenset)
    follow: bool = False  # 앞 문맥을 이어받았는지
    teach: dict | None = None
    answer: str | None = None


def strip(token: str) -> str:
    """낱말 하나를 다듬습니다: 문장부호·웃음(ㅋㅎ) 떼기, 끝 조사 떼기."""
    word = chat._word(token)
    for p in PARTICLES:
        if word.endswith(p) and len(word) - len(p) >= 2:
            return word[: -len(p)]
    return word


def words(text: str) -> frozenset[str]:
    return frozenset(w for w in (strip(t) for t in chat._clean(text).split()) if w)


def key_words(said: frozenset) -> frozenset:
    """가르친 말을 알아볼 핵심 낱말 (물음말·부탁말을 뺌). 다 빠지면 그대로."""
    kept = frozenset(w for w in said if w not in REQUEST_WORDS and not any(a in w for a in chat.ASK_WORDS))
    return kept or said


def similar(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def _where(text: str, keys) -> int | None:
    """채팅에서 그 낱말들이 처음 나온 자리."""
    low = text.lower()
    tokens = [chat._word(t) for t in low.split()]
    found = []
    for k in keys:
        if k.startswith("="):
            pos = next((low.find(t) for t in tokens if t == k[1:]), -1)
        else:
            pos = low.find(k)
        if pos >= 0:
            found.append(pos)
    return min(found) if found else None


def _topic(text: str) -> str | None:
    seen = {t: p for t, keys in TOPICS.items() if (p := _where(text, keys)) is not None}
    return min(seen, key=seen.get) if seen else None


def _ask(text: str) -> str | None:
    return next((a for a, keys in ASKS.items() if _where(text, keys) is not None), None)


def _fresh(ctx: Context | None, now: datetime, seconds: int) -> bool:
    return ctx is not None and (now - ctx.at).total_seconds() <= seconds


def understand(text: str, ctx: Context | None, now: datetime, taught: list,
               supported: Callable[[str, str], bool]) -> Turn:
    """채팅 하나를 읽습니다. taught 는 그 사람이 가르친 것 (memory 의 taught), supported 는 답할 수 있는 (화제, 물음)."""
    if not _fresh(ctx, now, CONTEXT_S):
        ctx = None
    said = words(text)
    asking = chat._asking(text)
    if ctx and ctx.unknown and _fresh(ctx, now, TEACH_S) and (lesson := teaching(text, supported)):
        return Turn("teach", words=ctx.unknown, teach=lesson)
    if ctx and ctx.asked and not asking and len(said) <= REPLY_WORDS:
        return Turn("reply", topic=ctx.asked, words=said)

    key = key_words(said)
    meaning = next((t for t in taught if t["kind"] == "meaning" and set(t["words"]) <= said), None)
    answers = [(similar(key, key_words(frozenset(t["words"]))), t) for t in taught if t["kind"] == "answer"]
    best = max(answers, key=lambda a: a[0], default=(0.0, None))
    if meaning:
        return Turn("question", meaning["topic"], meaning["ask"], said)
    if best[0] >= SIMILAR:
        return Turn("taught", words=said, answer=best[1]["answer"])
    if not asking:
        return Turn("chat", words=said)

    topic, ask, follow = _topic(text), _ask(text), False
    if ctx and topic is None and ctx.topic:
        topic, follow = ctx.topic, True
    if ctx and ask is None and ctx.ask:
        ask, follow = ctx.ask, True
    if topic is None and ask in TO_USAGI:
        topic = "usagi"
    if topic and ask and supported(topic, ask):
        return Turn("question", topic, ask, said, follow)
    return Turn("unknown", topic, ask, said, follow)


def teaching(text: str, supported: Callable[[str, str], bool]) -> dict | None:
    """모르는 물음 뒤의 설명. 답 알려 주기("'오늘도 화이팅'이라고 해 줘") 또는 뜻 알려 주기("점메추는 점심 메뉴 추천이야")."""
    if m := _QUOTED.search(text):
        return {"kind": "answer", "answer": m.group(1).strip()[:ANSWER_CHARS]}
    if chat._asking(text):  # 새 물음은 설명이 아님
        return None
    plain = text.strip().rstrip(" !.~…")
    if not (any(mark in plain for mark in MEANING_MARKS) or plain.endswith("야")):
        return None
    topic, ask = _topic(plain), _ask(plain) or "what"
    if topic and supported(topic, ask):
        return {"kind": "meaning", "topic": topic, "ask": ask}
    return None
