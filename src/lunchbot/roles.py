"""갑옷씨 등급을 디스코드 역할로: 행인 갑옷씨 · 직장인 갑옷씨 · 대장 갑옷씨.

등급이 바뀔 때마다 그 사람의 역할도 맞춥니다. 한 사람은 자기 등급 역할 하나만 갖고, 멤버가 아니면 셋 다 뗍니다.
역할이 있으면 서버 설정 → 연동 → 우사기 봇에서 명령마다 보일 역할을 정할 수 있습니다 (슬래시 명령 창이 등급에 맞게
보임. 이 설정은 봇 토큰으로는 바꿀 수 없어서 서버 주인이 정함). 봇에 '역할 관리' 권한이 있고, 봇 역할이 세 역할보다
위에 있어야 합니다. 역할 id 는 roles/{서버 id}.json 에 두고, 지워졌으면 같은 이름의 역할을 찾거나 새로 만듭니다.
"""
from . import config, discord, members, storage

COLORS = {members.WALKER: 0x95A5A6, members.WORKER: 0x3A5BA0, members.CAPTAIN: 0xEF9F27}  # 회색, 남색, 노란 주황


def ensure(guild_id: str) -> dict:
    """{등급: 역할 id}. 없는 역할은 만듭니다."""
    token = config.DISCORD_BOT_TOKEN
    saved = {int(k): v for k, v in ((storage.get_json(storage.roles_key(guild_id)) or {}).get("roles") or {}).items()}
    live = {r["id"]: r for r in discord.guild_roles(token, guild_id)}
    by_name = {r["name"]: rid for rid, r in live.items()}
    out, created = {}, False
    for level, name in sorted(members.RANKS.items(), reverse=True):  # 대장부터: 자리가 같으면 먼저 만든 역할이 위
        rid = saved.get(level)
        if rid not in live:  # 처음이거나 누가 지웠으면 같은 이름을 찾고, 없으면 새로
            rid = by_name.get(name)
            if not rid:
                rid, created = discord.create_role(token, guild_id, name, COLORS[level])["id"], True
        out[level] = rid
    if created:  # 새 역할은 맨 아래에 쌓이므로 다시 읽어서 순서를 봄
        live = {r["id"]: r for r in discord.guild_roles(token, guild_id)}
    _order(token, guild_id, out, {rid: live[rid]["position"] for rid in out.values()})
    if out != saved:
        storage.put_json(storage.roles_key(guild_id), {"roles": {str(k): v for k, v in out.items()}})
    return out


def _order(token: str, guild_id: str, out: dict, pos: dict) -> None:
    """세 역할의 자리는 그대로 두고, 높은 자리부터 대장 → 직장인 → 행인 순서로 앉힙니다.

    봇 역할이 낮으면 디스코드가 세 역할을 같은 자리에 두는데, 그때는 옮길 자리가 없어서 그대로 둡니다
    (만드는 순서로 대장이 위에 보임).
    """
    slots = sorted(pos.values(), reverse=True)
    if len(set(slots)) < len(slots):
        return
    want = {out[level]: slot for level, slot in zip(sorted(out, reverse=True), slots)}
    if want != pos:
        discord.set_role_positions(token, guild_id, want)


def sync(guild_id: str, user_id: str, level: int, reason: str = "우사기 명령: 갑옷씨 등급") -> None:
    """그 사람에게 자기 등급 역할만 남깁니다 (level 0 이면 갑옷씨 역할을 모두 뗌)."""
    token = config.DISCORD_BOT_TOKEN
    for rank, rid in ensure(guild_id).items():
        if rank == level:
            discord.add_role(token, guild_id, user_id, rid, reason)
        else:
            discord.remove_role(token, guild_id, user_id, rid, reason)
