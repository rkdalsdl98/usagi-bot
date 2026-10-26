"""1:1 대화 한 턴: 사람마다 따로 기억하고, 안내를 본 뒤에만 기록하고, 번역이 꺼져 있으면 기억을 건드리지 않는다."""
import random
from datetime import datetime, timedelta

import pytest

from lunchbot import answers, config, dialog, memory, storage
from test_flow import aws  # noqa: F401 (aws 는 fixture)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=config.KST)
TODAY = NOW.date().isoformat()
THREADS = {"a": "ta", "b": "tb", "w": "tw"}
PICKS = [{"name": "농민백암순대", "distance_m": 230}, {"name": "라멘집", "distance_m": 310}]


@pytest.fixture
def d(aws, vault_tmp):
    storage.put_json(storage.threads_key("g"), {"usagi": THREADS})
    storage.put_json(storage.members_key("g"), {"members": {"a": {"rank": 2}, "b": {"rank": 2}, "w": {"rank": 1}}})
    storage.put_json(storage.recommendation_key(TODAY), {"date": TODAY, "picks": PICKS})
    storage.put_json(storage.latest_key(), {**PICKS[0], "date": TODAY})
    return dialog.Dialog()


def say(d, author, text, thread=None, translating=True, now=NOW):
    return d.respond(guild_id="g", thread_id=thread or THREADS[author], author_id=author, owner_id="own", text=text,
                     now=now, translating=translating, rng=random.Random(3))


def words_of(talk):
    return " ".join(o.hachiware or "" for o in talk.outs)


def noticed(user):
    mem = memory.new()
    mem["noticed"] = TODAY
    memory.save("g", user, mem)


def files():
    return {k: storage.get_json(k) for k in storage.list_keys("memories/g/")}


def test_owner_of_thread(d):
    assert dialog.owner_of("g", "ta") == "a" and dialog.owner_of("g", "nope") is None


def test_first_chat_shows_guide_and_records_nothing(d):
    talk = say(d, "a", "라멘 좋아")
    assert answers.MEMORY_GUIDE in talk.outs[0].hachiware
    mem = memory.load("g", "a")
    assert mem["noticed"] == TODAY and mem["likes"] == [] and mem["last_seen"] is None and mem["moods"] == []


def test_remembers_after_the_guide(d):
    say(d, "a", "안녕")
    say(d, "a", "라멘 좋아")
    mem = memory.load("g", "a")
    assert mem["likes"] == ["라멘"] and mem["last_seen"] == TODAY


def test_follow_up_in_conversation(d):
    noticed("a")
    assert "농민백암순대" in words_of(say(d, "a", "오늘 점심 뭐야?"))
    assert "230" in words_of(say(d, "a", "거기 어디야?"))


def test_teach_then_use(d):
    noticed("a")
    assert "무슨 뜻인지 알려 줄래?" in words_of(say(d, "a", "점메추 해줘?"))
    assert "알았어" in words_of(say(d, "a", "점심 메뉴 추천이라는 뜻이야"))
    assert memory.load("g", "a")["taught"][0]["words"] == ["점메추"]  # 물음말·부탁말은 빼고 핵심 낱말만
    assert "농민백암순대" in words_of(say(d, "a", "점메추 뭐야?"))


def test_teach_an_answer(d):
    noticed("a")
    say(d, "a", "힘내라고 해 줄래?")
    say(d, "a", "그럴 땐 '오늘도 화이팅'이라고 해 줘")
    assert "오늘도 화이팅" in words_of(say(d, "a", "힘내라고 해 줄래?"))


def test_one_persons_teaching_is_not_anothers(d):
    noticed("a")
    noticed("b")
    say(d, "a", "점메추?")
    say(d, "a", "점심 메뉴 추천이라는 뜻이야")
    assert "잘 모르겠어" in words_of(say(d, "b", "점메추?"))


def test_other_person_in_my_thread_sees_nothing_of_mine(d):
    noticed("a")
    noticed("b")
    say(d, "a", "점메추?")
    say(d, "a", "점심 메뉴 추천이라는 뜻이야")
    say(d, "a", "오늘 점심 뭐야?")  # a 의 짧은 문맥: 농민백암순대
    before = files()
    asked = say(d, "b", "점메추 뭐야?", thread="ta")
    assert "농민백암순대" not in words_of(asked) and "무슨 뜻인지" not in words_of(asked)  # 가르치기도 못 함
    assert "230" not in words_of(say(d, "b", "거기 어디야?", thread="ta"))
    assert answers.MEMORY_GUIDE not in words_of(say(d, "b", "안녕", thread="ta"))
    assert files() == before  # a·b 기억 파일 모두 그대로


def test_translation_off_touches_no_memory(d, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("기억 파일을 건드림")

    monkeypatch.setattr(memory, "load", boom)
    monkeypatch.setattr(memory, "save", boom)
    for text in ("점메추?", "점심 메뉴 추천이라는 뜻이야", "오늘 점심 뭐야?", "안녕"):
        talk = say(d, "a", text, translating=False)
        assert all(o.hachiware is None for o in talk.outs) and talk.remark is None
        assert all(o.sound for o in talk.outs)


def test_below_worker_is_not_remembered(d):
    say(d, "w", "라멘 좋아")
    say(d, "w", "라멘 좋아")
    assert storage.list_keys("memories/g/") == []


def test_short_context_is_per_person_and_expires(d):
    noticed("a")
    noticed("b")
    say(d, "a", "오늘 점심 뭐야?")
    assert "230" not in words_of(say(d, "b", "거기 어디야?", thread="ta"))  # 같은 스레드라도 다른 사람
    assert "230" in words_of(say(d, "a", "거기 어디야?"))
    later = NOW + timedelta(minutes=11)
    assert "230" not in words_of(say(d, "a", "거기 어디야?", now=later))


def test_plain_chat_brings_back_a_memory(d):
    mem = memory.new()
    mem["noticed"] = TODAY
    mem["last_seen"] = (NOW.date() - timedelta(days=3)).isoformat()
    memory.save("g", "a", mem)
    talk = say(d, "a", "안녕")
    assert talk.plain is True and talk.remark == "3일 만이네!"
    assert memory.load("g", "a")["last_seen"] == TODAY


def test_locked_memory_still_answers_and_records_nothing(d, tmp_path, monkeypatch):
    from test_memory import switch_key

    noticed("a")
    before = files()
    switch_key(tmp_path, monkeypatch)
    talk = say(d, "a", "오늘 점심 뭐야?")
    assert "농민백암순대" in words_of(talk) and answers.MEMORY_GUIDE not in words_of(talk)
    say(d, "a", "라멘 좋아")
    assert files() == before


def test_save_failure_still_answers(d, monkeypatch):
    noticed("a")

    def full(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(memory, "save", full)
    assert "농민백암순대" in words_of(say(d, "a", "오늘 점심 뭐야?"))
