import importlib
import json
import random
import re
import time
import unicodedata
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from conftest import SIGNING_KEY
from lunchbot import config, discord, kakao, messages, storage
import interaction
import recommend

CATS = ["한식 > 국밥", "중식 > 중국요리", "일식 > 초밥,롤", "양식 > 이탈리안", "분식", "술집 > 호프,요리주점"]
V2 = 1 << 15  # IS_COMPONENTS_V2
ROW, BUTTON, TEXT, THUMBNAIL, SEPARATOR = 1, 2, 10, 11, 14


def make_places(n=900, seed=1):
    rnd = random.Random(seed)
    x1, y1, x2, y2 = kakao.bounding_rect(config.CENTER_LAT, config.CENTER_LNG, 1300)
    places = []
    for i in range(n):
        places.append(
            {
                "id": str(i),
                "place_name": f"식당{i}",
                "category_name": f"음식점 > {rnd.choice(CATS)}",
                "x": str(rnd.uniform(x1, x2)),
                "y": str(rnd.uniform(y1, y2)),
                "road_address_name": "서울 강남구",
                "place_url": f"http://place.map.kakao.com/{i}",
            }
        )
    return places


class FakeKakao:
    """rect 안의 장소만, 최대 45개까지만 돌려주는 카카오 API 흉내."""

    def __init__(self, places):
        self.places = places
        self.calls = 0

    def __call__(self, api_key, params):
        self.calls += 1
        x1, y1, x2, y2 = map(float, params["rect"].split(","))
        hits = [p for p in self.places if x1 <= float(p["x"]) < x2 and y1 <= float(p["y"]) < y2]
        pageable = hits[:45]
        page, size = params["page"], params["size"]
        docs = pageable[(page - 1) * size : page * size]
        return {
            "meta": {"total_count": len(hits), "pageable_count": len(pageable), "is_end": page * size >= len(pageable)},
            "documents": docs,
        }


def walk(components):
    """컴포넌트 V2 트리를 펼쳐서 모든 컴포넌트를 차례로 돌려준다."""
    for c in components:
        yield c
        yield from walk(c.get("components", []))
        if "accessory" in c:
            yield c["accessory"]


def texts(payload):
    return "\n".join(c["content"] for c in walk(payload["components"]) if c["type"] == TEXT)


def header(payload):
    """맨 위 글자 블록: 우사기 소리 + 작은 글씨 정보 줄."""
    return next(c["content"] for c in walk(payload["components"]) if c["type"] == TEXT)


def made_of(payload, pool, trill=False):
    """맨 위 줄이 우사기 소리 조각(과 떨림 소리)으로만 이루어졌는지. 예: '우라! 야하~' -> 우라, 야하"""
    ws = [p.strip("!?…~") for p in header(payload).split("\n")[0].split(" ")]
    return bool(ws) and all(w in pool or (trill and re.fullmatch("푸르{3,}", w)) for w in ws)


def buttons(payload, prefix=""):
    return [c for c in walk(payload["components"]) if c["type"] == BUTTON and c["custom_id"].startswith(prefix)]


def thumbnails(payload):
    return [c["media"]["url"] for c in walk(payload["components"]) if c["type"] == THUMBNAIL]


def fake_photo(place_url):
    return f"https://img.test/{place_url.rsplit('/', 1)[-1]}.jpg"


def test_collect_finds_every_place_in_radius():
    places = make_places()
    fake = FakeKakao(places)
    got = kakao.collect_restaurants("k", config.CENTER_LAT, config.CENTER_LNG, 1000, exclude={"술집"}, fetch=fake, delay=0)
    expected = {
        p["id"]
        for p in places
        if kakao.haversine_m(config.CENTER_LAT, config.CENTER_LNG, float(p["y"]), float(p["x"])) <= 1000
        and "술집" not in p["category_name"]
    }
    assert {r["id"] for r in got} == expected
    assert all(r["distance_m"] <= 1000 for r in got)
    assert {r["category"] for r in got} == {"한식", "중식", "일식", "양식", "분식"}
    print(f"\n장소 {len(expected)}곳, API 호출 {fake.calls}회")


def signed_event(payload: dict, tamper=False):
    body = json.dumps(payload)
    ts = str(int(time.time()))
    sig = SIGNING_KEY.sign(f"{ts}{body}".encode()).signature.hex()
    if tamper:
        body = body.replace("pick", "skip")
    return {"headers": {"X-Signature-Ed25519": sig, "X-Signature-Timestamp": ts}, "body": body, "isBase64Encoded": False}


def click(custom_id, message_id="m1", user_id="u-kim", name="김"):
    return {
        "type": 3,
        "data": {"custom_id": custom_id, "component_type": 2},
        "member": {"user": {"id": user_id, "username": "kim", "global_name": name}},
        "message": {"id": message_id},
    }


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        boto3.client("s3").create_bucket(
            Bucket="lunch-test", CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"}
        )
        storage._s3 = None
        sent = []
        fake = FakeKakao(make_places())
        monkeypatch.setattr(kakao, "http_fetch", fake)
        monkeypatch.setattr(recommend.kakao, "http_fetch", fake)
        monkeypatch.setattr(kakao.time, "sleep", lambda s: None)
        # 카카오 장소 페이지에서 대표 사진을 가져오는 대신 장소 id 로 만든 가짜 주소를 쓴다
        monkeypatch.setattr(kakao, "place_photo", fake_photo)
        monkeypatch.setattr(
            recommend.discord, "send_message", lambda token, channel_id, payload: sent.append(payload) or {"id": f"m{len(sent)}"}
        )
        monkeypatch.setattr(recommend.discord, "channel_viewer_count", lambda token, channel_id: 3)
        # collect_restaurants 의 기본 fetch 인자는 정의 시점에 묶이므로 래핑
        orig = kakao.collect_restaurants
        monkeypatch.setattr(recommend.kakao, "collect_restaurants", lambda *a, **kw: orig(*a, fetch=fake, delay=0, **kw))
        yield sent


def test_full_flow(aws, monkeypatch):
    sent = aws
    monkeypatch.setattr(config, "VOTER_COUNT", 1)  # 한 명이 투표하면 끝나는 투표
    s3 = boto3.client("s3")
    date = config.today_kst()

    # 1) 첫 추천: 컴포넌트 V2 한 장짜리 목록, 최근 선택 없음
    out = recommend.handler({}, None)
    assert len(out["picks"]) == 5
    msg = sent[-1]
    assert msg["flags"] & V2 and "embeds" not in msg and "content" not in msg
    assert made_of(msg, messages.EXCITED + messages.SULKY + messages.PUZZLED, trill=True)  # 머리말은 우사기 소리만
    assert messages.NO_LATEST in header(msg)
    assert "map.naver.com/p/search/" in texts(msg)
    picks = storage.get_json(storage.recommendation_key(date))["picks"]
    assert [b["custom_id"] for b in buttons(msg, "pick:")] == [f"pick:{date}:{p['id']}" for p in picks]
    assert [b["custom_id"] for b in buttons(msg, "skip:")] == [f"skip:{date}"]
    # 각 식당 옆에 카카오 대표 사진 썸네일이 붙고, 추천 기록에도 사진 주소가 남는다
    assert thumbnails(msg) == [f"https://img.test/{p['id']}.jpg" for p in picks]
    assert [p["photo_url"] for p in picks] == [f"https://img.test/{p['id']}.jpg" for p in picks]
    assert storage.get_json(storage.CACHE_KEY)["count"] > 0

    # 2) 서명 검증
    assert interaction.handler(signed_event({"type": 1}), None)["body"] == json.dumps({"type": 1})
    assert interaction.handler(signed_event({"type": 1}) | {"body": '{"type": 1} '}, None)["statusCode"] == 401

    # 3) 2번 식당에 투표: 정원(1명)이 찼으니 바로 끝나고, 고른 식당 카드(사진 포함)만 남고,
    #    latest + selections/{카테고리}/{날짜} 에 저장
    res = interaction.handler(signed_event(click(buttons(msg, "pick:")[1]["custom_id"])), None)
    body = json.loads(res["body"])
    assert body["type"] == 7 and body["data"]["flags"] & V2 and buttons(body["data"]) == []
    assert made_of(body["data"], messages.EXCITED) and picks[1]["name"] in texts(body["data"])
    assert thumbnails(body["data"]) == [f"https://img.test/{picks[1]['id']}.jpg"]
    latest = storage.get_json(storage.LATEST_KEY)
    assert latest["id"] == picks[1]["id"] and latest["selected_by"] == "투표"
    cat_key = f"selections/{picks[1]['category']}/{date}.json"
    assert storage.get_json(cat_key)["id"] == picks[1]["id"]
    keys = sorted(o["Key"] for o in s3.list_objects_v2(Bucket="lunch-test")["Contents"])
    print("\nS3 keys:", keys)

    # 4) 다음 추천의 정보 줄에 최근 선택이 표시됨 (캐시 재사용)
    recommend.handler({}, None)
    assert picks[1]["name"] in header(sent[-1])


def test_recommendation_is_sent_by_bot_to_configured_channel(aws, monkeypatch):
    calls = []
    monkeypatch.setattr(recommend.discord, "send_message", lambda token, channel_id, payload: calls.append((token, channel_id)))
    recommend.handler({}, None)
    assert calls == [("test-bot-token", "42")]  # conftest 의 DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID


def test_rerun_same_day_keeps_earlier_buttons(aws, monkeypatch):
    sent = aws
    date = config.today_kst()
    monkeypatch.setattr(config, "VOTER_COUNT", 1)
    # 1차 추천은 목록의 앞 5곳, 2차 추천은 그다음 5곳이 뽑히도록 고정
    starts = iter([0, 5])

    def fixed_sample(population, k):
        i = next(starts)
        return population[i : i + k]

    monkeypatch.setattr(recommend, "random", SimpleNamespace(sample=fixed_sample))

    recommend.handler({}, None)
    first_msg = sent[-1]
    first_picks = storage.get_json(storage.recommendation_key(date))["picks"]

    # 같은 날 다시 보내면 recommendations/{날짜}.json 이 새 5곳으로 덮어써진다
    recommend.handler({}, None)
    second_ids = {p["id"] for p in storage.get_json(storage.recommendation_key(date))["picks"]}
    assert first_picks[1]["id"] not in second_ids

    # 1차 메시지(m1)의 2번 버튼은 여전히 1차 추천의 2번 식당을 저장해야 한다
    button = buttons(first_msg, "pick:")[1]
    res = interaction.handler(signed_event(click(button["custom_id"], message_id="m1")), None)
    assert json.loads(res["body"])["type"] == 7
    assert storage.get_json(storage.LATEST_KEY)["id"] == first_picks[1]["id"]


def test_unknown_place_gets_ephemeral_reply(aws):
    recommend.handler({}, None)
    date = config.today_kst()
    res = interaction.handler(signed_event(click(f"pick:{date}:no-such-place")), None)
    body = json.loads(res["body"])
    assert body["type"] == 4 and body["data"]["flags"] == 64
    assert body["data"]["content"].strip("!?…~") in messages.PUZZLED
    assert storage.get_json(storage.LATEST_KEY) is None


def test_pick_count_above_five_is_capped(aws, monkeypatch):
    # 버튼은 한 줄에 5개까지라, 6곳 이상 추천하면 고를 수 없는 식당이 생긴다
    monkeypatch.setenv("PICK_COUNT", "8")
    importlib.reload(config)
    try:
        out = recommend.handler({}, None)
    finally:
        monkeypatch.delenv("PICK_COUNT")
        importlib.reload(config)
    assert len(out["picks"]) == 5
    assert len(buttons(aws[-1], "pick:")) == 5


def test_tampered_body_rejected(aws):
    res = interaction.handler(signed_event(click("pick:2026-10-23:0"), tamper=True), None)
    assert res["statusCode"] == 401


def sample_picks():
    # 0번 식당은 사진을 못 가져온 경우
    return [
        {
            "id": str(i),
            "name": f"아주아주긴식당이름{i}" * 10,
            "category": "한식",
            "category_detail": "한식 > 국밥",
            "distance_m": 100 * i,
            "photo_url": f"https://img.test/{i}.jpg" if i else None,
        }
        for i in range(5)
    ]


def test_message_payload_shape():
    p = discord.build_recommendation("2026-10-23", sample_picks(), {"name": "어제식당", "category": "중식", "date": "2026-10-22"})
    assert p["flags"] & V2
    head = header(p)
    assert "10월 23일 금요일" in head and "어제식당" in head and "10/22" in head
    # 메뉴는 가장 구체적인 분류만 보여 준다
    assert "국밥" in texts(p) and "한식 > 국밥" not in texts(p)
    # 사진을 못 가져온 식당은 썸네일 없이 글자만
    assert thumbnails(p) == [f"https://img.test/{i}.jpg" for i in range(1, 5)]
    # 버튼은 한 줄에 5개 이하, 라벨은 80자 이하
    assert all(len(row["components"]) <= 5 for row in walk(p["components"]) if row["type"] == ROW)
    assert len(buttons(p)) == 7 and all(len(b["label"]) <= 80 for b in buttons(p))  # 식당 5 + 패스 + 투표 종료
    # 이모티콘은 쓰지 않는다
    shown = texts(p) + "".join(b["label"] for b in buttons(p))
    assert [ch for ch in shown if unicodedata.category(ch) == "So"] == []


def test_message_without_buttons():
    # 봇이 만들지 않은 웹훅은 버튼을 보낼 수 없어서, 버튼 없이도 만들 수 있어야 한다
    p = discord.build_recommendation("2026-10-23", sample_picks(), None, buttons=False)
    assert buttons(p) == [] and not [c for c in walk(p["components"]) if c["type"] == ROW]
    assert p["components"][0]["components"][-1]["type"] != SEPARATOR
    assert messages.NO_LATEST in header(p)
