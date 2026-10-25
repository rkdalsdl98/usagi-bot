"""하치와레(웹훅): 우사기가 낸 소리를 사람들에게 번역해 준다.

우사기 소리 한 토막마다 하치와레 말 한 토막이 짝을 이룬다. 소리가 둘이면 번역도 두 토막이고,
번역 토막의 끝맺음(!, ~, …, ?)과 소리의 끝맺음이 같다. 그래서 '우라!' 한마디에 긴 문장이 붙지 않는다.
메뉴 추천·투표 결과·명령은 소리와 번역을 함께 만들고(Script), 우사기 채널 대화는 우사기가 이미 낸 소리를
토막마다 번역한다(chunks). 하치와레는 짧은 틀('"…"래!')로만 전한다.
"""
import random
import unicodedata

import pytest

from lunchbot import chat, hachiware

KINDS = [kind for kind, _ in chat.KINDS]
ENDS = ("…?", "?", "!", "~", "…")
SOUND_WORDS = chat.VOCAB


def ending(text):
    return next((e for e in ENDS if text.endswith(e)), "")


def translations(reading, usagi, n=200, **kw):
    return [hachiware.translate(reading, usagi, random.Random(seed), **kw) for seed in range(n)]


def stem(chunk):
    return chunk.rstrip("!?…~")  # 끝맺음은 소리에 맞춰 바뀔 수 있음


def quoted(line):
    return line.split('"')[1]  # 따옴표 안: 하치와레가 옮긴 우사기 말 (밖은 하치와레 자기 생각)


def has(line, kind):
    return any(stem(m) in quoted(line) for m in hachiware.MEANINGS[kind])


def share(lines, pred):
    return sum(1 for l in lines if pred(l)) / len(lines)


def assert_paired(script):
    """소리 토막과 번역 토막이 하나씩 짝이고, 끝맺음이 같다."""
    tokens = script.sound.split()
    assert len(tokens) == len(script.parts) >= 1, script
    for (sound, chunk), token in zip(script.parts, tokens):
        assert sound == token and token.strip("!?…~") in SOUND_WORDS | {"푸르르르", "푸르르르르", "푸르르르르르"}, script
        if ending(chunk):
            assert ending(token) == ending(chunk), script
    assert script.text == " ".join(chunk for _, chunk in script.parts)


# ── 메뉴 추천 · 투표 결과 · 명령: 소리와 번역을 함께 만든다 ──

def test_recommendation_script():
    picks = [{"name": "국밥집", "category": "한식"}, {"name": "이자카야", "category": "술집"}]
    lunch = [hachiware.recommend_script("lunch", picks[:1], latest="KFC 강남역점", rng=random.Random(s)) for s in range(200)]
    dinner = [hachiware.recommend_script("dinner", picks, today_lunch="KFC 강남역점", rng=random.Random(s))
              for s in range(200)]
    for script in lunch + dinner:
        assert_paired(script)
        assert 2 <= len(script.parts) <= 4
    assert len({s.sound for s in lunch}) >= 30 and len({s.text for s in lunch}) >= 20  # 단조롭지 않게
    assert share(lunch, lambda s: "'KFC 강남역점'" in s.text) >= 0.3  # 지난번 간 곳을 가끔 짚음
    assert share(dinner, lambda s: "술집" in s.text or "점심" in s.text) >= 0.3  # 술집 자리, 점심 뺀 것
    assert all("술집" not in s.text for s in lunch)


def test_result_script():
    won = [hachiware.result_script("농민백암순대", random.Random(s)) for s in range(100)]
    for script in won:
        assert_paired(script)
        assert "농민백암순대" in script.text
    none = [hachiware.result_script(None, random.Random(s)) for s in range(100)]
    for script in none:
        assert_paired(script)
        assert all(sound.strip("!?…~") in ("후웅", "흐응") or sound.startswith("푸르") for sound, _ in script.parts)
    assert len({s.text for s in won}) >= 4


@pytest.mark.parametrize("key, kw", [
    ("rank_low", {"need": "**직장인 갑옷씨**", "now": "**행인 갑옷씨**"}),
    ("added", {"target": "<@1>"}), ("promoted", {"target": "<@1>", "new": "직장인 갑옷씨"}),
    ("demoted", {"target": "<@1>", "new": "행인 갑옷씨"}), ("removed", {"target": "<@1>"}),
    ("kick_failed", {"target": "<@1>"}), ("recommend", {"channel": "<#42>", "meal": "점심"}),
    ("no_channel", {"meal": "저녁", "setting": "DINNER_CHANNEL_ID"}), ("unknown", {}),
])
def test_notice_scripts_are_paired(key, kw):
    for seed in range(30):
        script = hachiware.notice_script(key, random.Random(seed), **kw)
        assert_paired(script)
        assert all(v in script.text for v in kw.values() if v != "DINNER_CHANNEL_ID") or "DINNER_CHANNEL_ID" in script.text


def test_every_command_result_has_a_script():
    kw = {"actor": "<@1>", "target": "<@2>", "need": "n", "now": "w", "rank": "r", "target_rank": "t", "new": "x",
          "channel": "<#1>", "meal": "점심", "setting": "S", "thread": "<#t1>"}
    for key in hachiware.NOTICES:
        assert_paired(hachiware.notice_script(key, random.Random(1), **kw))


def test_kick_is_a_single_ura():
    script = hachiware.notice_script("kicked", random.Random(1), target="<@1>")
    assert script.sound == "우라!" and "<@1>" in script.text and len(script.parts) == 1


def test_relay_is_short():
    for seed in range(50):
        line = hachiware.relay("밥! 고기!", random.Random(seed))
        assert "밥! 고기!" in line and len(line) <= len("밥! 고기!") + 10


# ── 우사기 채널 대화: 우사기가 낸 소리를 토막마다 번역한다 ──

def test_one_chunk_per_sound():
    cases = [(chat.Reading("greet"), "야앗!"), (chat.Reading("sad"), "후웅… 흐응~ 푸르르르…"),
             (chat.Reading("food", asking=True), "하? 우라! 야하!"), (chat.Reading("laugh"), "야하 야하 와앗!"),
             (chat.Reading("plain"), "푸르르르르~ 와앗!"), (chat.Reading("unknown"), "야하~")]
    for reading, usagi in cases:
        for seed in range(50):
            assert len(hachiware.chunks(reading, usagi, random.Random(seed))) == len(usagi.split()), usagi


def test_chunk_endings_follow_the_sound():
    lines = [hachiware.chunks(chat.Reading("sad"), "후웅… 흐응~", random.Random(s)) for s in range(100)]
    assert share(lines, lambda c: c[0].endswith("…") and c[1].endswith("~")) >= 0.8


def test_translation_is_short_and_safe():
    cases = [(chat.Reading(k), "야하!") for k in KINDS] + [
        (chat.Reading("food", asking=True), "하? 우라!"),
        (chat.Reading("sad", then="food"), "후웅… 이얏 이얏!"),
        (chat.Reading("echo", sounds=("우라",)), "우라! 야하~"),
        (chat.Reading("plain"), "푸르르르르~ 와앗!"),
        (chat.Reading("unknown"), "야하~"),
    ]
    for reading, usagi in cases:
        for line in translations(reading, usagi, 50, name="한강민"):
            assert 4 <= len(line) <= 80, line
            assert [ch for ch in line if unicodedata.category(ch) == "So"] == [], line  # 이모티콘 없음
            assert "@" not in line, line  # 멘션 알림을 만들지 않음
    # 한 소리에는 짧게: '야앗!' 에 두 문장을 옮기지 않음 (하치와레 자기 생각은 따옴표 밖이라 따로)
    assert all(len(quoted(l)) <= 10 for l in translations(chat.Reading("greet"), "야앗!")), "한 소리 번역이 길다"


def test_says_what_usagi_meant():
    for kind in KINDS:
        assert share(translations(chat.Reading(kind), "야하!"), lambda l: has(l, kind)) == 1, kind


def test_question_is_answered_after_a_puzzled_sound():
    asked = chat.Reading("food", asking=True)
    assert all(has(l, "ask") and has(l, "food") for l in translations(asked, "하? 우라!"))
    assert all(has(l, "ask") and not has(l, "food") for l in translations(asked, "후웅…?"))  # 갸웃만 했을 때
    assert all(not has(l, "ask") and has(l, "food") for l in translations(asked, "우라!"))  # 갸웃 없이 바로 답했을 때


def test_mixed_chat_gets_both_meanings_when_usagi_said_more():
    mixed = chat.Reading("sad", then="food")
    assert all(has(l, "sad") and has(l, "food") for l in translations(mixed, "후웅… 이얏 이얏!"))
    assert all(has(l, "sad") and not has(l, "food") for l in translations(mixed, "후웅…"))


def test_repeated_sound_repeats_the_chunk():
    for seed in range(50):
        c = hachiware.chunks(chat.Reading("laugh"), "야하 야하!", random.Random(seed))
        assert c[0].rstrip("!?…~") == c[1].rstrip("!?…~")


def test_echo_and_unread_chats():
    assert all(has(l, "echo") for l in translations(chat.Reading("echo", sounds=("우라",)), "우라! 야하~"))
    # 어느 종류도 아니거나 내용을 못 읽었으면 우사기가 낸 소리의 느낌으로 풀어 준다
    assert all(any(stem(m) in quoted(l) for m in hachiware.SOUNDS["후웅"])
               for l in translations(chat.Reading("plain"), "후웅…"))
    assert all(any(stem(m) in quoted(l) for m in hachiware.SOUNDS[chat.T])
               for l in translations(chat.Reading("plain"), "푸르르르르~"))
    assert all(any(stem(m) in quoted(l) for m in hachiware.SOUNDS["야하"])
               for l in translations(chat.Reading("unknown"), "야하!"))


def test_varied_and_never_repeats_the_last_translation():
    assert len(set(translations(chat.Reading("greet"), "야하!"))) >= 10
    rng, last = random.Random(5), None
    for _ in range(100):
        line = hachiware.translate(chat.Reading("food"), "우라!", rng, last=last)
        assert line != last
        last = line


def test_sometimes_talks_to_the_person():
    lines = translations(chat.Reading("sad"), "흐응…", 300, name="한강민")
    assert 0.1 <= share(lines, lambda l: l.startswith("한강민, ")) <= 0.4
    assert all("한강민" not in l for l in translations(chat.Reading("sad"), "흐응…"))  # 이름을 모르면 부르지 않음


def test_different_sounds_get_different_chunks():
    for seed in range(200):
        c = hachiware.chunks(chat.Reading("sad"), "흐응 푸르르르… 흐응… 푸르르르~", random.Random(seed))
        stems = [stem(x) for x in c]
        assert stems[0] != stems[1] and len(set(stems)) >= 3, c  # 같은 소리를 잇달아 낸 게 아니면 다른 말



def test_hachiware_adds_her_own_thought_sometimes():
    lines = translations(chat.Reading("food"), "우라!", 300)
    thoughts = hachiware.COMMENTS["food"]
    with_thought = [l for l in lines if any(t in l for t in thoughts)]
    assert 0.2 <= len(with_thought) / len(lines) <= 0.5  # 10번에 3~4번
    for line in with_thought:  # 번역(따옴표 안) 다음에, 따옴표 밖에 붙임
        thought = next(t for t in thoughts if t in line)
        assert line.rindex('"') < line.index(thought) and thought not in quoted(line)
    assert len(set(lines)) >= 15


def test_every_kind_has_her_thoughts():
    for kind in KINDS + ["echo", "plain", "unknown"]:
        assert hachiware.COMMENTS.get(kind), kind


@pytest.mark.parametrize("about, kw", [("lunch", {}), ("dinner", {}), ("won", {"name": "농민백암순대"}), ("none", {})])
def test_menu_translation_sometimes_adds_her_thought(about, kw):
    lines = [hachiware.retell("점심이다! 골라 줘!", about, random.Random(s), **kw) for s in range(300)]
    assert all(quoted(l) == "점심이다! 골라 줘!" for l in lines)  # 따옴표 안은 번역 그대로
    thoughts = [t.format(**kw) for t in hachiware.COMMENTS[about]]
    with_thought = [l for l in lines if any(t in l for t in thoughts)]
    assert 0.2 <= len(with_thought) / len(lines) <= 0.5  # 가끔 (10번에 3~4번)
    assert all(l.rindex('"') < l.index(next(t for t in thoughts if t in l)) for l in with_thought)  # 따옴표 밖



def test_greeting_in_the_1on1_thread_is_paired():
    for seed in range(30):
        assert_paired(hachiware.greet_script(random.Random(seed)))
