"""이미지 랜덤 주제 게임의 규칙 (디스코드와 상관없는 진행 상태).

주제를 정하고 참가자를 고른 뒤 시작한다. 라운드마다 아직 술래가 안 된 사람 중 한 명이 술래가 되고(중복 없음),
술래를 뺀 사람 중 한 명이 사회자가 된다. 술래를 뺀 참가자가 답을 내면, 사회자만 답과 쓴 사람을 짝지어 본다.
사회자가 술래가 맞힌 수를 알려 주면 술래 점수에 더하고 다음 라운드로 간다. 모두 한 번씩 술래가 되면 끝난다.
"""
import random

import pytest

from lunchbot import game
from lunchbot.game import GameError

P = ["a", "b", "c", "d"]


def started(players=P, seed=1):
    g = game.new("첫인상", "a")
    game.set_players(g, players, {p: p.upper() for p in players})
    game.start(g, "a", random.Random(seed))
    return g


def test_setup_then_start():
    g = game.new("첫인상", "a")
    assert g["status"] == "setup" and g["topic"] == "첫인상" and g["starter"] == "a"
    with pytest.raises(GameError, match="too_few"):
        game.set_players(g, ["a", "b"], {}), game.start(g, "a", random.Random(1))  # 셋은 있어야 함
    game.set_players(g, P, {p: p.upper() for p in P})
    with pytest.raises(GameError, match="not_starter"):
        game.start(g, "b", random.Random(1))  # 시작한 사람만 시작
    game.start(g, "a", random.Random(1))
    assert g["status"] == "playing" and g["round"] == 1
    assert g["it"] in P and g["host"] in P and g["host"] != g["it"]
    assert g["scores"] == {p: 0 for p in P}


def test_everyone_is_it_exactly_once_and_host_is_never_it():
    for seed in range(30):
        g = started(seed=seed)
        its = []
        while g["status"] == "playing":
            its.append(g["it"])
            assert g["host"] != g["it"]
            for p in P:
                if p != g["it"]:
                    game.answer(g, p, f"{p}의 생각")
            game.result(g, g["host"], 1, random.Random(seed))
        assert sorted(its) == sorted(P)  # 중복 없이 모두 한 번씩
        assert g["status"] == "done" and g["round"] == len(P)


def test_answers_are_hidden_and_only_for_the_host():
    g = started()
    it, host = g["it"], g["host"]
    others = [p for p in P if p != it]
    with pytest.raises(GameError, match="is_it"):
        game.answer(g, it, "나는 술래")  # 술래는 답을 내지 않음
    with pytest.raises(GameError, match="not_player"):
        game.answer(g, "zz", "구경꾼")
    game.answer(g, others[0], "처음 생각")
    game.answer(g, others[0], "바꾼 생각")  # 다시 내면 바뀜
    assert game.progress(g) == (1, len(others))
    with pytest.raises(GameError, match="not_host"):
        game.reveal(g, it, random.Random(1))
    shown, missing = game.reveal(g, host, random.Random(1))
    assert shown == [("바꾼 생각", others[0])] and set(missing) == set(others[1:])  # 아직 안 낸 사람도 알려 줌


def test_reveal_order_is_shuffled():
    orders = set()
    for seed in range(20):
        g = started(players=["a", "b", "c", "d", "e", "f"])
        for p in g["players"]:
            if p != g["it"]:
                game.answer(g, p, p)
        orders.add(tuple(t for t, _ in game.reveal(g, g["host"], random.Random(seed))[0]))
    assert len(orders) > 1  # 늘 같은 순서면 쓴 사람이 짐작됨


def test_host_reports_how_many_the_it_got():
    g = started()
    it, host = g["it"], g["host"]
    for p in P:
        if p != it:
            game.answer(g, p, "생각")
    with pytest.raises(GameError, match="not_host"):
        game.result(g, it, 2, random.Random(1))
    with pytest.raises(GameError, match="bad_count"):
        game.result(g, host, 4, random.Random(1))  # 답이 3개인데 4개를 맞힐 수 없음
    game.result(g, host, 2, random.Random(1))
    assert g["scores"][it] == 2 and g["round"] == 2 and g["it"] != it
    assert game.scoreboard(g)[0] == (it, 2)


def test_end_by_starter_or_captain():
    g = started()
    with pytest.raises(GameError, match="not_starter"):
        game.end(g, "b", captain=False)
    game.end(g, "b", captain=True)
    assert g["status"] == "done"
    with pytest.raises(GameError, match="not_running"):
        game.answer(g, "c", "늦은 답")
