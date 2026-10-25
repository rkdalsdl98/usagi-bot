"""투표: 한 사람 한 표(바꿀 수 있음), 정원이 차거나 '투표 종료'를 누르면 가장 많이 받은 식당으로 결정."""
import json
from types import SimpleNamespace

import pytest

from lunchbot import config, messages, storage
import interaction
import recommend
from test_flow import V2, aws, buttons, header, made_of, signed_event, texts, walk  # noqa: F401 (aws 는 fixture)

ROW, TEXT = 1, 10


def press(custom_id, user_id, name, message_id="m1", nick=None):
    event = {
        "type": 3,
        "data": {"custom_id": custom_id, "component_type": 2},
        "member": {"nick": nick, "user": {"id": user_id, "username": f"user-{user_id}", "global_name": name}},
        "message": {"id": message_id},
    }
    return json.loads(interaction.handler(signed_event(event), None)["body"])


def block_of(payload, name):
    """식당 한 곳의 글자 블록 (이름 링크 + 메뉴·거리 + 투표 줄)."""
    return next(
        c["content"] for c in walk(payload["components"]) if c["type"] == TEXT and f"[{name}](" in c["content"]
    )


@pytest.fixture
def vote(aws, monkeypatch):
    """정원 3명으로 추천을 하나 보낸다 (메시지 id m1)."""
    monkeypatch.setattr(config, "VOTER_COUNT", 3)
    recommend.handler({}, None)
    date = config.today_kst()
    picks = storage.get_json(storage.recommendation_key(date))["picks"]
    return SimpleNamespace(
        sent=aws,
        date=date,
        picks=picks,
        pick=lambda i: f"pick:{date}:{picks[i]['id']}",
        skip=f"skip:{date}",
        end=f"end:{date}",
    )


def test_vote_message_has_progress_and_end_button(vote):
    msg = vote.sent[-1]
    assert "투표 0/3" in header(msg)
    end = buttons(msg, "end:")
    assert [b["custom_id"] for b in end] == [vote.end] and end[0]["label"] == messages.END_LABEL
    assert all(len(r["components"]) <= 5 for r in walk(msg["components"]) if r["type"] == ROW)


def test_votes_show_names_and_can_be_changed(vote):
    a, b = vote.picks[0]["name"], vote.picks[1]["name"]
    body = press(vote.pick(0), "u1", "민지")
    assert body["type"] == 7 and body["data"]["flags"] & V2
    assert "1표 · 민지" in block_of(body["data"], a) and "투표 1/3" in header(body["data"])
    assert buttons(body["data"], "pick:")  # 아직 진행 중이라 버튼이 남아 있다

    body = press(vote.pick(1), "u1", "민지")  # 마음을 바꿈
    assert "표 ·" not in block_of(body["data"], a) and "1표 · 민지" in block_of(body["data"], b)
    assert "투표 1/3" in header(body["data"])  # 한 사람은 한 표

    body = press(vote.skip, "u2", "현우", nick="현우(점심)")  # 서버 별명이 있으면 별명으로
    assert "패스 1표 · 현우(점심)" in texts(body["data"]) and "투표 2/3" in header(body["data"])
    assert storage.get_json(storage.LATEST_KEY) is None  # 아직 끝나지 않았다


def test_vote_closes_when_everyone_voted(vote):
    press(vote.pick(0), "u1", "민지")
    press(vote.pick(0), "u2", "현우")
    body = press(vote.pick(1), "u3", "지호")
    data = body["data"]
    assert body["type"] == 7 and data["flags"] & V2 and buttons(data) == []
    assert "투표 끝" in header(data) and "3명 중 3명 투표" in header(data)
    assert made_of(data, messages.EXCITED)
    assert texts(data).count("map.naver.com") == 1  # 고른 식당 카드만 남는다
    assert "2표 · 민지, 현우" in block_of(data, vote.picks[0]["name"])
    latest = storage.get_json(storage.LATEST_KEY)
    assert latest["id"] == vote.picks[0]["id"] and latest["selected_by"] == "투표"
    saved = storage.get_json(storage.selection_key(vote.picks[0]["category"], vote.date))
    assert saved["id"] == vote.picks[0]["id"] and saved["voters"] == ["민지", "현우"]


def test_end_button_closes_with_votes_so_far(vote):
    press(vote.pick(2), "u1", "민지")
    body = press(vote.end, "u2", "현우")
    assert buttons(body["data"]) == [] and "3명 중 1명 투표" in header(body["data"])
    assert storage.get_json(storage.LATEST_KEY)["id"] == vote.picks[2]["id"]


def test_pass_majority_means_no_selection(vote):
    press(vote.skip, "u1", "민지")
    press(vote.skip, "u2", "현우")
    body = press(vote.pick(0), "u3", "지호")
    assert buttons(body["data"]) == [] and "투표 끝" in header(body["data"])
    assert "map.naver.com" not in texts(body["data"])  # 식당 카드 없음
    assert made_of(body["data"], messages.SULKY, trill=True)
    assert storage.get_json(storage.LATEST_KEY) is None


def test_tie_prefers_restaurant_over_pass(vote):
    press(vote.skip, "u1", "민지")
    press(vote.pick(3), "u2", "현우")
    press(vote.end, "u3", "지호")
    assert storage.get_json(storage.LATEST_KEY)["id"] == vote.picks[3]["id"]


def test_tie_between_restaurants_picks_one_of_them(vote):
    press(vote.pick(0), "u1", "민지")
    press(vote.pick(1), "u2", "현우")
    press(vote.end, "u3", "지호")
    assert storage.get_json(storage.LATEST_KEY)["id"] in {vote.picks[0]["id"], vote.picks[1]["id"]}


def test_ending_with_no_votes_means_no_selection(vote):
    body = press(vote.end, "u1", "민지")
    assert "아무도 투표하지 않음" in header(body["data"]) and buttons(body["data"]) == []
    assert storage.get_json(storage.LATEST_KEY) is None


def test_clicks_after_close_keep_the_result(vote):
    press(vote.pick(0), "u1", "민지")
    first = press(vote.end, "u1", "민지")
    late = press(vote.pick(1), "u2", "현우")  # 화면이 늦게 갱신된 사람이 누른 버튼
    assert late["type"] == 7 and buttons(late["data"]) == []
    assert texts(late["data"]) == texts(first["data"])
    assert storage.get_json(storage.LATEST_KEY)["id"] == vote.picks[0]["id"]


def test_votes_are_counted_per_message(vote):
    recommend.handler({}, None)  # 같은 날 두 번째 메시지 (m2)
    second = storage.get_json(storage.recommendation_key(vote.date))["picks"]
    press(vote.pick(0), "u1", "민지", message_id="m1")
    body = press(f"pick:{vote.date}:{second[0]['id']}", "u2", "현우", message_id="m2")
    assert "투표 1/3" in header(body["data"])  # m1 의 표는 섞이지 않는다


def test_without_head_count_vote_ends_only_by_button(aws, monkeypatch):
    monkeypatch.setattr(config, "VOTER_COUNT", 0)
    monkeypatch.setattr(recommend.discord, "channel_viewer_count", lambda token, channel_id: None)
    recommend.handler({}, None)
    date = config.today_kst()
    first = storage.get_json(storage.recommendation_key(date))["picks"][0]["id"]
    assert "투표 0명" in header(aws[-1])
    for i in range(5):
        body = press(f"pick:{date}:{first}", f"u{i}", f"사람{i}")
    assert buttons(body["data"], "pick:") and "투표 5명" in header(body["data"])  # 아직 열려 있다


def test_head_count_is_counted_when_voter_count_not_set(aws, monkeypatch):
    monkeypatch.setattr(config, "VOTER_COUNT", 0)
    seen = []
    monkeypatch.setattr(recommend.discord, "channel_viewer_count", lambda token, channel_id: seen.append((token, channel_id)) or 4)
    recommend.handler({}, None)
    assert seen == [("test-bot-token", "42")] and "투표 0/4" in header(aws[-1])


def test_voter_count_setting_wins_over_head_count(aws, monkeypatch):
    monkeypatch.setattr(config, "VOTER_COUNT", 7)
    monkeypatch.setattr(recommend.discord, "channel_viewer_count", lambda *a: pytest.fail("설정값이 있으면 세지 않는다"))
    recommend.handler({}, None)
    assert "투표 0/7" in header(aws[-1])
