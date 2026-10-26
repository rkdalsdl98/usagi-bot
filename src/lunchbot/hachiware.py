"""하치와레: 우사기가 낸 소리를 사람들에게 번역해 줍니다 (웹훅으로 보냄).

우사기는 말을 못 하지만 하치와레는 말을 할 수 있고, 우사기 말을 알아듣습니다.
번역은 우사기 소리 한 토막마다 하치와레 말 한 토막이 짝을 이룹니다. 소리가 둘이면 번역도 두 토막이고,
번역 토막의 끝맺음(!, ~, …, ?)과 소리의 끝맺음이 같습니다. 그래서 '우라!' 한마디에 긴 문장이 붙지 않습니다.
하치와레는 짧은 틀('"…"래!')로 전합니다 (relay). 우사기 채널 대화와 메뉴 추천·투표 결과 번역에서는 가끔
번역 뒤 따옴표 밖에 하치와레 자기 생각을 한마디 보탭니다 (COMMENTS, retell). 따옴표 안의 번역은 그대로
소리와 토막 수가 같습니다.

  메뉴 추천·투표 결과·명령   소리와 번역을 함께 만듭니다 (Script: recommend_script, result_script, notice_script).
                           토막마다 (기분, 말) 을 고르면 기분에 맞는 소리를 말의 끝맺음으로 냅니다 (speak)
  우사기 채널 대화           우사기가 이미 낸 소리(chat.plan)를 토막마다 번역합니다 (chunks). 채팅을 어떻게 읽었는지
                           (chat.read)로 토막의 뜻을 고릅니다: 갸웃한 첫 소리는 갸웃한 말, 섞인 채팅이면 둘째 종류의
                           목소리로 낸 소리는 둘째 종류의 말, 종류를 모르면 그 소리의 느낌(SOUNDS)

번역 설정은 둘이고, 우사기 말이 나오는 곳에 따라 정해집니다 (is_on). 꺼져 있으면 그곳의 우사기 말은 무엇이든 번역하지 않습니다.
  서버 전체 (/전체번역 켜기·끄기, 직장인)  모두가 보는 채널: 우사기 채널 대화, 메뉴 추천·투표 결과, 명령의 결과 안내.
                                         기본은 꺼짐 (settings/hachiware.json)
  개인 (/하치와레 번역 켜기·끄기, 누구나)      내 /우사기 1:1 스레드 안. 정하지 않은 사람은 서버 전체 설정을 따릅니다
                                         (settings/hachiware_people.json)
웹훅은 채널마다 따로 있고(HACHIWARE_WEBHOOK_URLS), 그 채널의 우사기 말은 그 채널의 하치와레가 번역합니다.
/도움 은 번역이 아니라 사용법이라, 명령을 쓴 사람에게만 보이는 답에 붙고 꺼져 있어도 보여 줍니다 (commands.py).
사람은 멘션(<@id>)으로 부르지만 멘션 알림은 막아서 알림이 가지 않습니다.
"""
import random
import re
from dataclasses import dataclass

from . import config, discord, members, messages, storage
from .chat import T, VOICES, Reading

ENDS = ("…?", "?", "!", "~", "…")  # 토막의 끝맺음 (앞에 있을수록 먼저 봄)
_SWAP = {"!", "~", "…"}  # 서로 바꿔 끼워도 자연스러운 끝맺음


@dataclass(frozen=True)
class Script:
    """우사기 소리와 하치와레 번역을 한 토막씩 짝지은 것."""
    parts: tuple  # ((우사기 소리 토막, 하치와레 말 토막), ...)

    @property
    def sound(self) -> str:
        return " ".join(sound for sound, _ in self.parts)

    @property
    def text(self) -> str:
        return " ".join(chunk for _, chunk in self.parts)


def ending(text: str) -> str:
    return next((e for e in ENDS if text.endswith(e)), "")


def speak(beats, rng=None) -> Script:
    """[(기분, 말 토막), ...] 으로 우사기 소리와 하치와레 번역을 함께 만듭니다.

    기분(messages.MOODS)에 맞는 소리를 말 토막의 끝맺음으로 냅니다. 기분 자리에 '우라!' 처럼 소리를 그대로 쓰면 그 소리.
    """
    rng = rng or random
    parts, prev = [], None
    for mood, chunk in beats:
        sound = messages.mood_sound(mood, ending(chunk) or None, rng, avoid=prev) if mood in messages.MOODS else mood
        parts.append((sound, chunk))
        prev = "푸르르" if sound.startswith("푸르") else sound.strip("!?…~")
    return Script(tuple(parts))


# 하치와레가 전하는 짧은 틀. {m} 자리에 번역 토막들이 들어갑니다
FRAMES = {'"{m}"래!': 4, '"{m}"래~': 2, '우사기가 "{m}"래': 2, '"{m}"라고 하네!': 2}
UNSURE = {'음… "{m}" 아닐까?': 1, '아마 "{m}"래': 1}  # 채팅 내용을 못 읽었을 때


def relay(text: str, rng=None, unsure: bool = False) -> str:
    """번역 토막들을 하치와레 말투로 전합니다."""
    rng = rng or random
    return _pick(UNSURE if unsure else FRAMES, rng).format(m=text)


def retell(text: str, about: str, rng=None, **kw) -> str:
    """메뉴 추천·투표 결과 번역: 짧은 틀로 전하고, 가끔 따옴표 밖에 하치와레 자기 생각을 보탭니다.

    about 은 lunch, dinner (추천), won (식당이 정해짐, kw 의 name), none (선택 없음).
    """
    rng = rng or random
    line = relay(text, rng)
    if rng.random() < COMMENT:
        line = f"{line} {rng.choice(COMMENTS[about]).format(**kw)}"
    return line


# ── 우사기 채널 대화: 토막마다 우사기가 하려던 말 (채팅 종류마다, 갸웃(ask), 따라 하기(echo)) ──
MEANINGS = {
    "ask": ("응?", "음…?", "글쎄?", "뭐지?", "그게 뭐야?"),
    "greet": ("안녕!", "반가워!", "왔구나~", "기다렸어!", "안녕안녕~", "잘 지냈어?"),
    "bye": ("잘 가~", "또 봐!", "수고했어!", "푹 쉬어~", "내일 봐~"),
    "praise": ("헤헤~", "고마워!", "나도 좋아!", "부끄러워…", "칭찬 더!"),
    "laugh": ("웃겨!", "히히~", "재밌다!", "못 참겠어!", "크크…"),
    "sad": ("힘들었지…", "토닥토닥~", "괜찮아질 거야…", "푹 쉬자…", "힘내~"),
    "angry": ("누구야!", "혼내 줄게!", "화난다!", "씩씩…", "같이 화낼게!"),
    "food": ("밥!", "고기!", "배고파!", "빨리 가자!", "맛있겠다~", "먹자!"),
    "surprise": ("진짜?!", "깜짝이야!", "대박!", "우와!", "헉…"),
    "agree": ("좋아!", "찬성!", "응응~", "가자!", "알았어!"),
    "call": ("불렀어?", "여기 있어!", "왜왜?", "응!", "나 여기~"),
    "echo": ("나도!", "같이 하자!", "그 소리 좋다~", "따라 할래!", "또 해 줘!"),
}
# 채팅 종류를 모를 때 소리마다의 느낌
SOUNDS = {
    "우라": ("좋아!", "가자!"),
    "야하": ("신난다!", "야호~"),
    "야앗": ("앗!", "여기!"),
    "이얏": ("에잇!", "간다!"),
    "와앗": ("우와!", "멋지다~"),
    "후웅": ("힝…", "아쉽다…"),
    "흐응": ("흐음…", "그렇구나…"),
    "하아": ("휴…", "진짜…"),
    "하": ("응?", "어?"),
    T: ("기분 좋다~", "포근해…"),
}
# 하치와레가 번역 뒤에 보태는 자기 생각 (따옴표 밖)
COMMENTS = {
    "greet": ("나도 반가워!", "오늘도 잘 부탁해!", "우사기 기분 좋아 보여~"),
    "bye": ("조심히 들어가!", "나도 내일 봐!", "오늘도 수고 많았어~"),
    "praise": ("우사기 엄청 좋아하는 것 같아!", "나도 칭찬받고 싶다…", "우사기 얼굴 빨개졌어~"),
    "laugh": ("나도 웃음 나와!", "둘 다 너무 웃겨!", "우사기 웃음소리 좋다~"),
    "sad": ("어떻게든 될 거야!", "나도 응원할게!", "오늘은 일찍 쉬자…"),
    "angry": ("우사기 진심이야…", "맛있는 거 먹으면 풀릴 거야!", "나도 좀 화났어!"),
    "food": ("나도 배고파졌어…", "나도 같이 갈래!", "벌써 침 고인다…"),
    "surprise": ("나도 깜짝 놀랐어!", "진짜 놀랍다…", "세상에…"),
    "agree": ("그럼 결정!", "나도 찬성이야!", "좋아, 그렇게 하자!"),
    "call": ("우사기 대답 빠르다!", "우사기 여기 있어!", "부르니까 바로 왔네~"),
    "echo": ("둘이 똑같네!", "나도 따라 해 볼까…", "우사기 소리 잘 따라 하네!"),
    "plain": ("나도 다 알아듣는 건 아니지만!", "아마 그럴 거야!", "우사기 말은 느낌으로 알아들어야 해~"),
    "unknown": ("우사기 마음은 가끔 어려워…", "다음엔 꼭 알아들을게!"),
    # 메뉴 추천과 투표 결과 (retell). won 의 {name} 은 정해진 식당
    "lunch": ("나도 점심 같이 먹고 싶다…", "다 맛있어 보여서 고민되겠다~", "난 첫 번째가 끌려!", "오늘도 맛있게 먹자!"),
    "dinner": ("야근 힘내! 맛있는 거 먹고 하자~", "오늘은 한잔도 괜찮겠다…", "든든하게 먹어야 버틴다!",
               "나도 배고파졌어…"),
    "won": ("맛있게 먹고 와!", "나도 따라가고 싶다…", "좋은 선택이야!", "{name} 맛있겠다~"),
    "none": ("다음엔 꼭 정하자!", "다들 배 안 고팠나 봐…", "괜찮아, 내일 또 있어~"),
}
COMMENT = 0.35  # 자기 생각을 보태는 비율
CALL_NAME = 0.25  # 채팅한 사람을 부르는 비율 ("한강민, …")
MAX_CHARS = 80


def translate(reading: Reading, usagi: str, rng=None, name: str | None = None, last: str | None = None) -> str:
    """우사기가 낸 소리(usagi)를 하치와레 말로. reading 은 우사기가 읽은 채팅, last 와 같은 번역은 내지 않습니다."""
    rng = rng or random
    for _ in range(10):
        line = relay(" ".join(chunks(reading, usagi, rng)), rng, unsure=reading.kind == "unknown")
        thought = rng.choice(COMMENTS.get(reading.kind, COMMENTS["plain"])) if rng.random() < COMMENT else ""
        who = f"{name}, " if name and rng.random() < CALL_NAME else ""
        if thought and len(who + line) + 1 + len(thought) <= MAX_CHARS:  # 길면 자기 생각은 뺌
            line = f"{line} {thought}"
        line = who + line
        if line != last:
            return line
    return line[:-1] if line.endswith("!") else line + "!"


def chunks(reading: Reading, usagi: str, rng=None) -> list[str]:
    """우사기 소리 토막마다 번역 토막 하나. 같은 소리를 잇달아 내면 같은 말을 되풀이합니다 ("히히~ 히히~")."""
    rng = rng or random
    words = usagi.split()
    asked = reading.asking and bool(words) and words[0].endswith("?")
    out, prev = [], None
    for i, word in enumerate(words):
        base = _base(word)
        if i and base == prev:
            out.append(_reend(out[-1], ending(word)))
            continue
        if i == 0 and asked:
            pool = MEANINGS["ask"]
        elif reading.kind in MEANINGS:
            pool = MEANINGS[_kind_of(reading, base, first=i == int(asked))]
        else:  # plain, unknown
            pool = SOUNDS.get(base, SOUNDS["야하"])
        out.append(_fit(pool, ending(word), out, rng))
        prev = base
    return out


def _kind_of(reading: Reading, base: str, first: bool) -> str:
    """이 소리가 섞인 둘째 종류의 목소리로 낸 소리면 둘째 종류, 아니면 첫 종류."""
    if first or not reading.then:
        return reading.kind
    own = reading.sounds if reading.kind == "echo" else VOICES[reading.kind].lead
    other = VOICES[reading.then]
    return reading.then if base in other.lead + other.more and base not in own else reading.kind


def _fit(pool, end: str, used: list, rng) -> str:
    """끝맺음이 같은 말을 먼저 고르고, 없으면 끝맺음을 소리에 맞춰 바꿉니다."""
    said = {c.rstrip("!?…~") for c in used}  # 끝맺음만 다른 같은 말도 되풀이하지 않음
    fresh = [c for c in pool if c.rstrip("!?…~") not in said] or list(pool)
    same = [c for c in fresh if ending(c) == end]
    return _reend(rng.choice(same or fresh), end)


def _reend(chunk: str, end: str) -> str:
    """!~… 끼리는 소리의 끝맺음으로 바꾸고, 끝맺음 없는 소리("흐응 흐응…")에는 떼어 냅니다. ? 가 든 말은 그대로."""
    have = ending(chunk)
    if have in _SWAP | {""} and end in _SWAP | {""}:
        return (chunk[: -len(have)] if have else chunk) + end
    return chunk


def _base(word: str) -> str:
    word = word.strip("!?…~")
    return T if re.fullmatch("푸르{2,}", word) else word


def _pick(weights: dict, rng):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


# ── 메뉴 추천 메시지: 여는 말 + (그날 상황, 덧붙이는 말) + 닫는 말 ──
RECOMMEND = {
    "lunch": {
        "open": [("excited", "점심이다!"), ("excited", "밥 시간!"), ("happy", "드디어 점심~"), ("trill", "배고파…"),
                 ("excited", "점심 골라 왔어!")],
        "more": [("excited", "다 맛있겠다!"), ("happy", "여기 봐 봐~"), ("puzzled", "뭐 먹지?"), ("excited", "골고루 골랐어!"),
                 ("happy", "사진도 있어~")],
        "close": [("excited", "골라 줘!"), ("excited", "투표해 줘!"), ("excited", "빨리 정하자!"), ("happy", "같이 가자~"),
                  ("happy", "눌러 줘~")],
    },
    "dinner": {
        "open": [("excited", "저녁이다!"), ("sulky", "야근 힘들지…"), ("trill", "배고파…"), ("happy", "저녁 먹자~"),
                 ("sulky", "오늘도 야근…")],
        "more": [("excited", "든든하게 먹자!"), ("happy", "여기 봐 봐~"), ("puzzled", "뭐 먹지?"), ("excited", "힘내자!")],
        "close": [("excited", "골라 줘!"), ("excited", "투표해 줘!"), ("excited", "빨리 정하자!"), ("happy", "같이 가자~"),
                  ("excited", "먹고 힘내!")],
    },
}
FACTS = {  # 그날 상황
    "drink": [("excited", "술집도 있어!"), ("puzzled", "한잔할래?")],
    "today_lunch": [("happy", "점심 데는 뺐어~")],
    "latest": [("puzzled", "지난번은 '{latest}'?"), ("happy", "지난번 '{latest}' 맛있었지~")],
}
# 투표가 끝났을 때 (정해진 식당 이름은 {name})
RESULT = [
    [("excited", "정했다!"), ("happy", "{name} 가자~")],
    [("excited", "{name}!"), ("excited", "가자!")],
    [("happy", "결정~"), ("excited", "오늘은 {name}!")],
    [("excited", "와!"), ("excited", "{name}!"), ("happy", "신난다~")],
    [("happy", "{name}~"), ("excited", "빨리 가자!")],
]
NO_RESULT = [
    [("sulky", "못 정했어…")],
    [("sulky", "다들 패스…"), ("sulky", "다음엔 꼭…")],
    [("trill", "흐음…"), ("sulky", "아무 데도 안 골랐어…")],
]


def recommend_script(meal: str, picks: list, latest: str | None = None, today_lunch: str | None = None,
                     rng=None) -> Script:
    """추천 메시지의 우사기 소리와 번역. 저녁 술집 자리, 오늘 점심 뺀 것, 지난번 간 곳을 가끔 한 토막씩 짚습니다."""
    rng = rng or random
    table = RECOMMEND[meal]
    facts = []
    if any(p.get("category") == config.DRINK_CATEGORY for p in picks):
        facts.append(FACTS["drink"])
    if today_lunch:
        facts.append(FACTS["today_lunch"])
    elif latest:
        facts.append(FACTS["latest"])
    middle = []
    if facts and rng.random() < 0.7:
        middle.append(rng.choice(rng.choice(facts)))
    if rng.random() < 0.4:
        middle.append(rng.choice(table["more"]))
    beats = [rng.choice(table["open"]), *middle, rng.choice(table["close"])]
    return speak([(mood, chunk.format(latest=latest)) for mood, chunk in beats], rng)


def result_script(winner: str | None, rng=None) -> Script:
    """투표 결과 메시지의 우사기 소리와 번역. winner 는 정해진 식당 이름 (없으면 선택 없이 끝남)."""
    rng = rng or random
    beats = rng.choice(RESULT if winner else NO_RESULT)
    return speak([(mood, chunk.format(name=winner)) for mood, chunk in beats], rng)


# ── 우사기 명령의 결과와 까닭 (키는 members.check 의 까닭과 명령 결과). 토막은 우사기가 하려던 말 ──
NOTICES = {
    "rank_low": [[("puzzled", "응?"), ("sulky", "{need}부터야…"), ("sulky", "{now}")],
                 [("sulky", "안 돼…"), ("sulky", "{need}부터야…"), ("sulky", "{now}")]],
    "bot": [[("puzzled", "봇?"), ("sulky", "봇은 안 돼…")]],
    "self": [[("puzzled", "자기 자신?"), ("sulky", "그건 안 돼…")]],
    "already": [[("puzzled", "{target}?"), ("happy", "벌써 {target_rank}~")]],
    "owner": [[("puzzled", "서버 주인?"), ("sulky", "건드리면 안 돼…")]],
    "not_member": [[("puzzled", "{target}?"), ("sulky", "아직 멤버 아니야…"), ("happy", "먼저 `/멤버추가`~")]],
    "not_lower": [[("puzzled", "응?"), ("sulky", "더 낮은 등급만 돼…"), ("sulky", "{target} {target_rank}…")]],
    "not_up": [[("puzzled", "응?"), ("sulky", "벌써 {target_rank}야…")]],
    "not_down": [[("puzzled", "응?"), ("sulky", "지금 {target_rank}인데…")]],
    "rank_too_high": [[("puzzled", "응?"), ("sulky", "{rank}까지만 돼…")]],
    "bad_rank": [[("puzzled", "그런 등급?"), ("sulky", "없어…")]],
    "added": [[("excited", "{target}!"), ("happy", "이제 행인 갑옷씨~")],
              [("happy", "환영해~"), ("excited", "{target} 행인 갑옷씨!")]],
    "promoted": [[("excited", "축하해!"), ("happy", "{target} {new}~")],
                 [("excited", "{target}!"), ("excited", "{new} 승급!")]],
    "demoted": [[("sulky", "{target}…"), ("sulky", "{new}로…")], [("sulky", "힝…"), ("sulky", "{target} {new}…")]],
    "removed": [[("sulky", "{target}…"), ("sulky", "멤버에서 빠졌어…")], [("sulky", "잘 가…"), ("sulky", "{target}…")]],
    "kicked": [[("우라!", "{target} 나가!")]],
    "kick_failed": [[("puzzled", "어?"), ("sulky", "{target} 못 내보냈어…"),
                     ("sulky", "'멤버 추방하기' 권한이나 역할 문제…")]],
    "kick_gone": [[("puzzled", "{target}?"), ("sulky", "벌써 없어…")]],
    "translate_on": [[("excited", "하치와레!"), ("happy", "번역 부탁해~")]],
    "translate_on_already": [[("puzzled", "응?"), ("happy", "이미 하고 있어~")]],
    "translate_off": [[("sulky", "하치와레…"), ("sulky", "잠깐 쉬어…")]],
    "translate_off_already": [[("puzzled", "응?"), ("sulky", "이미 쉬고 있어…")]],
    "recommend": [[("excited", "{meal} 추천!"), ("happy", "{channel}에 보낼게~")],
                  [("excited", "{channel}!"), ("happy", "{meal} 추천 갈게~")]],
    "recommend_failed": [[("puzzled", "어?"), ("sulky", "{meal} 추천 못 보냈어…"), ("sulky", "다시 해 줘…")]],
    "no_channel": [[("puzzled", "{meal} 채널?"), ("sulky", "`{setting}` 비었어…")]],
    "unknown": [[("puzzled", "응?"), ("puzzled", "그게 뭐야?")]],
    "menu_on": [[("excited", "채널이랑 메뉴도!"), ("happy", "하치와레가 번역~")]],
    "menu_on_already": [[("puzzled", "응?"), ("happy", "채널 번역 이미 하고 있어~")]],
    "menu_off": [[("sulky", "채널 번역…"), ("sulky", "잠깐 쉬어…")]],
    "menu_off_already": [[("puzzled", "응?"), ("sulky", "채널 번역 이미 쉬고 있어…")]],
    # 이미지 랜덤 주제 게임 (게임 안에서는 번역 설정과 상관없이 늘 하치와레가 번역)
    "game_setup": [[("excited", "게임!"), ("happy", "주제는 {topic}~"), ("excited", "같이 할 사람!")]],
    "game_round": [[("excited", "{round}라운드!"), ("happy", "술래는 {it}~"), ("excited", "사회자는 {host}!")]],
    "game_all_in": [[("excited", "{host}!"), ("happy", "답 다 모였어~")]],
    "game_answered": [[("happy", "받았어~"), ("excited", "비밀이야!")]],
    "game_reveal": [[("puzzled", "쉿?"), ("happy", "사회자만 보는 답~")]],
    "game_score": [[("excited", "{it} {n}개!"), ("happy", "점수 올라간다~")]],
    "game_scoreboard": [[("happy", "지금 점수~"), ("excited", "힘내!")]],
    "game_end": [[("excited", "게임 끝!"), ("happy", "1등은 {winner}~")]],
    "game_cancel": [[("sulky", "게임…"), ("sulky", "그만할래…")]],
    "game_not_running": [[("puzzled", "응?"), ("sulky", "하는 게임이 없어…")]],
    "game_already": [[("puzzled", "응?"), ("sulky", "벌써 게임 중이야…")]],
    "game_not_starter": [[("puzzled", "응?"), ("sulky", "시작한 사람만 돼…")]],
    "game_too_few": [[("puzzled", "응?"), ("sulky", "셋은 있어야 해…")]],
    "game_not_player": [[("puzzled", "응?"), ("sulky", "참가자만 돼…")]],
    "game_is_it": [[("puzzled", "응?"), ("sulky", "술래는 답 안 내…")]],
    "game_not_host": [[("puzzled", "응?"), ("sulky", "사회자만 돼…")]],
    "game_bad_count": [[("puzzled", "응?"), ("sulky", "답보다 많이는 못 맞혀…")]],
    # 생일 (선택)
    "bday_saved": [[("excited", "{date}!"), ("happy", "기억할게~")]],
    "bday_bad": [[("puzzled", "응?"), ("sulky", "그런 날짜는 없어…")]],
    "bday_removed": [[("sulky", "생일…"), ("sulky", "지웠어…")]],
    "bday_none": [[("puzzled", "응?"), ("sulky", "적힌 생일이 없어…")]],
    # 1:1 대화 기억 (/기억, 나만 보기)
    "memory_shown": [[("happy", "이만큼~"), ("excited", "기억하고 있어!")]],
    "memory_none": [[("puzzled", "응?"), ("sulky", "아직 기억한 게 없어…")]],
    "memory_forgot": [[("sulky", "기억…"), ("sulky", "다 지웠어…")]],
    "memory_forgot_one": [[("happy", "{n}번!"), ("sulky", "잊어버렸어…")]],
    "memory_bad_number": [[("puzzled", "응?"), ("sulky", "그런 번호는 없어…")]],
    "memory_locked": [[("puzzled", "응?"), ("sulky", "기억 상자를 열 수 없어…")]],
    # /리마인드 (나만 보기)
    "remind_saved": [[("excited", "{date}!"), ("happy", "그때 알려 줄게~")]],
    "remind_past": [[("puzzled", "응?"), ("sulky", "이미 지난 시각이야…")]],
    "remind_bad_date": [[("puzzled", "응?"), ("sulky", "그런 날짜는 없어…")]],
    "remind_empty": [[("puzzled", "응?"), ("sulky", "뭘 알려 줄까…?")]],
    "remind_too_many": [[("puzzled", "응?"), ("sulky", "벌써 {n}개야… 하나 지워 줘…")]],
    "remind_none": [[("puzzled", "응?"), ("sulky", "걸어 둔 게 없어…")]],
    "remind_list": [[("happy", "이만큼~"), ("excited", "걸어 뒀어!")]],
    "remind_cancelled": [[("happy", "{n}번!"), ("sulky", "지웠어…")]],
    "remind_bad_number": [[("puzzled", "응?"), ("sulky", "그런 번호는 없어…")]],
    "remind_locked": [[("puzzled", "응?"), ("sulky", "알림 상자를 열 수 없어…")]],
    "remind_all_saved": [[("excited", "{date}!"), ("happy", "다 같이 알려 줄게~")]],
    "remind_not_yours": [[("puzzled", "응?"), ("sulky", "건 사람이나 대장만 지울 수 있어…")]],
    "usagi_thread": [[("excited", "{thread}!"), ("happy", "거기서 기다릴게~")],
                     [("happy", "둘이서 놀자~"), ("excited", "{thread}로 와!")]],
    "thread_failed": [[("puzzled", "어?"), ("sulky", "스레드를 못 만들었어…"), ("sulky", "'비공개 스레드 만들기' 권한 문제…")]],
    "no_usagi_channel": [[("puzzled", "우사기 채널?"), ("sulky", "`USAGI_CHANNEL_ID` 비었어…")]],
}
# /우사기 1:1 스레드에서 우사기가 건네는 인사
GREETS = [
    [("excited", "왔구나!"), ("happy", "여기선 둘이서만~")],
    [("happy", "안녕~"), ("excited", "뭐든 말해 줘!")],
    [("excited", "야호!"), ("happy", "우리만의 방~")],
    [("happy", "기다렸어~"), ("excited", "놀자!")],
]


# 생일 축하: 정해 둔 우사기 소리와 하치와레 번역 한 세트 (늘 같이 보냄)
BIRTHDAY = Script((("와앗!", "생일 축하해!"), ("야하~", "오늘은 주인공~"), ("우라!", "맛있는 거 먹자!")))
BIRTHDAY_LINE = f'"{BIRTHDAY.text}"래!'  # 하치와레 번역도 정해 둔 한 줄
# 새로 들어온 사람 환영: 하치와레가 우사기 말을 옮긴 뒤 따옴표 밖에서 생일 안내를 해 줌 (버튼은 우사기 메시지에)
WELCOMES = [[("excited", "어서 와!"), ("happy", "반가워~")], [("happy", "안녕~"), ("excited", "환영해!")]]
WELCOME_GUIDE = "생일은 선택이야! 위 버튼으로 알려 주면 생일 아침 9시에 여기서 축하 알림을 보내 줄게~"


def birthday_script() -> Script:
    return BIRTHDAY


def welcome_script(rng=None) -> Script:
    rng = rng or random
    return speak(rng.choice(WELCOMES), rng)


def welcome_line(script: Script, rng=None) -> str:
    return f"{relay(script.text, rng)} {WELCOME_GUIDE}"


def greet_script(rng=None) -> Script:
    rng = rng or random
    return speak(rng.choice(GREETS), rng)


def notice_script(key: str, rng=None, **kw) -> Script:
    """명령의 결과·까닭을 우사기 소리와 번역으로."""
    rng = rng or random
    return speak([(mood, chunk.format(**kw)) for mood, chunk in rng.choice(NOTICES[key])], rng)


def rank_now(level: int) -> str:
    return f"지금은 **{members.RANKS[level]}**야." if level else "아직 멤버가 아니야."  # 등급 이름은 받침 없는 '씨' 로 끝남


def help_text(actor: str, level: int, usage: dict, mine: bool, menu: bool) -> str:
    """/도움: 그 사람이 쓸 수 있는 명령과 사용법. usage 는 {명령: (사용법, 뜻)}."""
    lines = [f"{actor}, {rank_now(level)} 쓸 수 있는 우사기 명령은 이거야."]
    lines += [f"- `{usage[c][0]}` {usage[c][1]}" for c in members.allowed(level)]
    ladder = " → ".join(members.RANKS.values())
    lines.append(f"-# 등급: {ladder}. 자기 등급과 그 아래 등급의 명령을 쓸 수 있어. "
                 f"1:1 스레드 번역은 {'켜져' if mine else '꺼져'} 있고, 채널 번역(메뉴 추천 포함)은 {'켜져' if menu else '꺼져'} 있어.")
    if not level:
        lines.append("-# 멤버가 되려면 멤버한테 `/멤버추가`를 부탁해!")
    return "\n".join(lines)


def is_on(user_id: str | None = None) -> bool:
    """번역이 켜져 있는지. user_id 를 주면 그 사람 설정(정하지 않았으면 서버 전체), 안 주면 서버 전체. 기본은 꺼짐."""
    if user_id is not None:
        mine = (storage.get_json(storage.HACHIWARE_PEOPLE_KEY) or {}).get(str(user_id))
        if mine is not None:
            return bool(mine.get("translate"))
    return bool((storage.get_json(storage.HACHIWARE_KEY) or {}).get("translate", False))


def turn(on: bool, by: str, user_id: str | None = None) -> bool:
    """번역을 켜거나 끕니다 (user_id 를 주면 그 사람만, 안 주면 서버 전체). 이미 그 상태였으면 False."""
    changed = is_on(user_id) != on
    record = {"translate": on, "by": by, "at": config.now_kst().isoformat()}
    if user_id is None:
        if changed:
            storage.put_json(storage.HACHIWARE_KEY, record)
        return changed
    people = storage.get_json(storage.HACHIWARE_PEOPLE_KEY) or {}
    people[str(user_id)] = record  # 서버 전체와 같아도 내 선택으로 남김 (나중에 서버 전체가 바뀌어도 그대로)
    storage.put_json(storage.HACHIWARE_PEOPLE_KEY, people)
    return changed


_hooks = None


def forget(user_id: str) -> bool:
    """그 사람의 개인 번역 설정을 지웁니다 (서버를 나간 사람). 없었으면 False."""
    people = storage.get_json(storage.HACHIWARE_PEOPLE_KEY) or {}
    if people.pop(str(user_id), None) is None:
        return False
    storage.put_json(storage.HACHIWARE_PEOPLE_KEY, people)
    return True


def hooks() -> dict:
    """{채널 ID: 하치와레 웹훅 주소}. 처음 한 번만 읽습니다 (웹훅을 바꾸면 서버를 다시 띄움)."""
    global _hooks
    if _hooks is None:
        _hooks = discord.channel_webhooks(config.HACHIWARE_WEBHOOK_URLS)
    return _hooks


def say(channel_id, text: str, thread: str | None = None, user_id: str | None = None) -> bool:
    """번역이 켜져 있으면 그 채널의 하치와레 웹훅으로 말합니다 (thread 를 주면 그 채널 아래 스레드에).

    user_id 를 주면 그 사람의 설정, 안 주면 서버 전체 설정을 봅니다. 꺼져 있거나 그 채널에 웹훅이 없으면 False.
    """
    hook = hooks().get(str(channel_id))
    if not hook or not is_on(user_id):
        return False
    discord.execute_webhook(f"{hook}?thread_id={thread}" if thread else hook, text)
    return True


