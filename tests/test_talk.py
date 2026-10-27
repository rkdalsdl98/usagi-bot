"""1:1 대화 읽기: 물음의 화제와 의도, 앞 문맥 이어받기, 가르치는 말 알아보기."""
from datetime import datetime, timedelta

import pytest

from lunchbot import config, talk

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=config.KST)
SUP = {("lunch", "what"), ("dinner", "what"), ("dinner", "when"), ("place", "how"), ("place", "where"), ("usagi", "like")}


def sup(topic, ask):
    return (topic, ask) in SUP


def everything(topic, ask):
    return True


def ctx(**kw):
    base = {"topic": None, "ask": None, "target": None, "asked": None, "unknown": None, "at": NOW}
    return talk.Context(**{**base, **kw})


def read(text, context=None, taught=(), supported=sup, now=NOW):
    return talk.understand(text, context, now, list(taught), supported)


def test_words_drop_particles_and_marks():
    assert talk.words("점심은 뭐야?ㅋㅋ") == {"점심", "뭐야"}
    assert talk.words("나는 너를") == {"나는", "너를"}  # 떼면 한 글자만 남는 것은 그대로


@pytest.mark.parametrize("text, topic, ask", [
    ("오늘 점심 뭐야?", "lunch", "what"), ("점심 정해졌어?", "lunch", "what"), ("저녁 추천 언제 와?", "dinner", "when"),
    ("지난번에 뭐 먹었지?", "last", "what"), ("내 생일 언제로 돼 있어?", "birthday", "when"),
    ("게임 점수 몇 점이야?", "game", "what"), ("내 등급 뭐야?", "rank", "what"), ("지금 몇 시야?", "time", "what"),
    ("퇴근까지 얼마나 남았어?", "off", "when"), ("너 누구야?", "usagi", "who"), ("우사기는 뭐 좋아해?", "usagi", "like"),
    ("밥 먹었어?", "usagi", "eat"), ("하치와레는 누구야?", "hachiware", "who"), ("나 기억해?", "me", "remember"),
    ("내가 뭐 좋아한다고 했지?", "me", "like"), ("우리 마지막으로 언제 얘기했지?", "talk", "when"),
    ("심심해 뭐 하지?", "bored", "what"), ("힘든데 어떡해?", "tired", "how"), ("뭐 먹을까?", "food", "what")])
def test_reads_topic_and_ask(text, topic, ask):
    turn = read(text, supported=everything)
    assert (turn.kind, turn.topic, turn.ask, turn.follow) == ("question", topic, ask, False)


def test_follow_up_keeps_the_ask_and_switches_topic():
    first = read("오늘 점심 뭐야?")
    turn = read("그럼 저녁은?", ctx(topic=first.topic, ask=first.ask))
    assert (turn.kind, turn.topic, turn.ask, turn.follow) == ("question", "dinner", "what", True)


def test_there_means_the_last_place():
    c = ctx(topic="lunch", ask="what", target="농민백암순대")
    assert (read("거기 맛있어?", c).topic, read("거기 맛있어?", c).ask) == ("place", "how")
    assert (read("거기 어디야?", c).topic, read("거기 어디야?", c).ask) == ("place", "where")


def test_short_follow_ups_take_the_topic():
    c = ctx(topic="lunch", ask="what")
    for text, ask in (("왜?", "why"), ("진짜?", "really")):
        turn = read(text, c, supported=everything)
        assert (turn.topic, turn.ask, turn.follow) == ("lunch", ask, True)
    turn = read("너는?", ctx(topic="me", ask="like"), supported=everything)
    assert (turn.topic, turn.ask, turn.follow) == ("usagi", "like", True)


def test_new_topic_is_not_a_follow_up():
    turn = read("우사기는 뭐 좋아해?", ctx(topic="lunch", ask="what"))
    assert (turn.kind, turn.topic, turn.ask, turn.follow) == ("question", "usagi", "like", False)


def test_old_context_is_dropped():
    old = ctx(topic="lunch", ask="what", at=NOW - timedelta(minutes=11))
    assert read("그럼 저녁은?", old).follow is False


def test_unknown_question():
    turn = read("점메추 해줘?")
    assert turn.kind == "unknown" and "점메추" in turn.words


def test_teaching_meaning_and_answer():
    assert talk.teaching("점메추는 점심 메뉴 추천이야", sup) == {"kind": "meaning", "topic": "lunch", "ask": "what"}
    assert talk.teaching("그럴 땐 '오늘도 화이팅'이라고 해 줘", sup) == {"kind": "answer", "answer": "오늘도 화이팅"}
    assert talk.teaching("“힘내!”라고 말해 줘", sup) == {"kind": "answer", "answer": "힘내!"}
    assert talk.teaching("x" * 0 + "'" + "가" * 150 + "'라고 해", sup)["answer"] == "가" * 100
    assert talk.teaching("배고프다", sup) is None
    assert talk.teaching("오늘 점심 뭐야?", sup) is None  # 새 물음은 설명이 아님
    assert talk.teaching("그건 비밀이야", sup) is None  # 아는 의도로 이어지지 않으면 못 배움


def test_teach_only_right_after_unknown():
    words = frozenset({"점메추", "해줘"})
    soon = ctx(unknown=words, at=NOW - timedelta(minutes=4))
    turn = read("점메추는 점심 메뉴 추천이야", soon)
    assert turn.kind == "teach" and turn.words == words
    assert turn.teach == {"kind": "meaning", "topic": "lunch", "ask": "what"}
    late = ctx(unknown=words, at=NOW - timedelta(minutes=6))
    assert read("점메추는 점심 메뉴 추천이야", late).kind != "teach"


def test_taught_meaning_and_answer_are_used():
    taught = [{"words": ["점메추"], "kind": "meaning", "topic": "lunch", "ask": "what", "at": "2026-10-26"},
              {"words": ["힘내", "말해줘"], "kind": "answer", "answer": "오늘도 화이팅", "at": "2026-10-26"}]
    turn = read("점메추 뭐야?", taught=taught)
    assert (turn.kind, turn.topic, turn.ask) == ("question", "lunch", "what")
    assert read("점메추", taught=taught).kind == "question"  # 가르친 말이면 물음표 없어도
    turn = read("힘내 말해줘", taught=taught)
    assert (turn.kind, turn.answer) == ("taught", "오늘도 화이팅")
    assert read("점메추 뭐야?").kind == "unknown"  # 가르친 것을 안 넘기면 모름


def test_reply_to_usagis_question():
    turn = read("라멘", ctx(asked="food"))
    assert (turn.kind, turn.topic) == ("reply", "food") and "라멘" in turn.words
    assert read("오늘 점심 뭐야?", ctx(asked="food")).kind == "question"  # 물음이면 답이 아님


def test_plain_chat_is_chat():
    assert read("ㅋㅋㅋ 웃겨").kind == "chat"
    assert read("배고프다").kind == "chat"


def test_similar():
    assert talk.similar(frozenset({"a", "b"}), frozenset({"a", "b"})) == 1.0
    assert talk.similar(frozenset({"a", "b"}), frozenset({"a", "c"})) == pytest.approx(1 / 3)
    assert talk.similar(frozenset(), frozenset({"a"})) == 0.0


@pytest.mark.parametrize("text, word", [
    ("아샷추 마시고 싶다", "아샷추"), ("점메추", "점메추"), ("아샷추가 너무 좋아", "아샷추"), ("오늘 점메추 해줘", "점메추"),
    ("오늘 회의 너무 길었다", None), ("치킨이랑 맥주 먹고 싶어", None), ("ㅋㅋㅋ 웃겨", None), ("야하 우라", None),
    ("아 진짜 피곤하다", None), ("오늘 점심 뭐야?", None)])
def test_new_word_finds_unknown_nouns_in_any_sentence(text, word):
    assert talk.new_word(text, set()) == word


def test_known_words_are_not_new():
    assert talk.new_word("아샷추 마시고 싶다", {"아샷추"}) is None
    assert talk.new_word("아샷추랑 점메추", {"아샷추"}) == "점메추"


def test_requests_count_as_questions():
    for text in ("점메추 해줘", "아샷추 알아", "아샷추 알려줘"):
        assert read(text).kind == "unknown", text


def test_teaching_a_word_gloss():
    assert talk.teaching("아이스티에 샷 추가라는 뜻이야", sup, word="아샷추") == {"kind": "word", "means": "아이스티에 샷 추가"}
    assert talk.teaching("아샷추는 아이스티에 샷 추가한 거야", sup, word="아샷추") == {"kind": "word",
                                                                         "means": "아이스티에 샷 추가한"}
    assert talk.teaching("점심 메뉴 추천이야", sup, word="점메추") == {"kind": "meaning", "topic": "lunch", "ask": "what"}
    assert talk.teaching("아이스티에 샷 추가라는 뜻이야", sup) is None  # 무슨 낱말의 풀이인지 모르면 못 배움


def test_gloss_question_and_teach_turn():
    gloss = {"words": ["아샷추"], "kind": "word", "means": "아이스티에 샷 추가", "at": "2026-10-26"}
    turn = read("아샷추가 뭐야?", taught=[gloss])
    assert (turn.kind, turn.answer) == ("gloss", "아이스티에 샷 추가") and turn.words == {"아샷추"}
    turn = read("아이스티에 샷 추가라는 뜻이야", ctx(unknown=frozenset({"아샷추"})))
    assert turn.kind == "teach" and turn.teach == {"kind": "word", "means": "아이스티에 샷 추가"}


EVERYDAY = ["이제 끝", "끝이야", "오늘 업무 마무리", "마무리했어", "드디어 금요일이다", "회의 끝나고 보자", "내일 출장이야",
            "요즘 너무 바빠", "그래도 다행이다", "보고서 정리 중이야", "커피 한잔 할래", "스트레스 받아", "택배 왔어",
            "회식 있대", "연차 쓸까", "월급날이다", "고마워 덕분이야", "오늘은 일찍 자야지", "점심 먹으러 가자", "걱정 마",
            "주말에 뭐 하지", "오랜만에 산책했어", "비가 와서 우울해", "감기 걸렸나 봐", "내일 발표 준비해야 돼",
            "팀장님이 칭찬해 주셨어", "프로젝트 마감이라 정신없어", "집에 가고 싶다", "강아지 산책시켜야 해", "운동 좀 해야겠다",
            "오늘 진짜 대박이었어", "그냥 그렇지 뭐", "아무튼 수고했어", "일단 확인해 볼게", "결국 성공했다",
            "아까 말한 거 있잖아", "조금 피곤하네", "다음 주에 휴가야", "메일 확인했어?", "이번 달 너무 길다"]


@pytest.mark.parametrize("text", EVERYDAY)
def test_everyday_words_are_not_new(text):
    assert talk.new_word(text, set()) is None


@pytest.mark.parametrize("text, word", [("아샷추 먹고 싶어", "아샷추"), ("핑프 인정", "핑프"), ("갓생 살자", "갓생"),
                                        ("점메추 해줘", "점메추"), ("이번 주말엔 꾸안꾸로", "꾸안꾸")])
def test_slang_is_still_new(text, word):
    assert talk.new_word(text, set()) == word
