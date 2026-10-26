"""우사기 1:1 대화의 답: 봇이 실제로 아는 정보(오늘 추천·투표, 생일, 게임 점수, 등급, 시각)로 채웁니다.

답은 우사기 소리 + 하치와레 번역이고 소리 한 토막 = 번역 한 토막입니다 (hachiware.speak). 모르는 물음에는
아는 척하지 않고 되묻고, 가끔 우사기가 먼저 되물어서(asked) 다음 채팅을 그 답으로 읽게 합니다.
기억이 필요한 답(나에 대한 물음)은 그 사람의 기억(mem)이 있을 때만 합니다.
"""
import random
from dataclasses import dataclass
from datetime import date, datetime

from . import birthdays, chat, config, hachiware, meals, members, memory, storage, talk

# 답할 수 있는 (화제, 물음). "왜?"·"진짜?" 는 어느 화제든 짧게 받음 (supported)
SUPPORTED = {
    ("lunch", "what"), ("lunch", "where"), ("dinner", "what"), ("dinner", "where"), ("dinner", "when"),
    ("last", "what"), ("birthday", "when"), ("game", "what"), ("rank", "what"), ("time", "what"), ("off", "when"),
    ("usagi", "who"), ("usagi", "like"), ("usagi", "eat"), ("hachiware", "who"), ("me", "remember"), ("me", "like"),
    ("talk", "when"), ("bored", "what"), ("tired", "how"), ("food", "what"), ("place", "how"), ("place", "where"),
}
SHORT = ("why", "really")
OFF_HOUR = 18  # 퇴근·저녁 추천 시각 (평일)
ASK_BACK = 0.5  # 심심하거나 힘들다고 할 때 우사기가 "뭐 먹고 싶어?" 하고 되묻는 비율
RECALL_DAYS = 7  # 이보다 오래된 기분·음식은 꺼내지 않음
TAUGHT_CHUNKS = 4

MEMORY_GUIDE = ("알려 줄 게 있어! 우사기는 여기서 나눈 이야기 중 이것만 기억해: 마지막으로 이야기한 날, 기분, "
                "자주 하는 이야기, 좋아하거나 싫어한다고 한 것, 최근 이야기한 음식, 네가 가르쳐 준 것. "
                "대화 원문은 남기지 않고, 기억은 너만의 열쇠로 잠가서(암호화) 저장해. 서버를 나가거나 추방되면 다 지우고, "
                "/기억 보기·/기억 지우기로 언제든 보고 지울 수 있어.")


@dataclass
class Facts:
    picks: list  # 오늘 점심 추천 5곳
    winner: dict | None  # 오늘 투표로 정해진 점심
    dinner_picks: list
    dinner_winner: dict | None
    latest: dict | None  # 가장 최근에 정해진 점심 (날짜 상관없이)
    birthday: tuple | None
    score: int | None  # 우사기 채널 게임에서 이 사람 점수
    rank: int
    now: datetime


@dataclass
class Reply:
    script: hachiware.Script
    own: str = ""  # 하치와레가 따옴표 밖에서 하는 말
    target: str | None = None  # 방금 말한 식당 (다음 "거기")
    asked: str | None = None  # 우사기가 되물은 화제


def supported(topic: str | None, ask: str | None) -> bool:
    return (topic, ask) in SUPPORTED or (topic is not None and ask in SHORT)


def _today(meal: str, today: str):
    rec = storage.get_json(storage.recommendation_key(today, meal)) or {}
    latest = storage.get_json(storage.latest_key(meal))
    return rec.get("picks") or [], latest if latest and latest.get("date") == today else None, latest


def gather(guild_id: str, user_id: str, owner_id: str | None, now: datetime) -> Facts:
    today = now.date().isoformat()
    picks, winner, latest = _today(meals.LUNCH, today)
    dinner_picks, dinner_winner, _ = _today(meals.DINNER, today)
    game = storage.get_json(storage.game_key(config.USAGI_CHANNEL_ID)) or {}
    level = members.person(user_id, "", members.load(guild_id), owner_id).level
    return Facts(picks, winner, dinner_picks, dinner_winner, latest, birthdays.get(guild_id, user_id),
                 (game.get("scores") or {}).get(str(user_id)), level, now)


def _say(beats, rng, **kw) -> Reply:
    return Reply(hachiware.speak(beats, rng), **kw)


def _days_ago(day: str, today: date) -> int:
    return (today - date.fromisoformat(day)).days


def _when(days: int) -> str:
    return {0: "오늘", 1: "어제"}.get(days, f"{days}일 전")


def _at(days: int, also: bool = False) -> str:
    """'오늘도', '어제', '3일 전에' 처럼 뒤에 말을 바로 이을 수 있게 ('오늘에'·'어제에' 는 어색함)."""
    if days == 0:
        return "오늘도" if also else "오늘"
    if days == 1:
        return "어제도" if also else "어제"
    return f"{days}일 전에도" if also else f"{days}일 전에"


def _clock(now: datetime) -> str:
    h = now.hour % 12 or 12
    return f"{'오전' if now.hour < 12 else '오후'} {h}시 {now.minute}분"


def _meal(rng, winner, picks, meal: str) -> Reply:
    if winner:
        return _say([("excited", f"오늘 {meal}은 {winner['name']}!"), ("happy", "투표로 정해졌어~")], rng,
                    target=winner["name"])
    if picks:
        return _say([("happy", "아직 투표 중이야~"), ("excited", f"후보는 {len(picks)}곳!")], rng)
    if meal == "저녁":
        return _say([("happy", "저녁은 아직~"), ("excited", f"평일 {OFF_HOUR - 12}시에 추천 와!")], rng)
    return _say([("puzzled", "음…?"), ("happy", "아직 추천 전이야~")], rng)


def _place(facts: Facts, name: str | None):
    pool = facts.picks + facts.dinner_picks + [p for p in (facts.winner, facts.dinner_winner, facts.latest) if p]
    return next((p for p in pool if p.get("name") == name), None) if name else None


def answer(turn: talk.Turn, facts: Facts, mem: dict | None, ctx: talk.Context | None, rng) -> Reply:
    rng = rng or random
    topic, ask = turn.topic, turn.ask
    today = facts.now.date()
    if ask == "why":
        return _say([("puzzled", "왜냐면…"), ("happy", "그냥~")], rng)
    if ask == "really":
        return _say([("excited", "진짜!"), ("happy", "믿어 줘~")], rng)
    if topic == "lunch":
        return _meal(rng, facts.winner, facts.picks, "점심")
    if topic == "dinner" and ask == "when":
        if facts.now.weekday() >= 5:
            return _say([("happy", "주말엔~"), ("sulky", "저녁 추천도 쉬어…")], rng)
        return _say([("happy", "저녁 추천은~"), ("excited", f"평일 {OFF_HOUR - 12}시!")], rng)
    if topic == "dinner":
        return _meal(rng, facts.dinner_winner, facts.dinner_picks, "저녁")
    if topic == "last":
        if facts.latest:
            when = _at(_days_ago(facts.latest["date"], today)) if facts.latest.get("date") else "지난번엔"
            return _say([("happy", f"{when} {facts.latest['name']}!"), ("excited", "투표로 골랐어~")], rng,
                        target=facts.latest["name"])
        return _say([("puzzled", "음…?"), ("sulky", "아직 고른 데가 없어…")], rng)
    if topic == "birthday":
        if facts.birthday:
            return _say([("excited", f"{facts.birthday[0]}월 {facts.birthday[1]}일!"), ("happy", "기억하고 있어~")], rng)
        return _say([("puzzled", "생일?"), ("sulky", "아직 몰라…"), ("happy", "/생일 등록으로 알려 줘~")], rng)
    if topic == "game":
        if facts.score is not None:
            return _say([("excited", f"지금 {facts.score}점!"), ("happy", "힘내~")], rng)
        return _say([("puzzled", "게임?"), ("sulky", "지금은 안 하고 있어…")], rng)
    if topic == "rank":
        if facts.rank:
            return _say([("happy", f"{members.RANKS[facts.rank]}!"), ("excited", "멋져~")], rng)
        return _say([("puzzled", "등급?"), ("sulky", "아직 멤버가 아니야…")], rng)
    if topic == "time":
        return _say([("happy", "지금은~"), ("excited", f"{_clock(facts.now)}!")], rng)
    if topic == "off":
        return _off(facts.now, rng)
    if topic == "usagi":
        beats = {"who": [[("excited", "나 우사기!"), ("happy", "반가워~")]],
                 "like": [[("excited", "맛있는 거!"), ("happy", "다 좋아~")], [("happy", "너랑 노는 거~"), ("excited", "최고!")]],
                 "eat": [[("happy", "먹었어~"), ("excited", "배불러!")], [("sulky", "아직…"), ("excited", "같이 먹자!")]]}
        return _say(rng.choice(beats[ask]), rng)
    if topic == "hachiware":
        return _say([("happy", "하치와레?"), ("excited", "내 친구!"), ("happy", "말 옮겨 줘~")], rng)
    if topic in ("me", "talk"):
        return _me(topic, ask, mem, today, rng)
    if topic == "bored":
        if rng.random() < ASK_BACK:
            return _say([("puzzled", "심심해?"), ("happy", "뭐 먹고 싶어?")], rng, asked="food")
        return _say([("excited", "게임 하자!"), ("happy", "/게임 시작~")], rng)
    if topic == "tired":
        if rng.random() < ASK_BACK:
            return _say([("sulky", "힘들었구나…"), ("puzzled", "뭐 먹고 싶어?")], rng, asked="food")
        return _say([("sulky", "토닥토닥…"), ("happy", "맛있는 거 먹자~")], rng)
    if topic == "food":
        if facts.picks:
            pick = rng.choice(facts.picks)
            return _say([("excited", f"{pick['name']}!"), ("happy", "오늘 추천 중에~")], rng, target=pick["name"])
        return _say([("excited", f"{rng.choice(memory.FOOD_WORDS[:12])}!"), ("happy", "어때~?")], rng)
    if topic == "place":
        place = _place(facts, ctx.target if ctx else None)
        if not place:
            return _say([("puzzled", "거기?"), ("sulky", "어디 말하는 거야…?")], rng)
        if ask == "where":
            far = f"{place['distance_m']}m 거리~" if place.get("distance_m") is not None else "가까워~"
            return _say([("happy", f"{place['name']}!"), ("excited", far)], rng, target=place["name"])
        return _say([("excited", f"{place['name']}?"), ("happy", "맛있대!")], rng, target=place["name"])
    return unknown(False, rng)


def _off(now: datetime, rng) -> Reply:
    if now.weekday() >= 5:
        return _say([("happy", "오늘은~"), ("excited", "쉬는 날이야!")], rng)
    left = OFF_HOUR * 60 - (now.hour * 60 + now.minute)
    if left <= 0:
        return _say([("excited", "벌써!"), ("happy", "퇴근 시간이야~")], rng)
    hours, minutes = divmod(left, 60)
    span = f"{hours}시간 {minutes}분" if hours and minutes else f"{hours}시간" if hours else f"{minutes}분"
    return _say([("sulky", "퇴근까지…"), ("happy", f"{span} 남았어~")], rng)


def _me(topic: str, ask: str, mem: dict | None, today: date, rng) -> Reply:
    if mem is None:  # 기억을 쓰지 못하는 사람 (번역 꺼짐, 남의 스레드)
        return _say([("puzzled", "음…?"), ("sulky", "잘 모르겠어…")], rng)
    seen = mem.get("last_seen")
    if topic == "talk":
        if not seen:
            return _say([("excited", "오늘이 처음이야!"), ("happy", "반가워~")], rng)
        return _say([("happy", f"{_at(_days_ago(seen, today))} 얘기했어~")], rng)
    if ask == "like":
        if mem["likes"]:
            return _say([("happy", f"{', '.join(mem['likes'][-2:])}!"), ("excited", "좋아한댔지~")], rng)
        return _say([("puzzled", "음…?"), ("sulky", "아직 못 들었어…")], rng)
    if seen:
        return _say([("excited", "당연하지!"), ("happy", f"{_at(_days_ago(seen, today), also=True)} 얘기했잖아~")], rng)
    return _say([("happy", "이제부터~"), ("excited", "기억할게!")], rng)


def unknown(teachable: bool, rng) -> Reply:
    return _say([("puzzled", "음…?"), ("sulky", "잘 모르겠어…")], rng, own="무슨 뜻인지 알려 줄래?" if teachable else "")


def learned(rng) -> Reply:
    return _say([("excited", "알았어!"), ("happy", "다음엔 그렇게 말할게~")], rng)


def guide(rng) -> Reply:
    """처음 안내: 우사기가 부르고, 하치와레가 무엇을 어떻게 기억하는지 알려 줌."""
    return _say([("excited", "잠깐!"), ("happy", "알려 줄 게 있어~")], rng, own=MEMORY_GUIDE)


def reply_to(turn: talk.Turn, rng) -> Reply:
    """우사기가 되물은 것에 대한 답 ("뭐 먹고 싶어?" → "라멘")."""
    food = next((f for f in memory.FOOD_WORDS if any(w.startswith(f) for w in turn.words)), None)
    if food:
        return _say([("excited", f"{food} 좋다!"), ("happy", "같이 먹자~")], rng, target=food)
    return _say([("happy", "그렇구나~"), ("excited", "좋아!")], rng)


def taught_answer(text: str, rng) -> Reply:
    """그 사람이 알려 준 답 문장을 하치와레가 그대로 옮김 (100자, 1~4 토막)."""
    tokens = chat._clean(text[: talk.ANSWER_CHARS]).split() or ["…"]
    size = -(-len(tokens) // TAUGHT_CHUNKS)  # 올림
    chunks = [" ".join(tokens[i:i + size]) for i in range(0, len(tokens), size)]
    return _say([("happy", c) for c in chunks], rng)


def recall(mem: dict, reading: chat.Reading, today: date) -> str | None:
    """인사에 덧붙이는 기억 한마디 (7일 안의 것만)."""
    if reading.kind != "greet" or not mem.get("last_seen"):
        return None
    gap = _days_ago(mem["last_seen"], today)
    if gap >= 2:
        return f"{gap}일 만이네!"
    recent = [(d, f) for d, f in mem["foods"] if _days_ago(d, today) <= RECALL_DAYS]
    if recent:
        day, food = recent[-1]
        return f"{_when(_days_ago(day, today))} {food} 먹었어?"
    if any(k in ("sad", "angry") and _days_ago(d, today) <= RECALL_DAYS for d, k in mem["moods"]):
        return "오늘은 좀 괜찮아?"
    return None
