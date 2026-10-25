"""갑옷씨 등급 역할(행인·직장인·대장 갑옷씨)을 만들고, 서버 사람들의 역할을 지금 등급에 한 번에 맞춥니다.

명령(/멤버추가 · /멤버승급 · /멤버강등 · /멤버삭제)으로 등급이 바뀔 때는 버튼 처리 서버가 그때그때 맞추므로, 이 스크립트는 처음 한 번이나
봇 권한을 고친 뒤 어긋난 역할을 바로잡을 때 씁니다. 서버 주인은 대장 갑옷씨, 멤버는 자기 등급, 멤버가 아닌 사람은
갑옷씨 역할을 모두 뗍니다. 봇에 '역할 관리' 권한이 있고, 봇 역할이 세 역할보다 위에 있어야 합니다.

사용법:
  .env 에 DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID 를 넣고 (서버는 그 채널의 서버)
  uv run --python 3.12 --with boto3 scripts/sync_roles.py
  docker compose run --rm --entrypoint python recommend scripts/sync_roles.py

  --preview  역할을 만들거나 바꾸지 않고 누구에게 어떤 역할을 줄지만 출력
"""
import sys
import urllib.error

import local_env

local_env.load()
import local_storage  # noqa: E402  (.env 의 LOCAL_S3_DIR 을 읽도록 load 뒤에 import)

OPTIONS = {"--preview"}
unknown = [a for a in sys.argv[1:] if a not in OPTIONS]
if unknown:
    sys.exit(f"모르는 옵션입니다: {' '.join(repr(a) for a in unknown)}\n{__doc__}")

local_storage.install()
sys.path.insert(0, str(local_env.ENV_FILE.parent / "src"))
from lunchbot import config, discord, members, roles  # noqa: E402

if not config.DISCORD_BOT_TOKEN or not config.DISCORD_CHANNEL_ID:
    sys.exit(f"환경 변수가 없습니다: DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID (.env 에 넣어 주세요)\n{__doc__}")

token = config.DISCORD_BOT_TOKEN
try:
    guild_id = discord._api_get(token, f"/channels/{config.DISCORD_CHANNEL_ID}")["guild_id"]
    owner_id = discord.guild_owner(token, guild_id)
    roster = members.load(guild_id)
    people, after = [], "0"
    while True:  # 서버 사람 모두 (SERVER MEMBERS INTENT 필요)
        page = discord._api_get(token, f"/guilds/{guild_id}/members?limit=1000&after={after}")
        people += [m for m in page if not m["user"].get("bot")]
        if len(page) < 1000:
            break
        after = page[-1]["user"]["id"]
    plan = []
    for m in people:
        uid = m["user"]["id"]
        level = members.person(uid, "", roster, owner_id).level
        plan.append((m.get("nick") or m["user"].get("global_name") or m["user"]["username"], uid, level))
    for name, uid, level in plan:
        print(f"{name}: {members.RANKS.get(level, '멤버 아님 (갑옷씨 역할 없음)')}")
    if "--preview" in sys.argv:
        sys.exit(0)
    made = roles.ensure(guild_id)
    for name, uid, level in plan:
        roles.sync(guild_id, uid, level, reason="갑옷씨 등급 역할 맞추기 (sync_roles.py)")
except urllib.error.HTTPError as e:
    sys.exit(f"디스코드 요청 실패: HTTP {e.code} {e.read().decode('utf-8', 'replace')}\n"
             "봇 역할에 '역할 관리' 권한이 있고, 봇 역할이 갑옷씨 역할들보다 위에 있는지 확인하세요.")
print(f"갑옷씨 역할 {len(made)}개를 확인하고 {len(plan)}명의 역할을 맞췄습니다.")
