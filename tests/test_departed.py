"""서버를 나가거나 추방된 사람의 사람별 기록(기억·생일·개인 번역·등급·1:1 스레드)을 지운다."""
import logging
import urllib.error

import pytest

from lunchbot import birthdays, departed, hachiware, members, memory, storage
from test_commands import GUILD, bot  # noqa: F401 (bot 은 fixture)
from test_flow import aws  # noqa: F401 (aws 는 fixture)

G = "g"


@pytest.fixture
def world(aws, vault_tmp, monkeypatch):
    for uid in ("gone", "stay"):
        mem = memory.new()
        mem["likes"] = ["라멘"]
        memory.save(G, uid, mem)
        birthdays.save(G, uid, 3, 5, by="x")
        hachiware.turn(True, "x", user_id=uid)
    members.save(G, {"gone": {"rank": 2}, "stay": {"rank": 2}, "walk": {"rank": 1}})
    storage.put_json(storage.threads_key(G), {"usagi": {"gone": "tg", "stay": "ts", "walk": "tw", "x": "tx"}})
    calls = {"deleted": [], "left": [], "fail": None}

    def delete(token, channel_id, reason):
        if calls["fail"]:
            raise urllib.error.HTTPError("u", calls["fail"], "no", {}, None)
        calls["deleted"].append(channel_id)

    def leave(token, thread_id, user_id):
        calls["left"].append((thread_id, user_id))

    monkeypatch.setattr(departed.discord, "delete_channel", delete)
    monkeypatch.setattr(departed.discord, "remove_thread_member", leave)
    return calls


def records(uid):
    return {
        "memory": memory.load(G, uid) != memory.new(),
        "birthday": birthdays.get(G, uid) is not None,
        "translate": str(uid) in (storage.get_json(storage.HACHIWARE_PEOPLE_KEY) or {}),
        "rank": uid in members.load(G),
        "thread": uid in (storage.get_json(storage.threads_key(G)) or {}).get("usagi", {}),
    }


def test_forget_person_removes_every_per_person_record(world):
    departed.forget_person(G, "gone")
    assert not any(records("gone").values())
    assert all(records("stay").values())
    assert world["deleted"] == ["tg"]


def test_votes_and_games_are_kept(world):
    storage.put_json(storage.vote_result_key("m1"), {"voters": {"p": ["gone"]}})
    storage.put_json(storage.game_key("c"), {"scores": {"gone": 3}})
    departed.forget_person(G, "gone")
    assert storage.get_json(storage.vote_result_key("m1")) == {"voters": {"p": ["gone"]}}
    assert storage.get_json(storage.game_key("c")) == {"scores": {"gone": 3}}


def test_missing_thread_and_no_permission(world, caplog):
    world["fail"] = 404  # 이미 지워진 스레드
    departed.forget_person(G, "gone")
    assert not any(records("gone").values()) and not caplog.records
    world["fail"] = 403  # 봇에 '스레드 관리' 권한이 없음
    departed.forget_person(G, "stay")
    assert "스레드 관리" in caplog.text
    left = records("stay")
    assert left.pop("thread") is True and not any(left.values())  # 스레드 기록만 남겨 다음 정리 때 다시 지움


def test_sweep_finds_people_who_already_left(world):
    memory.save(G, "ghost", memory.new())  # 기억 파일만 남은 사람
    n = departed.sweep(G, {"stay", "walk", "x", "own"}, "own")
    assert n == 2 and not any(records("gone").values()) and all(records("stay").values())
    assert storage.list_keys(f"memories/{G}/") == [memory.key(G, "stay")]


def test_sweep_refuses_a_broken_member_list(world):
    assert departed.sweep(G, set(), "own") == 0  # 사람 목록을 못 읽었으면 아무도 지우지 않음
    assert departed.sweep(G, {"stay"}, "own") == 0  # 서버 주인이 없는 목록은 덜 읽힌 것
    assert all(records("gone").values()) and world["deleted"] == []


def test_sweep_removes_low_ranks_from_threads(world):
    departed.sweep(G, {"gone", "stay", "walk", "x", "own"}, "own")
    assert sorted(world["left"]) == [("tw", "walk"), ("tx", "x")]  # 행인·멤버 아님, 직장인(stay)은 그대로
    assert records("walk")["thread"] and records("walk")["rank"]  # 기록은 그대로


def test_sweep_logs_no_ids(world, caplog):
    caplog.set_level(logging.INFO)
    departed.sweep(G, {"stay", "walk", "x", "own"}, "own")
    assert "gone" not in caplog.text and "tg" not in caplog.text


def test_kick_forgets_right_away(bot, vault_tmp, monkeypatch):
    deleted = []
    monkeypatch.setattr(departed.discord, "delete_channel", lambda token, cid, reason: deleted.append(cid))
    birthdays.save(GUILD, "x", 3, 5, by="x")
    storage.put_json(storage.threads_key(GUILD), {"usagi": {"x": "tx"}})
    bot.kick.fail = 403  # 못 내보냈으면 그대로
    bot("추방", "own", "x")
    assert birthdays.get(GUILD, "x") == (3, 5) and deleted == []
    bot.kick.fail = None
    bot("추방", "own", "x")
    assert birthdays.get(GUILD, "x") is None and deleted == ["tx"]
