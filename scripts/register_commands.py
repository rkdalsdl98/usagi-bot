"""우사기 명령(슬래시 명령)을 디스코드 서버에 등록합니다. 명령 목록은 src/commands.py 의 DEFINITIONS 입니다.

서버 전용 명령으로 올리므로 바로 반영됩니다. 목록을 통째로 바꿔 올려서, 목록에 없는 예전 명령은 지워집니다.
명령을 고쳤으면 다시 실행합니다. 등록한 명령의 클릭은 Interactions Endpoint URL(버튼 처리 서버)로 옵니다.

사용법:
  .env 에 DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID 를 넣고 (서버는 그 채널의 서버)
  uv run --python 3.12 --with boto3 --with pynacl==1.5.0 scripts/register_commands.py
  docker compose run --rm --entrypoint python recommend scripts/register_commands.py

  --preview  디스코드에 올리지 않고 올릴 명령(JSON)만 출력
  --clear    이 서버의 우사기 명령을 모두 지우기
"""
import json
import os
import sys
import urllib.error
import urllib.parse

import local_env

local_env.load()
sys.path.insert(0, str(local_env.ENV_FILE.parent / "src"))

OPTIONS = {"--preview", "--clear"}
unknown = [a for a in sys.argv[1:] if a not in OPTIONS]
if unknown:
    sys.exit(f"모르는 옵션입니다: {' '.join(repr(a) for a in unknown)}\n{__doc__}")

import commands  # noqa: E402
from lunchbot import config, discord  # noqa: E402

defs = [] if "--clear" in sys.argv else commands.DEFINITIONS
if "--preview" in sys.argv:
    print(json.dumps(defs, ensure_ascii=False, indent=2))
    sys.exit(0)

channel_setting = next((k for k in ("DISCORD_CHANNEL_ID", "USAGI_CHANNEL_ID", "DINNER_CHANNEL_ID") if os.environ.get(k)), None)
missing = [k for k in ("DISCORD_BOT_TOKEN",) if not os.environ.get(k)] + ([] if channel_setting else ["DISCORD_CHANNEL_ID"])
if missing:
    sys.exit(f"환경 변수가 없습니다: {', '.join(missing)} (.env 에 넣어 주세요)\n{__doc__}")

try:
    app_id = discord._api_get(config.DISCORD_BOT_TOKEN, "/applications/@me")["id"]
    guild_id = discord._api_get(config.DISCORD_BOT_TOKEN, f"/channels/{os.environ[channel_setting]}")["guild_id"]
    done = discord.put_guild_commands(config.DISCORD_BOT_TOKEN, app_id, guild_id, defs)
except urllib.error.HTTPError as e:
    host = urllib.parse.urlsplit(e.url).netloc
    hint = ""
    if e.code in (401, 403):
        hint = ("\n봇 토큰이 맞는지, 봇이 그 서버에 초대돼 있는지 확인하세요. 명령 권한이 없다고 나오면 아래 주소로 다시 초대합니다:\n"
                f"https://discord.com/oauth2/authorize?client_id=<앱 ID>&scope=bot+applications.commands&permissions=19458")
    sys.exit(f"{host} 요청 실패: HTTP {e.code}\n{e.read().decode('utf-8', 'replace')}{hint}")

if defs:
    print(f"서버 {guild_id} 에 우사기 명령 {len(done)}개를 등록했습니다: {', '.join('/' + c['name'] for c in done)}")
else:
    print(f"서버 {guild_id} 의 우사기 명령을 모두 지웠습니다")
