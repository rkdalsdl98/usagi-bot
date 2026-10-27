"""우사기 채널: 사람이 채팅을 보내면 우사기 봇이 우사기 소리로 답한다.

우사기는 말을 하지 않으므로 소리만 내지만, 채팅 내용(질문, 피곤함, 배고픔, 웃음 …)과 길이에 따라
답하는 모양이 달라져서 진짜 대답하는 것처럼 보여야 한다. 채팅 내용을 못 읽으면(권한 없음) 무작위로 답한다.
"""
import random
import re
import unicodedata

import pytest

from lunchbot import chat

USAGI = "1563160909075972129"
TRILL = re.compile("푸르{3,}")

QUESTION = "점심 뭐 먹지?"
SAD = "오늘도 야근이라 너무 피곤하다 ㅠㅠ"
FOOD = "배고파 고기 먹고 싶다"
LAUGH = "ㅋㅋㅋㅋㅋ"
PRAISE = "우사기 귀여워 최고야"
GREETING = "안녕 우사기"
LONG = "오늘 회의가 세 개나 있었는데 하나는 두 시간이나 걸렸고 끝나고 나니까 벌써 저녁이라서 아무것도 못 했어"
INPUTS = [QUESTION, SAD, FOOD, LAUGH, PRAISE, GREETING, LONG, "우라!", "ㅇ", "헐 대박", "짜증나 진짜", ""]


def replies(text, n=200):
    return [chat.reply(text, random.Random(seed)) for seed in range(n)]


def words(line):
    return [w.strip("!?…~") for w in line.split()]


def share(lines, pred):
    return sum(1 for l in lines if pred(l)) / len(lines)


def test_replies_only_to_people_in_the_usagi_channel():
    assert chat.should_reply(author_is_bot=False, channel_id=USAGI, usagi_channel_id=USAGI) is True
    assert chat.should_reply(author_is_bot=True, channel_id=USAGI, usagi_channel_id=USAGI) is False  # 자기 자신·다른 봇
    assert chat.should_reply(author_is_bot=False, channel_id="1563162334376239165", usagi_channel_id=USAGI) is False
    assert chat.should_reply(author_is_bot=False, channel_id=USAGI, usagi_channel_id="") is False  # 채널을 안 정했으면 조용히


def test_replies_in_threads_under_the_usagi_channel():
    # /우사기 로 만든 1:1 비공개 스레드는 우사기 채널 아래에 있다
    assert chat.should_reply(author_is_bot=False, channel_id="t1", usagi_channel_id=USAGI, parent_id=USAGI) is True
    assert chat.should_reply(author_is_bot=False, channel_id="t2", usagi_channel_id=USAGI,
                             parent_id="1563162334376239165") is False  # 다른 채널의 스레드
    assert chat.should_reply(author_is_bot=True, channel_id="t1", usagi_channel_id=USAGI, parent_id=USAGI) is False


def test_only_usagi_sounds_and_not_too_short_or_long():
    for text in INPUTS:
        for line in replies(text, 100):
            assert all(w in chat.VOCAB or TRILL.fullmatch(w) for w in words(line)), (text, line)
            assert [ch for ch in line if unicodedata.category(ch) == "So"] == [], line  # 이모티콘 없음
            assert 2 <= len(line) <= 40, (text, line)


def test_reply_length_follows_the_chat():
    short = replies("ㅇ")
    long = replies(LONG)
    avg = lambda lines: sum(len(words(l)) for l in lines) / len(lines)  # noqa: E731
    assert avg(short) <= 1.6 < 2.2 <= avg(long)


def test_question_gets_a_puzzled_sound_first():
    assert share(replies(QUESTION), lambda l: l.split()[0].endswith("?")) >= 0.8


def test_tired_or_sad_chat_gets_soft_sounds():
    assert share(replies(SAD), lambda l: any(w in ("후웅", "흐응") or TRILL.fullmatch(w) for w in words(l))) >= 0.8


def test_food_chat_gets_excited():
    lines = replies(FOOD)
    assert share(lines, lambda l: "!" in l and any(w in chat.EXCITED for w in words(l))) >= 0.8
    assert share(lines, lambda l: "?" in l) <= 0.2


def test_laughing_and_praise_get_happy_sounds():
    for text in (LAUGH, PRAISE):
        assert share(replies(text), lambda l: any(w in ("야하", "와앗") for w in words(l))) >= 0.8, text


def test_usagi_sounds_are_echoed_back():
    assert share(replies("우라!"), lambda l: "우라" in l) >= 0.8


def test_greeting_and_call_get_a_hello():
    assert share(replies(GREETING), lambda l: "야하" in l or "야앗" in l) >= 0.8


def test_same_chat_gets_varied_replies_and_moods_differ():
    for text in INPUTS:
        assert len(set(replies(text))) >= 6, text
    # 피곤한 채팅과 배고픈 채팅은 대체로 다르게 답한다
    sad, food = set(replies(SAD)), set(replies(FOOD))
    assert len(sad & food) <= len(sad) * 0.2


def test_never_repeats_the_last_reply():
    rng = random.Random(3)
    last = None
    for _ in range(100):
        steps = chat.plan(FOOD, rng, last=last)
        assert steps[0].text != last
        last = steps[0].text


def test_plan_looks_like_typing_a_reply():
    for seed in range(300):
        steps = chat.plan(LONG if seed % 2 else "ㅇ", random.Random(seed))
        assert 1 <= len(steps) <= 2
        assert all(0.3 <= s.delay <= 3.0 for s in steps)  # '입력 중…' 을 보여 줄 시간
        if len(steps) == 2:  # 가끔 짧게 한마디 더
            assert steps[1].quote is False and len(words(steps[1].text)) == 1
    plans = [chat.plan(QUESTION, random.Random(s)) for s in range(300)]
    assert 0.1 <= share(plans, lambda p: len(p) == 2) <= 0.3
    assert 0.2 <= share(plans, lambda p: not p[0].quote) <= 0.6  # 늘 답장 표시를 다는 건 아님
    # 긴 답은 입력 시간도 길다
    short = [chat.plan("ㅇ", random.Random(s))[0] for s in range(200)]
    long = [chat.plan(LONG, random.Random(s))[0] for s in range(200)]
    assert sum(s.delay for s in short) / 200 < sum(s.delay for s in long) / 200


def test_read_tells_what_the_chat_is():
    # 우사기가 목소리를 고르고, 하치와레가 번역할 때 함께 쓰는 해석
    assert chat.read(QUESTION) == chat.Reading("food", asking=True)
    assert chat.read("야근인데 배고파 ㅠ") == chat.Reading("sad", then="food")
    assert chat.read(GREETING) == chat.Reading("greet")  # '우사기' 부르기는 둘째 종류로 치지 않음
    assert chat.read("ㅎㅇ") == chat.Reading("greet")  # 앞의 ㅎ 을 웃음으로 떼어 내 ㅇ(맞장구)으로 읽지 않음
    assert chat.read("응ㅋㅋ") == chat.Reading("laugh", then="agree")  # 뒤에 붙은 ㅋㅋ 를 떼면 '응' 도 보임
    assert chat.read("우라!") == chat.Reading("echo", sounds=("우라",))
    assert chat.read("음 그렇구나").kind == "plain"
    assert chat.read("").kind == "unknown"
    assert chat.read("<@1563160909075972129>").kind == "unknown"  # 멘션만 있으면 읽을 내용이 없음


def test_without_message_content_still_replies():
    # 채팅 내용을 못 읽으면 빈 글자로 들어온다
    lines = replies("")
    assert all(words(l) for l in lines) and len(set(lines)) >= 10


@pytest.mark.parametrize("text, kind", [
    ("내일 출장이라 걱정돼", "worry"), ("발표 때문에 불안해", "worry"), ("면접이라 긴장돼", "worry"), ("떨려 죽겠어", "worry"),
    ("드디어 끝이다", "done"), ("오늘 업무 마무리 중이야", "done"), ("보고서 다 했다", "done"), ("합격했어!", "done"),
    ("휴 다행이다", "done"), ("요즘 너무 바빠", "sad"), ("스트레스 받아", "sad"), ("너무 아쉽다", "sad"),
    ("끝났는데 너무 피곤해", "sad"), ("드디어 퇴근", "bye")])
def test_reads_everyday_feelings(text, kind):
    assert chat.read(text).kind == kind


def test_worry_gets_soft_sounds_and_done_gets_excited():
    soft = ("후웅", "흐응")
    assert share(replies("내일 출장이라 걱정돼"), lambda l: words(l)[0] in soft) >= 0.8
    assert share(replies("드디어 끝이다"), lambda l: words(l)[0] in ("야하", "와앗")) >= 0.8
