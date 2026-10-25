"""봇 토큰으로 '애플리케이션 소유 웹훅'을 만듭니다. (한 번만 실행)

디스코드 채널 설정에서 직접 만든 웹훅은 버튼을 보낼 수 없어서,
버튼 클릭을 받으려면 봇이 만든 웹훅이어야 합니다.
봇은 먼저 그 채널이 있는 서버에 초대돼 있어야 합니다 (권한: 웹훅 관리).

사용법:
  .env 에 DISCORD_BOT_TOKEN 을 넣고 (.env.example 참고)
  python3 scripts/create_webhook.py <채널 ID>
  출력된 웹훅 URL 을 .env 의 DISCORD_WEBHOOK_URL 에 넣습니다.
"""
import json
import os
import sys
import urllib.error
import urllib.request

import local_env

API = "https://discord.com/api/v10"
MANAGE_WEBHOOKS = 1 << 29

local_env.load()
if len(sys.argv) != 2 or not os.environ.get("DISCORD_BOT_TOKEN"):
    sys.exit(__doc__)

channel_id = sys.argv[1]
headers = {
    "Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}",
    "Content-Type": "application/json",
    "User-Agent": "DiscordBot (https://github.com/lunchbot, 1.0)",
}


def _get(path: str):
    with urllib.request.urlopen(urllib.request.Request(f"{API}{path}", headers=headers), timeout=10) as res:
        return json.load(res)


def invite_url() -> str:
    """이 봇을 서버에 초대하는 주소 (웹훅 관리 권한 포함)."""
    bot_id = _get("/users/@me")["id"]
    return f"https://discord.com/oauth2/authorize?client_id={bot_id}&scope=bot&permissions={MANAGE_WEBHOOKS}"


req = urllib.request.Request(
    f"{API}/channels/{channel_id}/webhooks",
    # 웹훅 이름이 디스코드에서 메시지 작성자 이름으로 보입니다
    data=json.dumps({"name": "우사기 봇"}).encode(),
    headers=headers,
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=10) as res:
        hook = json.load(res)
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", "replace")
    try:
        code = json.loads(body).get("code")
    except ValueError:
        code = None
    lines = [f"웹훅을 만들지 못했습니다: HTTP {e.code} {body}"]
    if e.code == 401:
        lines.append("봇 토큰이 틀렸습니다. 개발자 포털 Bot 탭에서 Reset Token 으로 새 토큰을 받아 .env 에 넣으세요.")
    elif code == 10003:
        lines.append("채널 ID가 잘못됐습니다. 채널을 우클릭해서 '채널 ID 복사'로 다시 받아 주세요.")
    elif code in (50001, 50013):
        # 봇이 서버에 없을 때도 디스코드는 권한 부족(50013)으로 답하므로 서버에 있는지 따로 확인합니다
        if not _get("/users/@me/guilds"):
            lines.append("봇이 아직 어떤 서버에도 초대되지 않았습니다. 아래 주소로 이 채널이 있는 서버에 초대하세요 (서버 관리 권한 필요).")
        else:
            lines.append("봇이 이 채널이 있는 서버에 없거나, 이 채널의 '웹후크 관리' 권한이 없습니다.")
            lines.append("서버에 없으면 아래 주소로 초대하고, 있으면 서버 설정에서 봇 역할에 웹후크 관리 권한을 주세요.")
        lines.append(invite_url())
    sys.exit("\n".join(lines))

print(f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}")
