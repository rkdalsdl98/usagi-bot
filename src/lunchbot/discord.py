"""디스코드 메시지 구성과 전송. 메시지는 봇 계정이 봇 토큰으로 채널에 직접 보냅니다 (웹훅 아님).

메시지는 컴포넌트 V2로 만든 한 장짜리 목록입니다. 테두리(Container) 하나 안에
우사기 소리와 작은 글씨 정보 줄, 식당 5곳(이름·메뉴·거리 + 대표 사진 썸네일, 투표한 사람), 버튼이 들어갑니다.
컴포넌트 V2 메시지에는 content 와 embeds 를 쓸 수 없습니다.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date as _date

from . import config, meals, messages

USER_AGENT = "DiscordBot (https://github.com/lunchbot, 1.0)"
WEEKDAYS = "월화수목금토일"

IS_COMPONENTS_V2 = 1 << 15
ACTION_ROW, BUTTON, SECTION, TEXT, THUMBNAIL, SEPARATOR, CONTAINER = 1, 2, 9, 10, 11, 14, 17
STYLE_SECONDARY, STYLE_DANGER = 2, 4
SKIP = "skip"  # 패스 표

VIEW_CHANNEL, ADMINISTRATOR = 1 << 10, 1 << 3


def naver_link(name: str) -> str:
    query = f"{config.SEARCH_PREFIX} {name}".strip()
    return f"https://map.naver.com/p/search/{urllib.parse.quote(query)}"


def _short_date(date: str) -> str:
    _, m, d = date.split("-")
    return f"{int(m)}/{int(d)}"


def _date_label(date: str) -> str:
    y, m, d = map(int, date.split("-"))
    return f"{m}월 {d}일 {WEEKDAYS[_date(y, m, d).weekday()]}요일"


def _text(content: str) -> dict:
    return {"type": TEXT, "content": content}


def _head(sound: str, info: str) -> dict:
    # "-# " 은 디스코드의 작은 회색 글씨
    return _text(f"{sound}\n-# {info}")


def _container(blocks: list, meal: str) -> dict:
    # 테두리 왼쪽 띠 색으로 점심과 저녁을 구분합니다
    return {"type": CONTAINER, "accent_color": meals.get(meal).accent, "components": blocks}


def _separator() -> dict:
    return {"type": SEPARATOR, "divider": True, "spacing": 1}


def latest_line(latest) -> str:
    if not latest:
        return messages.NO_LATEST
    return messages.latest(latest["name"], _short_date(latest["date"]))


def voters_by_choice(ballots) -> dict:
    """{식당 id 또는 'skip': [투표한 사람 이름, …]} — 먼저 투표한 사람부터."""
    names = {}
    for b in sorted(ballots, key=lambda b: (b["voted_at"], b["name"])):
        names.setdefault(b["choice"], []).append(b["name"])
    return names


def restaurant_block(r: dict, voters=()) -> dict:
    """식당 한 곳: 이름(네이버 지도 링크), 가장 구체적인 메뉴 분류, 거리, 투표한 사람. 사진이 있으면 오른쪽에 썸네일."""
    menu = r["category_detail"].split(" > ")[-1]
    content = f"**[{r['name']}]({naver_link(r['name'])})**\n{menu} · {r['distance_m']}m"
    if voters:
        content += f"\n-# {messages.voters_line(voters)}"
    text = _text(content)
    if not r.get("photo_url"):
        return text  # 썸네일을 붙이는 Section 은 사진이 꼭 있어야 해서, 없으면 글자만
    thumbnail = {"type": THUMBNAIL, "media": {"url": r["photo_url"]}, "description": r["name"]}
    return {"type": SECTION, "components": [text], "accessory": thumbnail}


def _button(label: str, custom_id: str, style: int = STYLE_SECONDARY) -> dict:
    return {"type": BUTTON, "style": style, "label": label[:80], "custom_id": custom_id}


def build_recommendation(
    date: str,
    picks: list,
    latest,
    buttons: bool = True,
    ballots=(),
    expected=None,
    sound=None,
    meal: str = meals.LUNCH,
    today_lunch=None,
) -> dict:
    """추천(투표) 메시지. ballots 가 있으면 식당마다 투표한 사람을, 정보 줄에 투표 진행을 보여 줍니다.

    저녁은 날짜 뒤에 '저녁'을 붙이고, 지난번 대신 오늘 점심(today_lunch, 식당 이름)을 보여 줍니다.
    """
    voters = voters_by_choice(ballots)
    label = meals.get(meal).label
    day = f"{_date_label(date)} {label}" if label else _date_label(date)
    context = messages.today_lunch(today_lunch) if meal == meals.DINNER else latest_line(latest)
    info = f"{day} · {context} · {messages.vote_progress(len(ballots), expected)}"
    blocks = [_head(sound or messages.recommend_sound(), info)]
    for i, r in enumerate(picks):
        if i:
            blocks.append(_separator())
        blocks.append(restaurant_block(r, voters.get(r["id"], [])))
    if voters.get(SKIP):
        blocks.append(_text(f"-# {messages.pass_line(voters[SKIP])}"))
    if buttons:
        # 버튼은 한 줄에 5개까지라 식당 줄과 패스·투표 종료 줄을 나눕니다
        blocks.append(_separator())
        blocks.append({"type": ACTION_ROW, "components": [_button(r["name"], f"pick:{date}:{r['id']}") for r in picks[:5]]})
        blocks.append(
            {
                "type": ACTION_ROW,
                "components": [
                    _button(messages.SKIP_LABEL, f"skip:{date}"),
                    _button(messages.END_LABEL, f"end:{date}", STYLE_DANGER),
                ],
            }
        )
    return {"flags": IS_COMPONENTS_V2, "components": [_container(blocks, meal)], "allowed_mentions": {"parse": []}}


def build_result(sound: str, info: str, restaurant=None, voters=(), meal: str = meals.LUNCH) -> dict:
    """투표가 끝난 뒤 바꿔 끼울 메시지: 우사기 소리 + 정보 줄, 고른 식당이 있으면 그 식당(과 투표한 사람)만."""
    blocks = [_head(sound, info)]
    if restaurant:
        blocks.append(restaurant_block(restaurant, voters))
    return {"flags": IS_COMPONENTS_V2, "components": [_container(blocks, meal)], "allowed_mentions": {"parse": []}}


def _headers(bot_token: str) -> dict:
    return {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json", "User-Agent": USER_AGENT}


def send_message(bot_token: str, channel_id: str, payload: dict) -> dict:
    """봇 계정으로 채널에 메시지를 보냅니다. 봇에게 그 채널의 보기·메시지 보내기 권한이 있어야 합니다."""
    req = urllib.request.Request(
        f"{config.DISCORD_API_BASE}/channels/{channel_id}/messages",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=_headers(bot_token),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.load(res)


def execute_webhook(webhook_url: str, content: str) -> dict:
    """웹훅으로 글을 보냅니다 (하치와레). 웹훅 주소 안의 토큰으로 보내고, 멘션 알림은 보내지 않습니다."""
    req = urllib.request.Request(
        f"{webhook_url}{'&' if '?' in webhook_url else '?'}wait=true",
        data=json.dumps({"content": content, "allowed_mentions": {"parse": []}}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.load(res)


def followup(app_id: str, interaction_token: str, content: str, ephemeral: bool = True) -> dict:
    """명령에 응답한 뒤 덧붙이는 메시지 (명령의 토큰은 15분 동안 씀). ephemeral 이면 명령을 쓴 사람에게만 보입니다."""
    payload = {"content": content, "allowed_mentions": {"parse": []}}
    if ephemeral:
        payload["flags"] = 64
    req = urllib.request.Request(
        f"{config.DISCORD_API_BASE}/webhooks/{app_id}/{interaction_token}",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.load(res)


def _url_get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.load(res)


def webhook_channel(webhook_url: str, get=None):
    """웹훅이 글을 올리는 채널 ID. 웹훅을 못 읽으면(지워졌거나 잘못된 주소) None."""
    get = get or _url_get
    try:
        return str(get(webhook_url)["channel_id"])
    except (OSError, KeyError, ValueError):  # HTTPError·URLError·시간 초과는 모두 OSError
        return None


def channel_webhooks(urls, channel_of=None) -> dict:
    """{채널 ID: 웹훅 주소}. 웹훅은 채널마다 따로라, 주소마다 어느 채널 것인지 읽어서 묶습니다 (못 읽는 주소는 뺌)."""
    channel_of = channel_of or webhook_channel
    hooks = {}
    for url in urls:
        channel = channel_of(url)
        if channel:
            hooks[channel] = url
    return hooks


def guild_owner(bot_token: str, guild_id: str, get=None):
    """서버 주인의 사용자 ID. 못 읽으면 None."""
    get = get or (lambda path: _api_get(bot_token, path))
    try:
        return str(get(f"/guilds/{guild_id}")["owner_id"])
    except (OSError, KeyError, ValueError):
        return None


def kick_member(bot_token: str, guild_id: str, user_id: str, reason: str) -> None:
    """서버에서 내보냅니다. 봇에 '멤버 추방하기' 권한이 있고 봇 역할이 그 사람보다 높아야 합니다 (아니면 HTTP 403)."""
    req = urllib.request.Request(
        f"{config.DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}",
        headers={**_headers(bot_token), "X-Audit-Log-Reason": urllib.parse.quote(reason)},  # 서버 감사 로그에 남는 까닭
        method="DELETE",
    )
    with urllib.request.urlopen(req, timeout=10):
        pass


def put_guild_commands(bot_token: str, app_id: str, guild_id: str, commands: list) -> list:
    """서버 전용 슬래시 명령을 통째로 바꿔 올립니다 (목록에 없는 명령은 지워짐). 서버 명령은 바로 반영됩니다."""
    req = urllib.request.Request(
        f"{config.DISCORD_API_BASE}/applications/{app_id}/guilds/{guild_id}/commands",
        data=json.dumps(commands, ensure_ascii=False).encode("utf-8"),
        headers=_headers(bot_token),
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.load(res)


def _api_send(bot_token: str, method: str, path: str, payload=None, reason: str | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = _headers(bot_token)
    if reason:
        headers["X-Audit-Log-Reason"] = urllib.parse.quote(reason)  # 서버 감사 로그에 남는 까닭
    req = urllib.request.Request(f"{config.DISCORD_API_BASE}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as res:
        body = res.read()
    return json.loads(body) if body else {}


def create_thread(bot_token: str, channel_id: str, name: str) -> dict:
    """채널 아래에 비공개 스레드를 만듭니다 (/우사기 1:1 대화). 다른 사람은 초대할 수 없고, 일주일 조용하면 보관됩니다."""
    payload = {"name": name, "type": 12, "invitable": False, "auto_archive_duration": 10080}
    return _api_send(bot_token, "POST", f"/channels/{channel_id}/threads", payload)


def add_thread_member(bot_token: str, thread_id: str, user_id: str) -> None:
    _api_send(bot_token, "PUT", f"/channels/{thread_id}/thread-members/{user_id}")


def unarchive_thread(bot_token: str, thread_id: str) -> None:
    _api_send(bot_token, "PATCH", f"/channels/{thread_id}", {"archived": False})


def edit_message(bot_token: str, channel_id: str, message_id: str, payload: dict) -> dict:
    """봇이 보낸 메시지 고치기 (게임 라운드 메시지의 답 낸 수)."""
    return _api_send(bot_token, "PATCH", f"/channels/{channel_id}/messages/{message_id}", payload)


def list_members(bot_token: str, guild_id: str) -> list:
    """서버의 사람들 (봇 빼고). SERVER MEMBERS INTENT 가 있어야 읽힙니다."""
    people, after = [], "0"
    while True:
        page = _api_get(bot_token, f"/guilds/{guild_id}/members?limit=1000&after={after}")
        people += [m for m in page if not m["user"].get("bot")]
        if len(page) < 1000:
            return people
        after = page[-1]["user"]["id"]


def guild_roles(bot_token: str, guild_id: str) -> list:
    return _api_get(bot_token, f"/guilds/{guild_id}/roles")


def create_role(bot_token: str, guild_id: str, name: str, color: int) -> dict:
    """권한 없는 역할을 만듭니다 (멤버 목록에서 따로 묶지 않고, 멘션도 못 함). 봇에 '역할 관리' 권한이 필요합니다."""
    payload = {"name": name, "color": color, "hoist": False, "mentionable": False, "permissions": "0"}
    return _api_send(bot_token, "POST", f"/guilds/{guild_id}/roles", payload, reason="우사기 갑옷씨 등급 역할")


def set_role_positions(bot_token: str, guild_id: str, positions: dict) -> None:
    """역할 순서 바꾸기 ({역할 id: 위치}, 클수록 위). 봇 역할보다 아래 자리끼리만 바꿀 수 있습니다."""
    payload = [{"id": rid, "position": pos} for rid, pos in positions.items()]
    _api_send(bot_token, "PATCH", f"/guilds/{guild_id}/roles", payload, reason="우사기 갑옷씨 등급 순서")


def add_role(bot_token: str, guild_id: str, user_id: str, role_id: str, reason: str) -> None:
    """역할 주기. 봇 역할이 그 역할보다 위에 있어야 합니다."""
    _api_send(bot_token, "PUT", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}", reason=reason)


def remove_role(bot_token: str, guild_id: str, user_id: str, role_id: str, reason: str) -> None:
    """역할 떼기 (그 역할이 없어도 됨)."""
    _api_send(bot_token, "DELETE", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}", reason=reason)


def get_channel(bot_token: str, channel_id: str):
    """채널(스레드) 정보. 지워졌으면 None."""
    try:
        return _api_get(bot_token, f"/channels/{channel_id}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _api_get(bot_token: str, path: str):
    req = urllib.request.Request(f"{config.DISCORD_API_BASE}{path}", headers=_headers(bot_token))
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.load(res)


# 앱 플래그의 채팅 내용 읽기 권한: 인증된 봇은 GATEWAY_MESSAGE_CONTENT, 서버 100개 미만은 _LIMITED
MESSAGE_CONTENT_FLAGS = 1 << 18 | 1 << 19


MEMBERS_FLAGS = 1 << 14 | 1 << 15  # SERVER MEMBERS INTENT (인증된 봇 / _LIMITED)


def can_read_members(bot_token: str, get=None) -> bool:
    """개발자 포털 Bot 탭의 SERVER MEMBERS INTENT 가 켜져 있는지 (새로 들어온 사람 환영에 필요)."""
    get = get or (lambda path: _api_get(bot_token, path))
    try:
        return bool(int(get("/applications/@me").get("flags", 0)) & MEMBERS_FLAGS)
    except (OSError, ValueError):
        return False


def can_read_messages(bot_token: str, get=None) -> bool:
    """개발자 포털 Bot 탭의 MESSAGE CONTENT INTENT 가 켜져 있는지. 확인을 못 하면 꺼진 것으로 봅니다."""
    get = get or (lambda path: _api_get(bot_token, path))
    try:
        flags = int(get("/applications/@me").get("flags", 0))
    except (OSError, ValueError):  # HTTPError·URLError·시간 초과는 모두 OSError
        return False
    return bool(flags & MESSAGE_CONTENT_FLAGS)


def channel_viewer_count(bot_token: str, channel_id: str, get=None):
    """채널을 볼 수 있는 사람 수 (봇 제외). 멤버 목록을 못 읽으면 None.

    멤버 목록은 개발자 포털 Bot 탭의 SERVER MEMBERS INTENT 를 켜야 읽을 수 있습니다.
    """
    get = get or (lambda path: _api_get(bot_token, path))
    try:
        channel = get(f"/channels/{channel_id}")
        guild_id = channel["guild_id"]
        roles = {r["id"]: int(r["permissions"]) for r in get(f"/guilds/{guild_id}/roles")}
        members, after = [], "0"
        while True:
            page = get(f"/guilds/{guild_id}/members?limit=1000&after={after}")
            members += page
            if len(page) < 1000:
                break
            after = page[-1]["user"]["id"]
    except (OSError, KeyError, ValueError):  # HTTPError·URLError·시간 초과는 모두 OSError
        return None
    overwrites = {o["id"]: o for o in channel.get("permission_overwrites", [])}

    def can_view(m) -> bool:
        perms = roles.get(guild_id, 0)
        for rid in m["roles"]:
            perms |= roles.get(rid, 0)
        if perms & ADMINISTRATOR:
            return True
        # 채널 권한 덮어쓰기: @everyone → 역할들 → 개인 순서
        for ids in ([guild_id], m["roles"], [m["user"]["id"]]):
            allow = deny = 0
            for i in ids:
                if i in overwrites:
                    allow |= int(overwrites[i]["allow"])
                    deny |= int(overwrites[i]["deny"])
            perms = (perms & ~deny) | allow
        return bool(perms & VIEW_CHANNEL)

    return sum(1 for m in members if not m["user"].get("bot") and can_view(m))
