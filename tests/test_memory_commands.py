"""/기억 보기·지우기 (직장인 갑옷씨부터, 나만 보기)와 강등되면 1:1 스레드에서 내보내기."""
import json
import urllib.error

import pytest

import interaction
from lunchbot import members, memory, storage
from test_commands import GUILD, bot, slash  # noqa: F401 (bot 은 fixture)
from test_flow import aws, signed_event  # noqa: F401 (aws 는 fixture)


def call(command, actor, number=None, **kw):
    event = slash(command, actor, **kw)
    if number is not None:
        event["data"]["options"][0]["options"] = [{"type": 4, "name": "번호", "value": number}]
    return json.loads(interaction.handler(signed_event(event), None)["body"])


@pytest.fixture
def team(bot, vault_tmp, monkeypatch):
    members.save(GUILD, {"work": {"rank": members.WORKER}, "walk": {"rank": members.WALKER}})
    storage.put_json(storage.threads_key(GUILD), {"usagi": {"work": "t-work", "walk": "t-walk"}})
    left = []

    def remove(token, thread_id, user_id):
        if remove.fail:
            raise urllib.error.HTTPError("u", remove.fail, "no", {}, None)
        left.append((thread_id, user_id))

    remove.fail = None
    monkeypatch.setattr(interaction.commands.discord, "remove_thread_member", remove)
    bot.left, bot.remove = left, remove
    return bot


def remembered(user):
    mem = memory.new()
    mem["likes"] = ["라멘"]
    mem["last_seen"] = "2026-10-26"
    mem["taught"] = [{"words": ["점메추"], "kind": "meaning", "topic": "lunch", "ask": "what", "at": "2026-10-26"},
                     {"words": ["힘내"], "kind": "answer", "answer": "오늘도 화이팅", "at": "2026-10-26"}]
    memory.save(GUILD, user, mem)


def test_memory_commands_need_worker(team):
    remembered("walk")
    for who in ("x", "walk"):  # 멤버가 아니거나 행인 갑옷씨 (강등돼서 기억이 남아 있어도)
        _, said = team("기억 보기", who)
        assert "직장인 갑옷씨" in said and "라멘" not in said
        team("기억 지우기", who)
    assert memory.load(GUILD, "walk")["likes"] == ["라멘"]


def test_memory_show_is_private_and_lists(team):
    remembered("work")
    n = len(team.hooked)
    body = call("기억 보기", "work")
    content = body["data"]["content"]
    assert body["data"]["flags"] == 64 and len(team.hooked) == n  # 나만 보기, 웹훅으로는 안 감
    assert "라멘" in content and "1. 점메추" in content and "2. 힘내" in content and "오늘도 화이팅" in content


def test_memory_show_when_empty(team):
    body = call("기억 보기", "work")
    assert body["data"]["flags"] == 64 and "라멘" not in body["data"]["content"]


def test_memory_forget_one_and_all(team):
    remembered("work")
    body = call("기억 지우기", "work", number=1)
    assert body["data"]["flags"] == 64 and [t["words"] for t in memory.load(GUILD, "work")["taught"]] == [["힘내"]]
    body = call("기억 지우기", "work", number=9)
    assert body["data"]["flags"] == 64 and len(memory.load(GUILD, "work")["taught"]) == 1
    body = call("기억 지우기", "work")
    assert body["data"]["flags"] == 64 and storage.list_keys(f"memories/{GUILD}/") == []


def test_demotion_removes_from_thread_but_keeps_records(team):
    remembered("work")
    before = storage.list_keys(f"memories/{GUILD}/")
    _, said = team("멤버강등", "own", "work", rank=members.WALKER)
    assert team.left == [("t-work", "work")]  # 응답 뒤 1:1 스레드에서 내보냄
    assert storage.list_keys(f"memories/{GUILD}/") == before and memory.load(GUILD, "work")["likes"] == ["라멘"]
    assert storage.get_json(storage.threads_key(GUILD))["usagi"]["work"] == "t-work"  # 스레드 기록도 그대로
    assert "스레드" not in said  # 1:1 을 썼는지 공개 답에 드러내지 않음


def test_member_removed_also_leaves_thread(team):
    team("멤버삭제", "own", "work")
    assert team.left == [("t-work", "work")]


def test_promotion_and_low_moves_do_not_remove(team):
    team("멤버승급", "own", "walk", rank=members.WORKER)
    team("멤버강등", "own", "walk", rank=members.WALKER)  # 직장인 → 행인 은 내보냄
    assert team.left == [("t-walk", "walk")]
    members.save(GUILD, {**members.load(GUILD), "cap": {"rank": members.CAPTAIN}})
    team("멤버강등", "own", "cap", rank=members.WORKER)  # 대장 → 직장인 은 그대로
    assert team.left == [("t-walk", "walk")]


def test_leaving_a_thread_that_is_gone(team):
    team.remove.fail = 404  # 이미 스레드가 없거나 그 사람이 없음
    team("멤버삭제", "own", "work")
    assert team.left == []


def test_memory_commands_when_locked(team, tmp_path, monkeypatch):
    from test_memory import switch_key

    remembered("work")
    switch_key(tmp_path, monkeypatch)
    for command in ("기억 보기", "기억 지우기"):
        body = call(command, "work")
        content = body["data"]["content"]
        assert body["data"]["flags"] == 64 and "열 수 없" in content and "아직 기억한 게 없어" not in content


def test_memory_show_fits_discord_and_shows_everything(team):
    mem = memory.new()
    mem["last_seen"] = "2026-10-26"
    mem["moods"] = [[f"2026-10-{d:02d}", "sad"] for d in range(10, 20)]
    mem["topics"] = {k: i + 1 for i, k in enumerate(("greet", "bye", "praise", "laugh", "sad", "angry", "food",
                                                     "surprise", "agree", "call"))}
    mem["likes"] = [f"좋아하는것{i:02d}" + "가" * 30 for i in range(20)]
    mem["dislikes"] = [f"싫어하는것{i:02d}" + "나" * 30 for i in range(20)]
    mem["foods"] = [[f"2026-10-{d:02d}", "라멘"] for d in range(20, 25)]
    mem["taught"] = [{"words": [f"말{i}", "가" * 40], "kind": "answer", "answer": "다" * 100, "at": "2026-10-26"}
                     for i in range(50)]
    memory.save(GUILD, "work", mem)
    n = len(team.followed)
    body = call("기억 보기", "work")
    extra = [text for _, _, text, private in team.followed[n:] if private]
    assert len(team.followed[n:]) == len(extra)  # 이어지는 것도 나만 보기
    pages = [body["data"]["content"]] + extra
    assert all(len(p) <= 2000 for p in pages)
    shown = "\n".join(pages)
    assert all(f"\n{i}. " in shown for i in range(1, 51))  # 지울 번호가 모두 보임
    assert all(f"2026-10-{d:02d}" in shown for d in range(10, 20))  # 최근 기분 모두
    assert all(f"좋아하는것{i:02d}" in shown and f"싫어하는것{i:02d}" in shown for i in range(20))
    assert "부르기" in shown and "인사" in shown  # 자주 하는 이야기 모두


def test_memory_show_lists_words_learned(team):
    mem = memory.new()
    mem["last_seen"] = "2026-10-26"
    mem["known"] = ["민지네"]
    mem["taught"] = [{"words": ["아샷추"], "kind": "word", "means": "아이스티에 샷 추가", "at": "2026-10-26"}]
    memory.save(GUILD, "work", mem)
    content = call("기억 보기", "work")["data"]["content"]
    assert "알게 된 낱말" in content and "민지네" in content and "1. 아샷추 → '아이스티에 샷 추가' 뜻" in content
