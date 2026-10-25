"""디스코드에 보이는 문구 모음.

우사기(먼작귀)는 말을 하지 않으므로 우사기 몫은 소리만 냅니다. 이모티콘은 쓰지 않습니다.
소리는 상황별 '모양'(한 번 외치기, 같은 소리 두 번, 물결로 늘이기, 떨림 소리 뒤에 외치기 …)을
비중에 따라 하나 고르고, 그 안을 소리 조각으로 채워서 매번 다르게 냅니다. '!!' 는 가끔만 씁니다.
식당 이름, 메뉴, 거리, 날짜와 작은 글씨 정보 줄은 화면 표시라 그대로 적습니다.
"""
import random

# 우사기 소리 조각 (끝맺음 없이)
EXCITED = ("우라", "야하", "야앗", "이얏", "와앗")  # 추천할 때
HAPPY = ("야하", "우라", "와앗")  # 누가 식당을 골랐을 때
SULKY = ("후웅", "흐응")  # 패스
PUZZLED = ("하아", "후웅", "하")  # 모르는 버튼, 식당을 못 찾음 (누른 사람에게만 보임)

# 소리의 모양과 뽑힐 비중. {a} {b} 는 서로 다른 조각, {t} 는 길이가 바뀌는 떨림 소리(푸르르르…)
RECOMMEND_SHAPES = (
    (3, "{a}!"),
    (2, "{a} {a}"),
    (2, "{a}~"),
    (2, "{a}! {b}~"),
    (1, "{a}… {b}!"),
    (1, "{t}… {a}!"),
    (1, "{a} {a}!!"),
)
PICKED_SHAPES = (
    (3, "{a}!"),
    (2, "{a}~"),
    (2, "{a} {a}!"),
    (1, "{a}! {b}~"),
    (1, "{a}!!"),
)
SKIPPED_SHAPES = (
    (3, "{a}…"),
    (2, "{t}…"),
    (1, "{a}… {t}"),
    (1, "{a}"),
)
HUH_SHAPES = (
    (3, "{a}?"),
    (1, "{a}…?"),
)


def trill(rng) -> str:
    return "푸르르르" + "르" * rng.randint(0, 2)


def _sound(shapes, pool, rng) -> str:
    shape = rng.choices([s for _, s in shapes], weights=[w for w, _ in shapes])[0]
    a, b = rng.sample(pool, 2)
    return shape.format(a=a, b=b, t=trill(rng))


def recommend_sound(rng=random) -> str:
    return _sound(RECOMMEND_SHAPES, EXCITED, rng)


def picked_sound(rng=random) -> str:
    return _sound(PICKED_SHAPES, HAPPY, rng)


def skipped_sound(rng=random) -> str:
    return _sound(SKIPPED_SHAPES, SULKY, rng)


def huh_sound(rng=random) -> str:
    return _sound(HUH_SHAPES, PUZZLED, rng)


# 토막 하나에 낼 소리: 기분 → (소리 조각, 끝맺음 비중). 하치와레 번역 토막과 짝을 이룰 때 씁니다 (hachiware.speak)
MOODS = {
    "excited": (EXCITED, {"!": 6, "~": 2}),
    "happy": (HAPPY, {"~": 5, "!": 3}),
    "sulky": (SULKY, {"…": 5, "~": 2}),
    "puzzled": (PUZZLED, {"?": 5, "…?": 2}),
    "trill": (("푸르르",), {"…": 3, "~": 3}),
}


def mood_sound(mood: str, end: str | None = None, rng=random, avoid: str | None = None) -> str:
    """기분에 맞는 소리 한 토막. end 를 주면 그 끝맺음으로 냅니다 (짝이 되는 번역 토막과 맞춤).

    avoid 와 같은 소리는 되도록 피합니다 (바로 앞 토막과 겹치지 않게).
    """
    pool, ends = MOODS[mood]
    base = rng.choice([b for b in pool if b != avoid] or pool)
    word = trill(rng) if base == "푸르르" else base
    end = end if end is not None else rng.choices(list(ends), weights=list(ends.values()))[0]
    return word + (end or ("?" if word == "하" else ""))  # '하' 만 덩그러니 두지 않음


# 작은 글씨 정보 줄과 버튼
NO_LATEST = "지난번 없음"
SKIP_LABEL = "패스"
END_LABEL = "투표 종료"


def latest(name: str, short_date: str) -> str:
    return f"지난번 {name} ({short_date})"


def today_lunch(name) -> str:
    """저녁 메시지 정보 줄: 오늘 점심으로 정해진 식당 (아직 없으면 없음)."""
    return f"오늘 점심 {name}" if name else "오늘 점심 없음"


def vote_progress(voted: int, expected) -> str:
    """정원을 알면 '투표 3/7', 모르면 '투표 3명' (투표 종료 버튼으로만 끝남)."""
    return f"투표 {voted}/{expected}" if expected else f"투표 {voted}명"


def voters_line(names) -> str:
    return f"{len(names)}표 · {', '.join(names)}"


def pass_line(names) -> str:
    return f"패스 {len(names)}표 · {', '.join(names)}"


def vote_summary(tally, voted: int, expected) -> str:
    """tally: [(식당 이름 또는 '패스', 표 수), …] 많은 순."""
    if not voted:
        return "투표 끝 · 아무도 투표하지 않음"
    counts = " · ".join(f"{label} {n}" for label, n in tally)
    who = f"{expected}명 중 {voted}명 투표" if expected else f"{voted}명 투표"
    return f"투표 끝 · {counts} · {who}"
