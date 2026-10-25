"""들어온 순서대로 하나씩 처리하는 줄 (로컬 버튼 서버 scripts/serve_local.py).

버튼 서버는 요청마다 스레드를 띄웁니다. 그대로 두면 거의 같은 순간에 온 두 입력이 같은 파일(게임 상태, 멤버 목록,
생일 …)을 함께 읽고 고쳐 써서 한쪽 변경이 사라질 수 있습니다. 그래서 입력과 응답 뒤에 할 일을 모두 이 줄에 넣고,
일꾼 스레드 하나가 넣은 순서대로 하나씩 처리합니다.

오래 걸리는 일(명령으로 부른 메뉴 추천, 식당 목록을 다시 모으면 1분 안팎)은 slow() 로 표시해 줄 밖에서 돌립니다.
그동안 들어온 입력이 디스코드의 3초 제한을 넘기지 않게 하기 위해서입니다.
"""
import threading
from concurrent.futures import ThreadPoolExecutor


def slow(job):
    """줄을 막지 않게 따로 돌릴 오래 걸리는 일로 표시합니다."""
    job.slow = True
    return job


def is_slow(job) -> bool:
    return getattr(job, "slow", False)


class Inbox:
    def __init__(self):
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inbox")

    def ask(self, fn, *args):
        """줄에 넣고 차례가 와서 끝날 때까지 기다려 결과를 돌려줍니다 (실패하면 그 예외가 그대로 남)."""
        return self._worker.submit(fn, *args).result()

    def after(self, jobs, run) -> None:
        """응답 뒤에 할 일을 줄에 넣습니다. run(jobs) 으로 하고, 오래 걸리는 일은 앞의 일을 마친 뒤 따로 돌립니다."""
        quick = [job for job in jobs if not is_slow(job)]
        aside = [job for job in jobs if is_slow(job)]

        def go():
            run(quick)
            for job in aside:
                threading.Thread(target=run, args=([job],), daemon=True).start()

        self._worker.submit(go)
