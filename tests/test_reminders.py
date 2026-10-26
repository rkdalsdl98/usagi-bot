"""리마인드: 날짜 정하기, 사람마다 따로·암호화해 저장, 정한 시각에 하치와레가 그 사람의 1:1 스레드에서 알림."""
import json
from datetime import datetime, timedelta

import pytest

from lunchbot import config, members, reminders, storage
from test_flow import aws  # noqa: F401 (aws 는 fixture)

NOW = datetime(2026, 10, 26, 15, 0, tzinfo=config.KST)
HOOK = "https://discord.com/api/webhooks/9/hachiware-token"


def at(*a):
    return datetime(*a, tzinfo=config.KST)


def test_when_defaults_to_today_and_rolls_to_tomorrow():
    assert reminders.when(NOW, 16, 30) == at(2026, 10, 26, 16, 30)
    assert reminders.when(NOW, 14, 0) == at(2026, 10, 27, 14, 0)  # 날짜를 비웠는데 지났으면 내일
    assert reminders.when(NOW, 14, 0, day=27) == at(2026, 10, 27, 14, 0)
    assert reminders.when(NOW, 9, 0, year=2027, month=1, day=1) == at(2027, 1, 1, 9, 0)
    with pytest.raises(reminders.RemindError, match="past"):
        reminders.when(NOW, 14, 0, month=10, day=26)  # 날짜를 넣었는데 지난 시각
    with pytest.raises(reminders.RemindError, match="bad_date"):
        reminders.when(NOW, 9, 0, month=2, day=30)


def add(user, text, when, name="민지"):
    return reminders.add("g", user, name, f"t-{user}", text, when, NOW)


def test_add_list_cancel_are_per_person(aws):
    add("a", "회의", at(2026, 10, 26, 17, 0))
    add("a", "점심", at(2026, 10, 26, 16, 0))
    add("b", "운동", at(2026, 10, 26, 18, 0))
    assert [r["text"] for r in reminders.mine("g", "a")] == ["점심", "회의"]  # 이른 것부터
    assert reminders.cancel("g", "a", 1) is True and [r["text"] for r in reminders.mine("g", "a")] == ["회의"]
    assert reminders.cancel("g", "a", 9) is False and reminders.cancel("g", "a", 0) is False
    assert [r["text"] for r in reminders.mine("g", "b")] == ["운동"]
    assert reminders.forget("g", "a") == 1 and reminders.mine("g", "a") == [] and len(reminders.mine("g", "b")) == 1


def test_saved_reminders_are_sealed(aws):
    add("a", "비밀 회의", at(2026, 10, 26, 17, 0))
    stored = storage.get_json(storage.reminders_key("g"))
    assert set(stored) == {"v", "box"} and "비밀" not in json.dumps(stored, ensure_ascii=False)


def test_limit_and_text(aws):
    for i in range(reminders.LIMIT):
        add("a", f"할 일 {i}", at(2026, 10, 27, 9, 0))
    with pytest.raises(reminders.RemindError, match="too_many"):
        add("a", "하나 더", at(2026, 10, 27, 9, 0))
    with pytest.raises(reminders.RemindError, match="empty"):
        add("b", "   ", at(2026, 10, 27, 9, 0))
    assert len(add("b", "가" * 150, at(2026, 10, 27, 9, 0))["text"]) == 100


def test_fire_due_sends_once_with_a_late_tag(aws):
    add("a", "회의", at(2026, 10, 26, 15, 0))
    add("a", "지난 것", at(2026, 10, 26, 14, 50))
    add("a", "나중", at(2026, 10, 26, 16, 0))
    sent = []
    assert reminders.fire_due("g", NOW, lambda item, late: sent.append((item["text"], late)) or True) == 2
    assert sorted(sent) == [("지난 것", True), ("회의", False)]  # 2분 넘게 지났으면 '늦었지만'
    assert reminders.fire_due("g", NOW, lambda item, late: sent.append(item["text"]) or True) == 0  # 한 번만
    assert [r["text"] for r in reminders.mine("g", "a")] == ["나중"]


def test_failed_send_is_retried_then_dropped(aws):
    add("a", "회의", at(2026, 10, 26, 15, 0))

    def broken(item, late):
        raise OSError("network down")

    assert reminders.fire_due("g", NOW, broken) == 0 and len(reminders.mine("g", "a")) == 1  # 다음에 다시
    assert reminders.fire_due("g", NOW + timedelta(minutes=1), lambda item, late: True) == 1
    add("a", "오래된 것", at(2026, 10, 26, 15, 0))
    assert reminders.fire_due("g", NOW + timedelta(days=2), broken) == 0 and reminders.mine("g", "a") == []  # 하루 넘으면 버림


@pytest.fixture
def delivery(aws, monkeypatch):
    hooked, posted = [], []
    monkeypatch.setattr(config, "USAGI_CHANNEL_ID", "555")
    monkeypatch.setattr(reminders.hachiware, "hooks", lambda: {"555": HOOK})
    monkeypatch.setattr(reminders.discord, "execute_webhook",
                        lambda url, text, users=None: hooked.append((url, text, users)) or {})
    monkeypatch.setattr(reminders.discord, "send_message", lambda token, cid, payload: posted.append((cid, payload)) or {})
    monkeypatch.setattr(reminders.discord, "unarchive_thread", lambda token, tid: None)
    members.save("g", {"a": {"rank": members.WORKER}, "w": {"rank": members.WALKER}})
    return hooked, posted


def test_deliver_uses_hachiware_in_the_thread_and_pings_only_that_person(delivery, monkeypatch):
    hooked, posted = delivery
    item = add("a", "회의 준비", at(2026, 10, 26, 15, 0))
    assert reminders.deliver("g", "own", item, late=False) is True
    [(url, text, users)] = hooked
    assert url == f"{HOOK}?thread_id=t-a" and users == ["a"] and text.startswith("<@a> ") and "회의 준비" in text
    assert "오후 3시 0분" in text and not posted  # 우사기(봇 계정)는 말하지 않음
    assert "늦었지만" in reminders.message(item, late=True)
    monkeypatch.setattr(reminders.hachiware, "hooks", lambda: {})  # 하치와레 웹훅이 없으면 봇 계정으로 하치와레 말을
    reminders.deliver("g", "own", item, late=False)
    [(cid, payload)] = posted
    assert cid == "t-a" and "> **하치와레**" in payload["content"] and payload["allowed_mentions"]["users"] == ["a"]


def test_deliver_skips_people_below_worker(delivery):
    hooked, posted = delivery
    item = add("w", "회의", at(2026, 10, 26, 15, 0))
    assert reminders.deliver("g", "own", item, late=False) is True and not hooked and not posted  # 스레드를 못 보니 버림


def test_fire_all_sends_due_reminders_through_hachiware(delivery):
    hooked, _ = delivery
    add("a", "회의", at(2026, 10, 26, 15, 0))
    add("a", "나중", at(2026, 10, 26, 18, 0))
    assert reminders.fire_all("g", "own", NOW) == 1
    assert [text for _, text, _ in hooked if "회의" in text] and len(hooked) == 1
    assert [r["text"] for r in reminders.mine("g", "a")] == ["나중"]
