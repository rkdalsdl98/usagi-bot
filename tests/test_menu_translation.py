"""메뉴 추천 메시지와 투표 결과의 우사기 소리는, 하치와레 번역이 켜져 있을 때만 그 채널의 하치와레가 번역한다.

번역이 꺼져 있으면(기본) 우사기가 무슨 말을 하든 하치와레는 번역하지 않는다. 그 채널에 웹훅이 없어도 번역하지 않는다.
"""
import json

import pytest

from lunchbot import config, hachiware, storage
import interaction
import recommend
from test_flow import aws, header, signed_event  # noqa: F401 (aws 는 fixture)

LUNCH_HOOK, DINNER_HOOK = "https://hook/lunch", "https://hook/dinner"


@pytest.fixture
def hooked(aws, monkeypatch):
    said = []
    monkeypatch.setattr(hachiware, "hooks", lambda: {"42": LUNCH_HOOK, "77": DINNER_HOOK})
    monkeypatch.setattr(hachiware.discord, "execute_webhook", lambda url, text: said.append((url, text)) or {"id": "h"})
    monkeypatch.setattr(config, "DINNER_CHANNEL_ID", "77")
    hachiware.turn(True, "테스트")
    return said


@pytest.fixture
def scripts(monkeypatch):
    """추천·결과 메시지를 만들 때 짝지은 우사기 소리와 번역을 모아 둔다."""
    made = []
    for name in ("recommend_script", "result_script"):
        real = getattr(hachiware, name)
        monkeypatch.setattr(hachiware, name, lambda *a, _real=real, **kw: made.append(_real(*a, **kw)) or made[-1])
    return made


def press(custom_id, user_id, message_id, channel_id="42"):
    event = {
        "type": 3, "channel_id": channel_id,
        "data": {"custom_id": custom_id, "component_type": 2},
        "member": {"user": {"id": user_id, "username": user_id, "global_name": user_id}},
        "message": {"id": message_id},
    }
    return json.loads(interaction.handler(signed_event(event), None)["body"])


def test_menu_follows_the_server_wide_switch_not_personal_ones(hooked):
    hachiware.turn(False, "테스트")
    hachiware.turn(True, "누군가", user_id="u1")  # 누군가 개인 번역을 켜도
    recommend.handler({}, None)
    assert hooked == []  # 메뉴 추천은 서버 전체 설정을 따름
    hachiware.turn(True, "테스트")
    hachiware.turn(False, "누군가", user_id="u1")  # 누군가 개인 번역을 꺼도
    recommend.handler({}, None)
    assert len(hooked) == 1


def test_nothing_is_translated_when_the_switch_is_off(hooked, monkeypatch):
    hachiware.turn(False, "테스트")
    monkeypatch.setattr(config, "VOTER_COUNT", 1)
    recommend.handler({}, None)
    date = config.today_kst()
    pick = storage.get_json(storage.recommendation_key(date))["picks"][0]
    press(f"pick:{date}:{pick['id']}", "u1", "m1")  # 마감
    assert hooked == []  # 추천도 결과도 번역 안 함


def test_recommendation_is_translated_when_the_switch_is_on(hooked, scripts, aws):
    recommend.handler({}, None)
    # 추천 메시지 머리말의 우사기 소리와 하치와레 번역은 같은 짝에서 나온다 (토막 수가 같음)
    assert header(aws[-1]).split("\n")[0] == scripts[-1].sound
    assert len(hooked) == 1 and hooked[0][0] == LUNCH_HOOK and scripts[-1].text in hooked[0][1]
    recommend.handler({"meal": "dinner"}, None)
    assert header(aws[-1]).split("\n")[0] == scripts[-1].sound
    assert hooked[-1][0] == DINNER_HOOK and scripts[-1].text in hooked[-1][1]


def test_no_webhook_or_failed_webhook_does_not_stop_the_recommendation(hooked, monkeypatch):
    monkeypatch.setattr(hachiware, "hooks", lambda: {})
    assert recommend.handler({}, None)["picks"] and hooked == []

    def down(url, text):
        raise OSError("HTTP Error 404: Not Found")

    monkeypatch.setattr(hachiware, "hooks", lambda: {"42": LUNCH_HOOK})
    monkeypatch.setattr(hachiware.discord, "execute_webhook", down)
    assert recommend.handler({}, None)["picks"]  # 추천은 그대로 나감


def test_vote_result_is_translated(hooked, scripts, monkeypatch):
    monkeypatch.setattr(config, "VOTER_COUNT", 1)
    recommend.handler({}, None)  # 메시지 m1
    date = config.today_kst()
    pick = storage.get_json(storage.recommendation_key(date))["picks"][0]
    hooked.clear()
    body = press(f"pick:{date}:{pick['id']}", "u1", "m1")  # 정원 1명이 투표 → 마감
    assert header(body["data"]).split("\n")[0] == scripts[-1].sound  # 결과 메시지의 우사기 소리와 짝
    assert len(hooked) == 1 and hooked[0][0] == LUNCH_HOOK and pick["name"] in hooked[0][1]
    assert scripts[-1].text in hooked[0][1]
    press(f"pick:{date}:{pick['id']}", "u2", "m1")  # 이미 끝난 투표: 다시 번역하지 않음
    assert len(hooked) == 1

    recommend.handler({}, None)  # 메시지 m2
    hooked.clear()
    press(f"end:{date}", "u1", "m2")  # 아무도 안 고르고 종료
    assert len(hooked) == 1 and scripts[-1].text in hooked[0][1] and pick["name"] not in hooked[0][1]


def test_votes_in_progress_are_not_translated(hooked, monkeypatch):
    monkeypatch.setattr(config, "VOTER_COUNT", 3)
    recommend.handler({}, None)
    date = config.today_kst()
    pick = storage.get_json(storage.recommendation_key(date))["picks"][0]
    hooked.clear()
    press(f"pick:{date}:{pick['id']}", "u1", "m1")
    assert hooked == []


def test_menu_translation_uses_the_right_thoughts(hooked, monkeypatch):
    abouts = []
    real = hachiware.retell
    monkeypatch.setattr(hachiware, "retell", lambda text, about, *a, **kw: abouts.append(about) or real(text, about, *a, **kw))
    monkeypatch.setattr(config, "VOTER_COUNT", 1)
    recommend.handler({}, None)
    recommend.handler({"meal": "dinner"}, None)
    date = config.today_kst()
    pick = storage.get_json(storage.recommendation_key(date))["picks"][0]
    press(f"pick:{date}:{pick['id']}", "u1", "m1")  # 점심 투표 마감 (식당 정해짐)
    press(f"end:{date}", "u1", "m2")  # 저녁은 아무도 안 고르고 종료
    assert abouts == ["lunch", "dinner", "won", "none"]
