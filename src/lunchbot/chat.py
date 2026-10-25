"""우사기 채널: 사람이 채팅을 보내면 우사기 봇이 우사기 소리로 답합니다.

우사기는 말을 하지 않으므로 소리만 내지만, 채팅을 읽고 무슨 채팅인지(인사, 질문, 배고픔, 피곤함, 웃음, 칭찬 …)
가려서 그에 맞는 소리로 답합니다. 질문에는 먼저 갸웃하고("하?"), 피곤한 채팅에는 시무룩하게, 밥 이야기에는
신나게, 우사기 소리를 보내면 같은 소리로 받아칩니다. 채팅에 두 가지가 섞여 있으면 소리도 섞습니다
("야근인데 배고파 ㅠ" → "후웅… 우라!"). 답 길이는 채팅 길이를 따라가되 1~4 소리(40자 이내)로 맞추고,
채팅의 물결(~)·느낌표·말줄임을 조금 따라 하며, 바로 전 답은 되풀이하지 않습니다.
어떻게 보낼지('입력 중…' 시간, 답장 표시, 가끔 덧붙이는 한마디)는 plan 이 정합니다.

채팅 내용은 디스코드 Message Content 권한이 있어야 읽을 수 있습니다. 권한이 없으면 빈 글자로 들어오므로
상황별 소리 중 하나를 무작위로 냅니다.
"""
import random
import re
from dataclasses import dataclass

from .messages import EXCITED, trill

T = "{t}"  # 떨림 소리 자리 (푸르르르…, 낼 때마다 길이가 바뀜)
VOCAB = frozenset({"우라", "야하", "야앗", "이얏", "와앗", "후웅", "흐응", "하아", "하"})  # 떨림 소리 말고 내는 소리


@dataclass(frozen=True)
class Voice:
    lead: tuple  # 첫 소리: 이 채팅에 가장 어울리는 소리
    more: tuple  # 둘째 소리부터 함께 섞는 소리
    ends: dict  # 끝맺음과 뽑힐 비중
    again: float = 0.25  # 앞 소리를 한 번 더 내는 비율 ("야하 야하~")


@dataclass(frozen=True)
class Reading:
    """채팅을 어떻게 읽었는지. 우사기가 목소리를 고를 때와 하치와레가 번역할 때 함께 씁니다."""
    kind: str  # KINDS 의 종류, echo(우사기 소리를 따라 함), plain(어느 종류도 아님), unknown(내용을 못 읽음)
    then: str | None = None  # 함께 섞인 둘째 종류
    asking: bool = False  # 질문인지
    sounds: tuple = ()  # 채팅에 있던 우사기 소리 (echo 일 때)


@dataclass(frozen=True)
class Step:
    text: str
    delay: float  # 보내기 전에 '입력 중…' 을 보여 줄 초
    quote: bool  # 채팅에 답장 표시를 달지 (안 달면 그냥 채널에 보냄)


# 채팅 종류와 알아보는 낱말. 앞에 있을수록 먼저 봅니다. '=' 로 시작하면 낱말 전체가 같아야 합니다 (네 → 네가 X)
KINDS = (
    ("greet", ("안녕", "=하이", "ㅎㅇ", "반가", "좋은 아침", "굿모닝", "=hi", "hello", "출근")),
    ("bye", ("잘가", "잘 가", "=바이", "ㅂㅂ", "ㅂㅇ", "퇴근", "내일 봐", "내일봐", "잘자", "잘 자", "수고", "먼저 갈게")),
    ("praise", ("귀여", "귀엽", "최고", "사랑", "잘했", "잘 했", "짱", "멋지", "멋있", "고마", "감사", "착하", "좋아")),
    ("laugh", ("ㅋㅋ", "=ㅋ", "ㅎㅎ", "하하", "히히", "웃기", "웃겨", "웃김", "lol")),
    ("sad", ("ㅠ", "ㅜ", "피곤", "힘들", "힘드", "야근", "슬퍼", "슬프", "우울", "졸려", "졸리", "지쳐", "지친",
             "아파", "아프", "망했", "싫어", "못 했", "못했", "외로", "월요일")),
    ("angry", ("짜증", "화나", "화난", "열받", "열 받", "빡치", "빡쳐", "아오", "젠장", "억울")),
    ("food", ("배고", "배 고", "밥", "점심", "저녁", "먹", "고기", "라면", "치킨", "피자", "맛있", "맛집", "배달",
              "간식", "야식", "맥주", "소주", "한잔", "한 잔", "커피", "햄버거", "국밥", "떡볶이", "회식")),
    ("surprise", ("=헐", "대박", "=와", "우와", "실화", "미쳤", "=엥", "세상에", "어머", "ㄷㄷ", "=헉")),
    ("agree", ("=ㅇ", "ㅇㅇ", "ㅇㅋ", "=응", "=웅", "=넹", "=넵", "=네", "그래", "오케이", "=ok", "알겠", "ㄱㄱ",
               "고고", "가자")),
    ("call", ("우사기",)),
)
ASK_WORDS = ("뭐", "뭘", "왜", "어디", "언제", "어떻게", "어때", "누구", "무슨", "몇", "할까", "갈까", "먹을까",
             "할래", "갈래", "먹을래")
SOUNDS = ("우라", "야하", "야앗", "이얏", "와앗", "후웅", "흐응", "하아")  # 채팅에 있으면 같은 소리로 받아침

VOICES = {
    "greet": Voice(("야하", "야앗"), ("우라", "와앗"), {"!": 4, "~": 4, "": 1}),
    "bye": Voice(("야하", "우라"), ("흐응", "야하", T), {"~": 6, "!": 2, "…": 1}),
    "praise": Voice(("야하", "와앗"), ("우라", "야하", T), {"~": 4, "!": 3, "": 1}, again=0.3),
    "laugh": Voice(("야하", "와앗"), ("야하", "와앗", "우라"), {"": 3, "!": 3, "~": 2}, again=0.5),
    "sad": Voice(("후웅", "흐응", T), ("후웅", "흐응", T), {"…": 5, "~": 2, "": 2}),
    "angry": Voice(("이얏", "하아", "후웅"), ("우라", "이얏", "하아"), {"!": 5, "…": 2, "!!": 1}),
    "food": Voice(EXCITED, EXCITED, {"!": 7, "~": 2, "!!": 1}),
    "surprise": Voice(("와앗", "야앗", "하"), ("와앗", "우라", "하아"), {"!": 4, "?!": 2, "…": 1}),
    "agree": Voice(("우라", "야하"), ("우라", "야하", "이얏"), {"!": 5, "~": 2, "": 1}),
    "call": Voice(("야앗", "하", "야하"), ("야하", "우라"), {"?": 4, "!": 3, "~": 2}),
    "plain": Voice(("야하", "우라", "와앗", "하", "후웅"), ("야하", "우라", "와앗", T),
                   {"!": 3, "~": 3, "…": 1, "?": 1, "": 1}),
}
ASK = Voice(("하", "후웅", "하아", "야앗"), (), {"?": 6, "…?": 2})  # 질문을 받으면 먼저 갸웃
ASK_FIRST = 0.88  # 질문에 갸웃부터 하는 비율 (나머지는 바로 신나게 답함)
MIX = 0.6  # 채팅에 두 종류가 섞였을 때 둘째 소리부터 두 번째 종류 소리를 낼 비율
RANDOM = {"food": 4, "praise": 3, "sad": 2, "call": 1}  # 채팅 내용을 못 읽을 때 (대체로 신남)

# 채팅 길이(글자)에 따라 낼 소리 개수와 비중: 짧은 채팅엔 짧게, 긴 채팅엔 길게
LENGTHS = ((2, {1: 8, 2: 2}), (6, {1: 5, 2: 4, 3: 1}), (15, {1: 3, 2: 5, 3: 2}), (30, {2: 5, 3: 4, 4: 1}),
           (None, {2: 3, 3: 5, 4: 2}))
MAX_SOUNDS, MAX_CHARS = 4, 40
QUOTE = 0.6  # 답장 표시를 다는 비율
AFTERWORD = 0.18  # 짧게 한마디를 더 보내는 비율

_NOISE = re.compile(r"<a?:\w+:\d+>|<[@#][!&]?\d+>|https?://\S+")  # 멘션, 채널, 커스텀 이모지, 링크
_PUNCT = "!?.,~…;:'\"()"
_JAMO = "ㅋㅎㅠㅜ"  # 낱말 뒤에 붙은 웃음·울음 (응ㅋㅋ → 응). 앞쪽은 떼지 않음 (ㅎㅇ 은 인사)


def should_reply(author_is_bot: bool, channel_id: str, usagi_channel_id: str, parent_id: str | None = None) -> bool:
    """우사기 채널과 그 아래 스레드(/우사기 1:1 스레드)에서 사람이 보낸 채팅에만 답합니다 (봇끼리 주고받지 않게)."""
    here = str(usagi_channel_id)
    return bool(usagi_channel_id) and not author_is_bot and here in (str(channel_id), str(parent_id))


def reply(text: str = "", rng=None, last: str | None = None) -> str:
    """채팅에 답할 우사기 소리 한 줄. last 와 같은 답은 내지 않습니다."""
    rng = rng or random
    for _ in range(10):
        line = _compose(text, rng)
        if line != last:
            return line
    return line.rstrip("!?~…") + ("!" if line.endswith("~") else "~")


def plan(text: str = "", rng=None, last: str | None = None) -> list[Step]:
    """채팅에 어떻게 답할지: 보낼 글, 그 전에 '입력 중…' 을 보여 줄 시간, 답장 표시를 달지.

    가끔 짧게 한마디를 따로 더 보냅니다 ("하?" 다음에 "우라!").
    """
    rng = rng or random
    line = reply(text, rng, last)
    steps = [Step(line, _typing(text, line, rng), quote=rng.random() < QUOTE)]
    if rng.random() < AFTERWORD:
        steps.append(Step(_afterword(text, line, rng), round(rng.uniform(0.4, 1.2), 2), quote=False))
    return steps


def read(text: str) -> Reading:
    """채팅이 무슨 채팅인지 읽습니다."""
    text = _clean(text)
    if not text:
        return Reading("unknown")
    kinds, found, asking = _kinds(text), _sounds(text), _asking(text)
    if found:  # 우사기 소리를 보냈으면 같은 소리로 받아침
        return Reading("echo", kinds[0] if kinds else None, asking, tuple(found))
    rest = [k for k in kinds[1:] if k != "call"]
    return Reading(kinds[0] if kinds else "plain", rest[0] if rest else None, asking)


def _compose(text: str, rng) -> str:
    reading = read(text)
    if reading.kind == "unknown":
        return _line(rng, VOICES[_pick(RANDOM, rng)], _pick({1: 4, 2: 4, 3: 2}, rng))
    text = _clean(text)
    voice, then = _voices(reading)
    n = _pick(next(w for limit, w in LENGTHS if limit is None or len(text) <= limit), rng)
    if text.count("ㅋ") >= 6:  # 크게 웃으면 더 길게 웃음
        n += 1
    ask = reading.asking and rng.random() < ASK_FIRST
    return _line(rng, voice, min(n, MAX_SOUNDS), ask=ask, then=then, boost=_mirror(text))


def _line(rng, voice: Voice, n: int, ask=False, then: Voice | None = None, boost=None) -> str:
    words, prev, key, prev_voice = [], None, None, None  # key: 앞 소리 종류 (떨림 소리는 길이와 상관없이 T)
    if ask:
        words.append(rng.choice(ASK.lead) + _pick(ASK.ends, rng))
        n -= 1
    for i in range(n):
        v = then if then and i > 0 and rng.random() < MIX else voice
        if prev and prev != "하" and rng.random() < prev_voice.again:
            v = prev_voice
            words[-1] = base = prev  # 같은 소리를 잇달아: "야하 야하~"
        else:
            pool = v.lead if i == 0 else v.lead + v.more
            key = rng.choice([b for b in pool if b != key] or pool)
            base = trill(rng) if key == T else key
        ends = {e: w + (boost or {}).get(e, 0) for e, w in v.ends.items()}
        words.append(base + (_pick(ends, rng) or ("!" if base == "하" else "")))  # '하' 만 덩그러니 두지 않음
        prev, prev_voice = base, v
    while len(" ".join(words)) > MAX_CHARS and len(words) > 1:
        words.pop()
    return " ".join(words)


def _afterword(text: str, line: str, rng) -> str:
    """덧붙이는 한마디: 채팅 종류에 맞는 소리 하나 (질문이었으면 갸웃 다음의 대답)."""
    reading = read(text)
    voice = VOICES[_pick(RANDOM, rng)] if reading.kind == "unknown" else _voices(reading)[0]
    word = _line(rng, voice, 1, boost=_mirror(text))
    for _ in range(5):
        if word != line.split()[-1]:
            break
        word = _line(rng, voice, 1)
    return word


def _typing(text: str, line: str, rng) -> float:
    # 읽는 시간(채팅 길이) + 치는 시간(답 길이) + 들쭉날쭉
    seconds = 0.4 + min(len(text), 80) * 0.01 + len(line) * 0.07 + rng.uniform(0, 0.4)
    return round(min(3.0, max(0.3, seconds)), 2)


def _voices(reading: Reading) -> tuple[Voice, Voice | None]:
    """(첫 소리를 정할 목소리, 섞을 둘째 목소리)."""
    then = VOICES[reading.then] if reading.then else None
    if reading.kind == "echo":
        found = reading.sounds
        return Voice(found, ("야하", "우라", "와앗") + found, {"!": 3, "~": 2, "": 1}, again=0.4), then
    return VOICES[reading.kind], then


def _kinds(text: str) -> list[str]:
    low = text.lower()
    tokens = {_word(w) for w in low.split()}
    return [kind for kind, keys in KINDS
            if any(k[1:] in tokens if k.startswith("=") else k in low for k in keys)]


def _sounds(text: str) -> list[str]:
    found = {s: text.find(s) for s in SOUNDS if s in text}
    if m := re.search("푸르{2,}", text):
        found[T] = m.start()
    if "하" in {_word(w) for w in text.split()}:
        found["하"] = text.find("하")
    return sorted(found, key=found.get)


def _word(token: str) -> str:
    return token.strip(_PUNCT).rstrip(_JAMO).strip(_PUNCT)


def _asking(text: str) -> bool:
    return text.rstrip(" ~!.…").endswith("?") or any(w in text for w in ASK_WORDS)


def _mirror(text: str) -> dict:
    """채팅의 끝맺음을 조금 따라 합니다: 물결엔 물결, 느낌표엔 느낌표, 말줄임엔 말줄임."""
    return {"~": 3 * ("~" in text), "!": 2 * ("!" in text), "…": 2 * ("…" in text or ".." in text)}


def _clean(text: str) -> str:
    return " ".join(_NOISE.sub(" ", text or "").split())


def _pick(weights: dict, rng):
    return rng.choices(list(weights), weights=list(weights.values()))[0]
