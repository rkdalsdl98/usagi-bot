"""/리마인드·/리마인드목록·/리마인드취소: 직장인 갑옷씨부터, 모두 나만 보기, 알림은 내 1:1 스레드로."""
import json
from datetime import datetime

import pytest

import interaction
from lunchbot import config, members, reminders
from test_commands import GUILD, bot, slash  # noqa: F401 (bot 은 fixture)
from test_flow import aws, signed_event  # noqa: F401 (aws 는 fixture)

NOW = datetime(2026, 10, 26, 15, 0, tzinfo=config.KST)


def call(command, actor, **opts):
    event = slash(command, actor)
    event["data"]["options"] = [{"type": 3 if isinstance(v, str) else 4, "name": k, "value": v} for k, v in opts.items()]
    return json.loads(interaction.handler(signed_event(event), None)["body"])


@pytest.fixture
def team(bot, monkeypatch):
    monkeypatch.setattr(config, "now_kst", lambda: NOW)
    members.save(GUILD, {"work": {"rank": members.WORKER}, "walk": {"rank": members.WALKER}})
    return bot


def test_remind_needs_worker(team):
    for who in ("x", "walk"):
        _, said = team("리마인드", who)
        assert "직장인 갑옷씨" in said
    assert reminders.mine(GUILD, "walk") == []


def test_remind_saves_privately_and_opens_my_thread(team):
    n = len(team.hooked)
    body = call("리마인드", "work", 내용="비밀 회의", 시간=16, 분=30)
    content = body["data"]["content"]
    assert body["data"]["flags"] == 64 and "10월 26일 오후 4시 30분" in content and "<#t1>" in content
    assert len(team.hooked) == n  # 나만 보기: 채널에 하치와레 말이 안 감
    assert team.threads["made"] and team.threads["added"][-1] == ("t1", "work")  # 1:1 스레드가 없으면 만듦
    [item] = reminders.mine(GUILD, "work")
    assert (item["text"], item["thread"], item["at"]) == ("비밀 회의", "t1", "2026-10-26T16:30:00+09:00")


def test_remind_dates_and_refusals(team):
    assert "10월 27일 오후 2시 0분" in call("리마인드", "work", 내용="내일", 시간=14, 분=0)["data"]["content"]
    for opts, word in ((dict(월=10, 일=26, 시간=14, 분=0), "지난"), (dict(월=2, 일=30, 시간=9, 분=0), "날짜"),
                       (dict(시간=9, 분=0, 내용="   "), "뭘")):
        body = call("리마인드", "work", **{"내용": "회의", **opts})
        assert body["data"]["flags"] == 64 and word in body["data"]["content"]
    assert len(reminders.mine(GUILD, "work")) == 1


def test_remind_list_and_cancel(team):
    call("리마인드", "work", 내용="회의", 시간=17, 분=0)
    call("리마인드", "work", 내용="점심", 시간=16, 분=0)
    body = call("리마인드목록", "work")
    content = body["data"]["content"]
    assert body["data"]["flags"] == 64 and content.index("1. 10월 26일 오후 4시 0분 — 점심") < content.index("2. ")
    body = call("리마인드취소", "work", 번호=1)
    assert body["data"]["flags"] == 64 and [r["text"] for r in reminders.mine(GUILD, "work")] == ["회의"]
    assert "번호" in call("리마인드취소", "work", 번호=9)["data"]["content"]
    call("리마인드취소", "work", 번호=1)
    assert "없어" in call("리마인드목록", "work")["data"]["content"]
