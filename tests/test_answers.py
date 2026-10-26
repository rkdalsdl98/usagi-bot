"""1:1 대화의 답: 봇이 실제로 아는 정보로 채우고, 모르면 아는 척하지 않고 되묻는다."""
import random
from datetime import date, datetime, timedelta

import pytest

from lunchbot import answers, birthdays, chat, config, memory, storage, talk
from test_flow import aws  # noqa: F401 (aws 는 fixture)

NOW = datetime(2026, 10, 26, 17, 20, tzinfo=config.KST)  # 월요일
TODAY = NOW.date().isoformat()
PICKS = [{"name": n, "distance_m": d, "address": f"서울 강남구 {n}"} for n, d in
         (("농민백암순대", 230), ("라멘집", 310), ("국밥집", 120), ("파스타집", 400), ("쌀국수집", 520))]


def rng():
    return random.Random(7)


def turn(topic, ask):
    return talk.Turn("question", topic, ask)


def facts(**kw):
    base = dict(picks=[], winner=None, dinner_picks=[], dinner_winner=None, latest=None, birthday=None, score=None,
                rank=2, now=NOW)
    return answers.Facts(**{**base, **kw})


def ctx(**kw):
    base = {"topic": None, "ask": None, "target": None, "asked": None, "unknown": None, "at": NOW}
    return talk.Context(**{**base, **kw})


def paired(script):
    return len(script.sound.split()) == len(script.parts) >= 1


@pytest.mark.parametrize("pair", sorted(answers.SUPPORTED))
def test_every_answer_pairs_sound_and_words(pair):
    for f in (facts(), facts(picks=PICKS, winner=PICKS[0], latest=PICKS[0], birthday=(3, 5), score=4)):
        for mem in (None, memory.new()):
            reply = answers.answer(turn(*pair), f, mem, ctx(target="농민백암순대"), rng())
            assert paired(reply.script), pair


def test_supported_also_takes_short_follow_ups():
    assert answers.supported("lunch", "what") and answers.supported("lunch", "why") and answers.supported("game", "really")
    assert not answers.supported("lunch", "who") and not answers.supported(None, "why")


def test_lunch_answer_uses_todays_vote():
    reply = answers.answer(turn("lunch", "what"), facts(picks=PICKS, winner=PICKS[0]), None, None, rng())
    assert "농민백암순대" in reply.script.text and reply.target == "농민백암순대"


def test_lunch_answer_before_any_recommendation():
    reply = answers.answer(turn("lunch", "what"), facts(), None, None, rng())
    assert paired(reply.script) and reply.target is None
    assert not any(p["name"] in reply.script.text for p in PICKS)


def test_what_to_eat_picks_one_of_todays_five():
    reply = answers.answer(turn("food", "what"), facts(picks=PICKS), None, None, rng())
    assert reply.target in {p["name"] for p in PICKS} and reply.target in reply.script.text


def test_there_is_the_last_place():
    f = facts(picks=PICKS)
    reply = answers.answer(turn("place", "where"), f, None, ctx(target="라멘집"), rng())
    assert "310" in reply.script.text and reply.target == "라멘집"
    reply = answers.answer(turn("place", "how"), f, None, ctx(), rng())  # 무엇을 말하는지 모름
    assert reply.target is None


def test_time_and_off_work():
    assert "5시 20분" in answers.answer(turn("time", "what"), facts(), None, None, rng()).script.text
    assert "40분" in answers.answer(turn("off", "when"), facts(), None, None, rng()).script.text
    weekend = facts(now=NOW + timedelta(days=5))
    assert "40분" not in answers.answer(turn("off", "when"), weekend, None, None, rng()).script.text


def test_my_birthday_rank_and_score():
    assert "3월 5일" in answers.answer(turn("birthday", "when"), facts(birthday=(3, 5)), None, None, rng()).script.text
    assert "대장 갑옷씨" in answers.answer(turn("rank", "what"), facts(rank=3), None, None, rng()).script.text
    assert "4점" in answers.answer(turn("game", "what"), facts(score=4), None, None, rng()).script.text


def test_memory_answers_need_memory():
    mem = memory.new()
    mem["likes"] = ["치킨", "라멘"]
    mem["last_seen"] = (NOW.date() - timedelta(days=3)).isoformat()
    assert "라멘" in answers.answer(turn("me", "like"), facts(), mem, None, rng()).script.text
    assert "3일 전" in answers.answer(turn("talk", "when"), facts(), mem, None, rng()).script.text
    blind = answers.answer(turn("me", "like"), facts(), None, None, rng())  # 기억을 못 쓰는 사람
    assert "라멘" not in blind.script.text and "잘 모르겠어" in blind.script.text


def test_gather_reads_what_the_bot_knows(aws):
    storage.put_json(storage.recommendation_key(TODAY), {"date": TODAY, "picks": PICKS})
    storage.put_json(storage.latest_key(), {**PICKS[0], "date": TODAY})
    birthdays.save("g", "a", 3, 5, by="x")
    storage.put_json(storage.members_key("g"), {"members": {"a": {"rank": 2}}})
    storage.put_json(storage.game_key(config.USAGI_CHANNEL_ID), {"status": "playing", "scores": {"a": 4}})
    f = answers.gather("g", "a", "own", NOW)
    assert [p["name"] for p in f.picks] == [p["name"] for p in PICKS] and f.winner["name"] == "농민백암순대"
    assert f.latest["name"] == "농민백암순대" and f.birthday == (3, 5) and f.score == 4 and f.rank == 2
    assert answers.gather("g", "own", "own", NOW).rank == 3  # 서버 주인
    storage.put_json(storage.latest_key(), {**PICKS[0], "date": "2026-10-25"})
    assert answers.gather("g", "a", "own", NOW).winner is None  # 오늘 정해진 것만


def test_unknown_and_learned_fixed_words():
    r = answers.unknown(True, rng())
    assert [w for _, w in r.script.parts] == ["음…?", "잘 모르겠어…"] and r.own == "무슨 뜻인지 알려 줄래?"
    assert answers.unknown(False, rng()).own == ""
    assert [w for _, w in answers.learned(rng()).script.parts] == ["알았어!", "다음엔 그렇게 말할게~"]


def test_reply_to_usagis_question():
    reply = answers.reply_to(talk.Turn("reply", topic="food", words=frozenset({"라멘"})), rng())
    assert "라멘" in reply.script.text and paired(reply.script)
    assert paired(answers.reply_to(talk.Turn("reply", topic="food", words=frozenset({"몰라"})), rng()).script)


def test_taught_answer_is_cut_and_quiet():
    text = "가" * 150 + " <@123> https://x.y"
    reply = answers.taught_answer(text, rng())
    assert len(reply.script.text.replace(" ", "")) <= 100 and 1 <= len(reply.script.parts) <= 4
    reply = answers.taught_answer("오늘도 화이팅 내일도 화이팅 모레도 화이팅 글피도 화이팅 그 뒤도", rng())
    assert 1 <= len(reply.script.parts) <= 4 and paired(reply.script) and "화이팅" in reply.script.text


def test_recall_only_recent_things():
    today = NOW.date()
    mem = memory.new()
    mem["last_seen"] = (today - timedelta(days=1)).isoformat()
    mem["foods"] = [[(today - timedelta(days=1)).isoformat(), "라멘"]]
    greet = chat.read("안녕")
    assert answers.recall(mem, greet, today) == "어제 라멘 먹었어?"
    mem["foods"] = [[(today - timedelta(days=10)).isoformat(), "라멘"]]
    assert answers.recall(mem, greet, today) is None
    mem["moods"] = [[(today - timedelta(days=1)).isoformat(), "sad"]]
    assert answers.recall(mem, greet, today) == "오늘은 좀 괜찮아?"
    mem["last_seen"] = (today - timedelta(days=3)).isoformat()
    assert answers.recall(mem, greet, today) == "3일 만이네!"
    assert answers.recall(mem, chat.read("ㅋㅋㅋ"), today) is None  # 인사일 때만
    assert answers.recall(memory.new(), greet, today) is None


def test_memory_guide_tells_everything():
    for word in ("기분", "좋아", "음식", "가르쳐", "원문", "열쇠", "추방", "/기억 보기", "/기억 지우기"):
        assert word in answers.MEMORY_GUIDE
    guide = answers.guide(rng())
    assert guide.own == answers.MEMORY_GUIDE and paired(guide.script)


@pytest.mark.parametrize("days", [0, 1, 3])
def test_day_words_read_naturally(days):
    mem = memory.new()
    mem["last_seen"] = (NOW.date() - timedelta(days=days)).isoformat()
    latest = {**PICKS[0], "date": (NOW.date() - timedelta(days=days)).isoformat()}
    said = " ".join(answers.answer(turn(t, a), facts(latest=latest), mem, None, rng()).script.text
                    for t, a in (("talk", "when"), ("me", "remember"), ("last", "what")))
    for awkward in ("오늘에", "어제에", "어제엔", "오늘엔"):
        assert awkward not in said
