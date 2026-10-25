import random
import re
import unicodedata

import pytest

from lunchbot import messages

TRILL = re.compile("푸르{3,}")  # 푸르르르, 푸르르르르 … 떨림 소리
CASES = [
    # 만드는 함수, 쓸 수 있는 소리 조각, 떨림 소리 허용
    (messages.recommend_sound, messages.EXCITED, True),
    (messages.picked_sound, messages.HAPPY, False),
    (messages.skipped_sound, messages.SULKY, True),
    (messages.huh_sound, messages.PUZZLED, False),
]


def lines_of(make, n=300):
    return [make(random.Random(seed)) for seed in range(n)]


def words(line):
    return [w.strip("!?…~") for w in line.split(" ")]


@pytest.mark.parametrize("make, pool, trill", CASES)
def test_only_usagi_sounds_and_short(make, pool, trill):
    for line in lines_of(make):
        ws = words(line)
        assert 1 <= len(ws) <= 3, line
        assert all(w in pool or (trill and TRILL.fullmatch(w)) for w in ws), line
        assert [ch for ch in line if unicodedata.category(ch) == "So"] == [], line  # 이모티콘 없음


@pytest.mark.parametrize("make", [messages.recommend_sound, messages.picked_sound])
def test_double_bang_is_rare_and_shapes_vary(make):
    lines = lines_of(make)
    # '!!' 는 가끔만 나온다
    assert sum("!!" in l for l in lines) / len(lines) <= 0.2
    # 느낌표 없이 끝나는 줄(물결, 반복 등)도 섞여 나온다
    assert any("!" not in l for l in lines)
    # 조각만 바꾼 같은 모양이 아니라, 모양 자체가 여러 가지다 (예: 'X!', 'X X', 'X~', 'X! Y~')
    shapes = {re.sub(r"[가-힣]+", "X", l) for l in lines}
    assert len(shapes) >= 4, shapes


def test_usagi_sometimes_repeats_a_sound():
    # '우라 우라' 처럼 같은 소리를 두 번 내는 모양이 있다
    assert any(len(set(words(l))) < len(words(l)) for l in lines_of(messages.recommend_sound))


def test_huh_is_a_single_puzzled_sound():
    for line in lines_of(messages.huh_sound):
        assert len(line.split(" ")) == 1 and line.endswith("?"), line
