"""우사기 1:1 대화에서 채팅 읽기: 물음의 화제와 의도, 앞 문맥 이어받기, 가르치는 말 알아보기.

물음은 (화제, 물음) 한 쌍으로 읽습니다: "오늘 점심 뭐야?" → (lunch, what). 화제 없이 짧게 물으면("그럼 저녁은?",
"왜?", "너는?") 바로 앞 문맥에서 빠진 쪽을 이어받고, "거기"·"그 집"은 방금 말한 식당입니다.
모르는 물음에 그 사람이 뜻이나 답을 알려 주면(teaching) 기억했다가, 다음에 그 말이 나오면 씁니다.
물음이 아닌 채팅에서도 모르는 낱말(new_word: 이름처럼 쓰인 낱말 중 기본 낱말·채팅 낱말·아는 말이 아닌 것)을 찾아
그 사람에게 뜻을 물어 조금씩 알아 갑니다 (누가 무엇을 알려 줬는지는 그 사람 기억에만).
디스코드·저장소와 상관없는 규칙이고, 바로 앞 문맥(Context)은 우사기 봇이 메모리에만 둡니다.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from . import chat, korean

# 낱말 끝의 조사 (긴 것부터 봄). 떼고 남는 글자가 2자 이상일 때만 뗌 (나는 → 나는, 점심은 → 점심)
PARTICLES = ("에서는", "에서도", "으로는", "이라고", "에게는", "한테는", "에서", "에게", "한테", "까지", "부터", "처럼", "보다",
             "이랑", "이야", "으로", "에는", "에도", "하고", "라고", "은", "는", "이", "가", "을", "를", "에", "도", "야", "요",
             "로", "랑", "만", "의", "엔")

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
REQUEST_ENDS = ("알아", "알려줘", "해줘", "뭐게")  # 물음표가 없어도 묻거나 부탁하는 말 ("점메추 해줘", "아샷추 알아")
# 모르는 낱말 풀이를 알려 줄 때 끝에 붙는 말 ("아이스티에 샷 추가라는 뜻이야" → 아이스티에 샷 추가)
GLOSS_ENDS = ("이라는 뜻이야", "라는 뜻이야", "이란 뜻이야", "란 뜻이야", "이라는 뜻", "라는 뜻", "란 뜻", "뜻이야",
              "말하는 거야", "말하는 거", "의미야", "의미", "거야", "이야", "야")
GLOSS_CHARS = 50
FOOD_WORDS = ("라멘", "라면", "국밥", "순대국", "치킨", "피자", "햄버거", "버거", "떡볶이", "초밥", "스시", "파스타",
              "짜장면", "짬뽕", "탕수육", "삼겹살", "고기", "김밥", "샐러드", "커피", "돈까스", "돈가스", "카레", "쌀국수",
              "냉면", "김치찌개", "된장찌개", "부대찌개", "비빔밥", "샌드위치", "마라탕", "족발", "보쌈", "우동", "덮밥")
# 모르는 낱말로 보지 않는 흔한 말 (사람마다 알려 준 말은 기억에 따로 쌓임)
BASE_WORDS = frozenset("""
오늘 내일 어제 모레 그제 지금 아까 이따 나중 요즘 이번 다음 지난 주말 평일 아침 점심 저녁 새벽 시간 하루 일주일 한달
회사 회의 사무실 출근 퇴근 야근 업무 일정 보고 미팅 팀장 팀장님 부장 부장님 과장 과장님 대리 사원 동료 직장 월급 연차 휴가
친구 가족 엄마 아빠 언니 누나 오빠 형 동생 사람 우리 너희 저희 여기 거기 저기 이거 그거 저거 무엇 어디 언제 누구
진짜 정말 완전 너무 엄청 되게 많이 조금 계속 그냥 빨리 천천히 같이 혼자 먼저 처음 마지막 오랜만 아마 혹시 사실 근데
그런데 그래서 그리고 하지만 그럼 그러면 아니 아니야 그래 맞아 날씨 하늘 바람 비가 집에 카페 식당 편의점 마트 학교 공부
운동 산책 여행 영화 드라마 음악 노래 유튜브 핸드폰 휴대폰 컴퓨터 노트북 메일 메시지 문자 카톡 버스 지하철 택시 자동차
강남 강남역 서울 선물 파티 주문 배달 점심시간 기분 마음 생각 느낌 이야기 얘기 대화 질문 대답 소리 우사기 하치와레 치이카와
음식 메뉴 추천 투표 식사 디저트 간식 술 맥주 소주 와인 음료 아이스 라떼 아메리카노 녹차 우유 과자 빵 케이크 아이스크림
생일 게임 점수 등급 멤버 채널 스레드 번역 기억 내용 오전 오후 하나 두개 세개 처음 정도 이상 이하 매일 항상 가끔 별로
""".split())
# 움직임·상태를 말하는 끝 (이 끝으로 끝나는 말은 이름이 아니라고 봄: 마시고, 싶다, 야근시킴)
PREDICATE_ENDS = ("다", "요", "고", "어", "아", "지", "네", "서", "면", "게", "자", "까", "래", "냐", "니", "음", "임",
                  "함", "됨", "김", "킴", "짐", "심", "기", "겠", "죠", "든", "던", "며", "러", "라", "해", "줘", "봐",
                  "데", "께", "걸", "군", "나", "랑", "며", "니까", "는데", "도록", "려고", "대", "워", "빠", "파", "써",
                  "려", "쳐", "져", "돼", "셔", "왔", "갔", "했", "봤", "줬", "났", "됐", "렸", "였", "겼", "와", "봐요", "야", "한",
                  "켜", "잖아")
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


def asking(text: str) -> bool:
    """물음이거나 부탁인지 ("점메추 해줘", "아샷추 알아" 도)."""
    return chat._asking(text) or any(chat._word(t).endswith(REQUEST_ENDS) for t in chat._clean(text).split())


def _known_keys() -> tuple:
    keys = [k for _, ks in chat.KINDS for k in ks] + [k for ks in TOPICS.values() for k in ks]
    keys += [k for ks in ASKS.values() for k in ks] + list(chat.ASK_WORDS) + list(chat.SOUNDS)
    return tuple(k for k in keys if not k.startswith("=")), frozenset(k[1:] for k in keys if k.startswith("="))


_INSIDE, _WHOLE = _known_keys()


def _plain_noun(word: str) -> bool:
    """우사기가 모를 수 있는, 이름처럼 쓰인 낱말인지 (한글 두 글자 이상, 흔한 말·채팅 낱말·음식·움직임 말이 아님)."""
    if len(word) < 2 or not all("가" <= c <= "힣" for c in word):
        return False
    if korean.common(word) or word in BASE_WORDS or word in REQUEST_WORDS or word in _WHOLE:
        return False  # 기본 낱말 (조사·'이다'를 떼어 보고: "끝이야", "출장이야")
    if word.endswith(PREDICATE_ENDS):
        return False
    return not any(k in word for k in _INSIDE) and not any(word.startswith(f) for f in FOOD_WORDS)


def new_word(text: str, known) -> str | None:
    """채팅에서 처음 보는 낱말 하나 (앞에 나온 것부터). known 은 그 사람이 이미 알려 줬거나 넘긴 말."""
    for token in chat._clean(text).split():
        raw, word = chat._word(token), strip(token)
        if word in known or raw in known:
            continue
        if _plain_noun(raw) and _plain_noun(word):  # 조사를 뗀 꼴과 뗀 앞 꼴 모두 모르는 말일 때만
            return word
    return None


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
    is_asking = asking(text)
    word = next(iter(ctx.unknown)) if ctx and ctx.unknown and len(ctx.unknown) == 1 else None
    if ctx and ctx.unknown and _fresh(ctx, now, TEACH_S) and (lesson := teaching(text, supported, word=word)):
        return Turn("teach", words=ctx.unknown, teach=lesson)
    if ctx and ctx.asked and not is_asking and len(said) <= REPLY_WORDS:
        return Turn("reply", topic=ctx.asked, words=said)

    key = key_words(said)
    meaning = next((t for t in taught if t["kind"] == "meaning" and set(t["words"]) <= said), None)
    answers = [(similar(key, key_words(frozenset(t["words"]))), t) for t in taught if t["kind"] == "answer"]
    best = max(answers, key=lambda a: a[0], default=(0.0, None))
    if meaning:
        return Turn("question", meaning["topic"], meaning["ask"], said)
    if best[0] >= SIMILAR:
        return Turn("taught", words=said, answer=best[1]["answer"])
    gloss = next((t for t in taught if t["kind"] == "word" and t["words"][0] in said), None)
    if gloss and is_asking:  # "아샷추가 뭐야?" → 알려 준 풀이로
        return Turn("gloss", words=frozenset(gloss["words"]), answer=gloss["means"])
    if not is_asking:
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


def teaching(text: str, supported: Callable[[str, str], bool], word: str | None = None) -> dict | None:
    """모르는 물음·낱말 뒤의 설명.

    답 알려 주기("'오늘도 화이팅'이라고 해 줘"), 뜻 알려 주기(아는 물음으로 이어지면: "점메추는 점심 메뉴 추천이야"),
    낱말 풀이(word 를 물었을 때, 아는 물음이 아니면: "아이스티에 샷 추가라는 뜻이야").
    """
    if m := _QUOTED.search(text):
        return {"kind": "answer", "answer": m.group(1).strip()[:ANSWER_CHARS]}
    if asking(text):  # 새 물음은 설명이 아님
        return None
    plain = chat._clean(text).strip().rstrip(" !.~…")
    if not (any(mark in plain for mark in MEANING_MARKS) or plain.endswith("야")):
        return None
    topic, ask = _topic(plain), _ask(plain) or "what"
    if topic and supported(topic, ask):
        return {"kind": "meaning", "topic": topic, "ask": ask}
    if word and (means := _gloss(plain, word)):
        return {"kind": "word", "means": means}
    return None


def _gloss(plain: str, word: str) -> str | None:
    for end in GLOSS_ENDS:
        if plain.endswith(end):
            plain = plain[: -len(end)].strip()
            break
    for lead in (word, "그건", "그거는", "그거"):
        if plain.startswith(lead):
            plain = plain[len(lead):].lstrip("은는이가란 ").strip()
            break
    return plain[:GLOSS_CHARS] or None
