"""디스코드 버튼 클릭과 우사기 명령(Interaction)을 로컬에서 처리하는 서버입니다. interaction.py 를 그대로 실행합니다.

run_local.py 와 같은 로컬 폴더(기본 .local-s3/)에서 추천 기록을 찾고 선택 기록을 저장하므로,
run_local.py 로 보낸 메시지의 버튼을 처리할 수 있습니다.
우사기 명령은 응답(우사기 소리)부터 보내고, 그 뒤에 하치와레 말과 명령으로 부른 추천을 따로 처리합니다.
입력과 응답 뒤에 할 일은 들어온 순서대로 줄(lunchbot/inbox.py)에 넣어 하나씩 처리합니다. 거의 같은 순간에 온
두 입력(예: 게임 답 둘)이 같은 파일을 함께 고쳐 써서 한쪽이 사라지지 않게 하기 위해서입니다.
서버를 나간 사람의 기록 지우기(lunchbot/departed.py)도 10분마다, 리마인드 보내기(lunchbot/reminders.py)도 30초마다
같은 줄에서 합니다.
디스코드가 이 서버에 닿으려면 공개 HTTPS 주소가 필요합니다. 다른 터미널에서 터널을 띄우고
그 주소를 개발자 포털의 Interactions Endpoint URL 에 넣습니다.

  cloudflared tunnel --url http://127.0.0.1:8787

사용법:
  .env 에 DISCORD_PUBLIC_KEY 를 넣고 (.env.example 참고)
  uv run --python 3.12 --with pynacl==1.5.0 --with boto3 scripts/serve_local.py [포트]
  (DISCORD_PUBLIC_KEY 가 없으면 실행할 때 물어봅니다. 기본 포트는 8787)
"""
import logging
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import local_env

local_env.load()
import local_storage  # noqa: E402  (.env 의 LOCAL_S3_DIR 을 읽도록 load 뒤에 import)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
AFTER_S = 0.8  # 응답(우사기 소리)이 채널에 올라간 뒤 하치와레가 말하기까지

if not os.environ.get("DISCORD_PUBLIC_KEY"):
    if not sys.stdin.isatty():
        sys.exit(f"DISCORD_PUBLIC_KEY 환경 변수가 없습니다.\n{__doc__}")
    os.environ["DISCORD_PUBLIC_KEY"] = input("디스코드 앱 Public Key (General Information 탭): ").strip()

# 잘못 붙여 넣은 키는 디스코드 검증 때가 아니라 지금 알려 줍니다.
from nacl.signing import VerifyKey  # noqa: E402

try:
    VerifyKey(bytes.fromhex(os.environ["DISCORD_PUBLIC_KEY"]))
except ValueError:
    sys.exit("Public Key 형식이 아닙니다. 개발자 포털의 PUBLIC KEY(64자리 16진수)를 그대로 넣어 주세요.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
local_storage.install()
import commands  # noqa: E402
import interaction  # noqa: E402
from lunchbot import config, departed, discord, hachiware, inbox, reminders  # noqa: E402

line = inbox.Inbox()  # 들어온 순서대로 하나씩
SWEEP_FIRST_S = 30  # 서버를 띄우고 처음 나간 사람을 찾기까지


def sweep_now() -> None:
    """서버 사람 목록과 견주어 나간 사람의 기록을 지웁니다 (처리 줄 안에서 부름)."""
    if not config.USAGI_CHANNEL_ID:
        return
    guild_id = discord.get_channel(config.DISCORD_BOT_TOKEN, config.USAGI_CHANNEL_ID)["guild_id"]
    people = discord.list_members(config.DISCORD_BOT_TOKEN, guild_id)
    n = departed.sweep(guild_id, {m["user"]["id"] for m in people}, commands._owner(guild_id))
    if n:
        logging.info("나간 사람 %d명의 기록을 지웠어요", n)


def remind_now() -> None:
    """시각이 된 리마인드를 하치와레가 1:1 스레드에서 알립니다 (처리 줄 안에서 부름)."""
    if not config.USAGI_CHANNEL_ID:
        return
    guild_id = discord.get_channel(config.DISCORD_BOT_TOKEN, config.USAGI_CHANNEL_ID)["guild_id"]
    n = reminders.fire_all(guild_id, commands._owner(guild_id), config.now_kst())
    if n:
        logging.info("리마인드 %d개를 보냈어요", n)


def _reminder() -> None:
    while True:
        time.sleep(reminders.FIRE_S)
        try:
            line.ask(remind_now)
        except Exception as e:  # 다음에 다시
            logging.warning("리마인드 확인 실패: %s", type(e).__name__)


def _sweeper() -> None:
    time.sleep(SWEEP_FIRST_S)
    while True:
        try:
            line.ask(sweep_now)
        except Exception as e:  # 다음 확인 때 다시
            logging.warning("나간 사람 정리 실패: %s", type(e).__name__)
        time.sleep(departed.SWEEP_S)

# 하치와레 웹훅이 어느 채널 것인지 미리 읽어 둡니다 (첫 명령의 응답이 늦지 않게)
_hooks = hachiware.hooks()
print(f"하치와레 웹훅 {len(_hooks)}개 (채널 {', '.join(_hooks) or '없음'})")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
        # Lambda Function URL 이 넘겨주는 이벤트와 같은 모양으로 만듭니다.
        event = {"headers": dict(self.headers.items()), "body": body, "isBase64Encoded": False}
        later = []
        try:
            res, later = line.ask(interaction.respond, event)
        except Exception:
            traceback.print_exc()
            res = {"statusCode": 500, "headers": {"Content-Type": "application/json"}, "body": "{}"}
        self._send(res["statusCode"], res["body"].encode("utf-8"), res["headers"]["Content-Type"])
        if later:  # 응답을 다 보낸 뒤에 (디스코드는 3초 안에 응답을 받아야 함)
            threading.Thread(target=self._after, args=(later,), daemon=True).start()

    @staticmethod
    def _after(later):
        time.sleep(AFTER_S)
        line.after(later, interaction.run_later)  # 줄의 차례대로 (오래 걸리는 추천만 줄 밖에서)

    def do_GET(self):
        # 터널이 이 서버에 닿는지 브라우저로 확인할 때 씁니다.
        self._send(200, "lunchbot 로컬 interaction 서버가 동작 중입니다.\n".encode("utf-8"), "text/plain; charset=utf-8")

    def _send(self, status, data, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        logging.info(fmt, *args)


# 도커 안에서는 다른 컨테이너(cloudflared)가 들어올 수 있게 SERVE_HOST=0.0.0.0 으로 띄웁니다
HOST = os.environ.get("SERVE_HOST", "127.0.0.1")
server = ThreadingHTTPServer((HOST, PORT), Handler)
threading.Thread(target=_sweeper, daemon=True).start()
threading.Thread(target=_reminder, daemon=True).start()
print(f"http://{HOST}:{PORT} 에서 버튼 클릭을 기다립니다. 저장 폴더: {local_storage.LOCAL_DIR}")
print("멈추려면 Ctrl+C")
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
