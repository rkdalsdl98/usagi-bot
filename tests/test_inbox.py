"""들어온 순서대로 하나씩 처리하는 줄: 버튼 서버가 요청마다 스레드를 띄워도 같은 파일을 함께 고쳐 쓰지 않는다."""
import threading
import time

import pytest

from lunchbot import inbox
import interaction


def test_inputs_at_the_same_moment_do_not_overwrite_each_other():
    box = inbox.Inbox()
    saved = {"answers": []}

    def answer(n):  # 게임 답처럼 읽고, 고치고, 다시 씀
        answers = list(saved["answers"])
        time.sleep(0.01)
        saved["answers"] = answers + [n]

    people = [threading.Thread(target=box.ask, args=(answer, n)) for n in range(8)]
    for p in people:
        p.start()
    for p in people:
        p.join()
    assert sorted(saved["answers"]) == list(range(8))  # 하나도 빠지지 않음


def test_one_at_a_time_in_the_order_put():
    box = inbox.Inbox()
    seen, running, most = [], [0], [0]

    def job(n):
        running[0] += 1
        most[0] = max(most[0], running[0])
        time.sleep(0.005)
        seen.append(n)
        running[0] -= 1

    for n in range(5):
        box.after([lambda n=n: job(n)], interaction.run_later)
    box.ask(lambda: None)  # 앞에 넣은 일이 다 끝난 뒤에 차례가 옴
    assert seen == [0, 1, 2, 3, 4] and most[0] == 1


def test_ask_returns_the_answer_and_a_failure_does_not_stop_the_line():
    box = inbox.Inbox()
    assert box.ask(lambda a, b: a + b, 2, 3) == 5
    with pytest.raises(ZeroDivisionError):
        box.ask(lambda: 1 / 0)
    assert box.ask(lambda: "다음") == "다음"


def test_slow_jobs_run_aside_after_the_quick_ones():
    # 명령으로 부른 메뉴 추천은 1분 안팎 걸릴 수 있어서 줄을 막지 않게 따로 돌림
    box = inbox.Inbox()
    order, started, release = [], threading.Event(), threading.Event()

    def recommend():
        order.append("추천 시작")
        started.set()
        release.wait(5)

    box.after([lambda: order.append("하치와레 안내"), inbox.slow(recommend)], interaction.run_later)
    assert started.wait(2)
    assert box.ask(lambda: "다음 입력") == "다음 입력"  # 추천이 끝나기 전에도 다음 입력을 처리
    assert order == ["하치와레 안내", "추천 시작"]
    release.set()
