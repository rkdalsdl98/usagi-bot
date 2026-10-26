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
    assert talk.notice is True and answers.MEMORY_GUIDE in talk.outs[0].hachiware
    assert storage.list_keys("memories/g/") == []  # 안내가 닿기 전에는 아무것도 저장하지 않음
    again = say(d, "a", "라멘 좋아")  # 안내가 닿았다는 말이 없으면 다시 안내
    assert again.notice is True and storage.list_keys("memories/g/") == []


def test_guide_counts_only_when_delivered(d):
    say(d, "a", "안녕")
    d.noticed("g", "a", NOW.date())  # 우사기 봇이 하치와레 안내를 보낸 뒤 부름
    mem = memory.load("g", "a")
    assert mem["noticed"] == TODAY and mem["likes"] == [] and mem["last_seen"] is None
    assert say(d, "a", "안녕").notice is False


def test_remembers_after_the_guide(d):
    say(d, "a", "안녕")
    d.noticed("g", "a", NOW.date())
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
    told = words_of(say(d, "b", "점메추?"))
    assert "농민백암순대" not in told and "점메추…?" in told  # b 에게는 모르는 말 (a 가 알려 준 뜻을 안 씀)


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


def test_no_teaching_offer_on_the_guide_turn(d):
    talk = say(d, "a", "점메추?")
    assert talk.notice is True and "무슨 뜻인지" not in words_of(talk)


def test_unknown_word_in_a_sentence_is_asked_then_learned(d):
    noticed("a")
    asked = say(d, "a", "아샷추 마시고 싶다")
    assert "아샷추" in words_of(asked) and "무슨 뜻인지 알려 줄래?" in words_of(asked)
    assert "알았어" in words_of(say(d, "a", "아이스티에 샷 추가라는 뜻이야"))
    [gloss] = [t for t in memory.load("g", "a")["taught"] if t["kind"] == "word"]
    assert gloss["words"] == ["아샷추"] and gloss["means"] == "아이스티에 샷 추가"
    assert "아이스티에 샷 추가" in words_of(say(d, "a", "아샷추가 뭐야?"))


def test_ignored_word_is_known_and_not_asked_again(d):
    noticed("a")
    say(d, "a", "아샷추 마시고 싶다")
    say(d, "a", "ㅋㅋ 아무튼")  # 설명 없이 넘어감
    assert "아샷추" in memory.load("g", "a")["known"]
    later = NOW + timedelta(minutes=11)
    assert "무슨 뜻인지" not in words_of(say(d, "a", "아샷추 또 마시고 싶다", now=later))


def test_one_word_question_per_ten_minutes(d):
    noticed("a")
    say(d, "a", "아샷추 마시고 싶다")
    assert "무슨 뜻인지" not in words_of(say(d, "a", "점메추 하자", now=NOW + timedelta(minutes=3)))
    asked = say(d, "a", "점메추 하자", now=NOW + timedelta(minutes=11))
    assert "점메추" in words_of(asked) and "무슨 뜻인지" in words_of(asked)


def test_word_questions_only_for_remembering_people(d):
    noticed("a")
    noticed("b")
    before = files()
    off = say(d, "a", "아샷추 마시고 싶다", translating=False)  # 번역이 꺼져 있으면 묻지 않음
    other = say(d, "b", "아샷추 마시고 싶다", thread="ta")  # 남의 스레드
    assert off.plain and other.plain and files() == before


def test_glossed_word_in_chat_shows_it_knows(d):
    mem = memory.new()
    mem["noticed"] = TODAY
    mem["taught"] = [{"words": ["아샷추"], "kind": "word", "means": "아이스티에 샷 추가", "at": TODAY}]
    memory.save("g", "a", mem)
    remarks = [d.respond(guild_id="g", thread_id="ta", author_id="a", owner_id="own", text="아샷추 마시고 싶다",
                         now=NOW, translating=True, rng=random.Random(seed)).remark for seed in range(20)]
    assert any(r and "아샷추면 아이스티에 샷 추가지?" in r for r in remarks)
    assert not all(remarks)  # 늘 그러지는 않음
