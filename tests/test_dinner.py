"""저녁 추천 (오저뭐): 점심과 같은 투표 방식이지만, 식사 4곳 + 술집 1곳, 오늘 점심 식당은 빼고, 따로 저장한다."""
from types import SimpleNamespace

import pytest

from lunchbot import config, meals, storage
import recommend
from test_flow import aws, buttons, header, texts, walk  # noqa: F401 (aws 는 fixture)
from test_voting import press

CONTAINER = 17


def r(id, category, detail=None):
    return {"id": id, "name": f"식당{id}", "category": category, "category_detail": detail or category,
            "lat": config.CENTER_LAT, "lng": config.CENTER_LNG, "distance_m": 100, "kakao_url": ""}


@pytest.fixture
def dinner(aws, monkeypatch):
    """저녁 채널 77, 저녁 정원 2명, 점심 정원 1명."""
    monkeypatch.setattr(config, "DINNER_CHANNEL_ID", "77")
    monkeypatch.setattr(config, "DINNER_VOTER_COUNT", 2)
    monkeypatch.setattr(config, "VOTER_COUNT", 1)
    calls = []
    monkeypatch.setattr(
        recommend.discord, "send_message",
        lambda token, channel_id, payload: aws.append(payload) or calls.append(channel_id) or {"id": f"m{len(aws)}"},
    )
    return SimpleNamespace(sent=aws, channels=calls, date=config.today_kst())


def accent(payload):
    return next(c["accent_color"] for c in walk(payload["components"]) if c["type"] == CONTAINER)


def test_dinner_goes_to_dinner_channel_with_four_meals_and_one_bar(dinner):
    recommend.handler({"meal": "dinner"}, None)
    assert dinner.channels == ["77"]
    picks = storage.get_json(storage.recommendation_key(dinner.date, "dinner"))["picks"]
    assert len(picks) == 5
    assert [p["category"] == "술집" for p in picks] == [False, False, False, False, True]  # 술집은 마지막 한 자리
    assert storage.get_json(storage.recommendation_key(dinner.date)) is None  # 점심 기록과 따로


def test_dinner_message_looks_different_from_lunch(dinner):
    recommend.handler({}, None)
    recommend.handler({"meal": "dinner"}, None)
    lunch_msg, dinner_msg = dinner.sent[-2], dinner.sent[-1]
    assert accent(dinner_msg) == meals.get("dinner").accent != accent(lunch_msg)
    assert "저녁" in header(dinner_msg) and "저녁" not in header(lunch_msg)
    assert "오늘 점심 없음" in header(dinner_msg)  # 점심 투표가 아직 안 끝났다


def test_dinner_skips_todays_lunch_pick_and_shows_it(dinner, monkeypatch):
    # 고르는 순서를 고정: 후보 목록의 앞에서부터 뽑는다
    monkeypatch.setattr(recommend, "random", SimpleNamespace(sample=lambda pop, k: list(pop)[:k]))
    recommend.handler({}, None)  # 점심 (m1, 정원 1명)
    lunch_first = storage.get_json(storage.recommendation_key(dinner.date))["picks"][0]
    press(f"pick:{dinner.date}:{lunch_first['id']}", "u1", "민지", message_id="m1")  # 점심 결정
    recommend.handler({"meal": "dinner"}, None)
    dinner_ids = {p["id"] for p in storage.get_json(storage.recommendation_key(dinner.date, "dinner"))["picks"]}
    assert lunch_first["id"] not in dinner_ids
    assert f"오늘 점심 {lunch_first['name']}" in header(dinner.sent[-1])


def test_dinner_vote_is_saved_apart_from_lunch(dinner):
    recommend.handler({"meal": "dinner"}, None)  # m1, 저녁 정원 2명
    picks = storage.get_json(storage.recommendation_key(dinner.date, "dinner"))["picks"]
    body = press(f"pick:{dinner.date}:{picks[4]['id']}", "u1", "민지")
    # 아직 진행 중인 저녁 투표 메시지도 저녁 모양을 유지한다
    assert buttons(body["data"], "pick:") and "저녁" in header(body["data"])
    assert accent(body["data"]) == meals.get("dinner").accent
    body = press(f"pick:{dinner.date}:{picks[4]['id']}", "u2", "현우")
    assert buttons(body["data"]) == [] and accent(body["data"]) == meals.get("dinner").accent
    assert storage.get_json(storage.latest_key("dinner"))["id"] == picks[4]["id"]
    assert storage.get_json(storage.selection_key(picks[4]["category"], dinner.date, "dinner"))["id"] == picks[4]["id"]
    assert storage.get_json(storage.LATEST_KEY) is None  # 점심 '지난번'에는 섞이지 않는다


def test_dinner_needs_its_channel(dinner, monkeypatch):
    monkeypatch.setattr(config, "DINNER_CHANNEL_ID", "")
    with pytest.raises(RuntimeError, match="DINNER_CHANNEL_ID"):
        recommend.handler({"meal": "dinner"}, None)


def test_choose_picks_per_meal():
    pool = [r(f"k{i}", "한식") for i in range(6)] + [r("cake", "간식"), r("cafeteria", "구내식당")]
    pool += [r("bar1", "술집", "술집 > 일본식주점"), r("bar2", "술집", "술집 > 호프,요리주점")]
    for seed in range(30):
        dinner = recommend.choose_picks(pool, meals.get("dinner"), avoid_ids={"k0"}, rng=__import__("random").Random(seed))
        cats = [p["category"] for p in dinner]
        assert cats[:4] == ["한식"] * 4 and cats[4] == "술집"  # 디저트·구내식당·오늘 점심(k0) 없이
        assert "k0" not in {p["id"] for p in dinner}
        lunch = recommend.choose_picks(pool, meals.get("lunch"), avoid_ids=set(), rng=__import__("random").Random(seed))
        assert not {"술집", "간식"} & {p["category"] for p in lunch}


def test_dinner_without_bars_uses_five_meals():
    pool = [r(f"k{i}", "한식") for i in range(6)]
    picks = recommend.choose_picks(pool, meals.get("dinner"), avoid_ids=set(), rng=__import__("random").Random(1))
    assert len(picks) == 5 and all(p["category"] == "한식" for p in picks)
