import urllib.error

from lunchbot import discord

VIEW, ADMIN = 1 << 10, 1 << 3


def member(user_id, roles, bot=False):
    return {"user": {"id": user_id, "bot": bot}, "roles": roles}


def test_counts_humans_who_can_see_the_channel():
    data = {
        "/channels/c": {
            "guild_id": "g",
            "permission_overwrites": [
                {"id": "g", "type": 0, "allow": "0", "deny": str(VIEW)},  # @everyone 은 이 채널을 못 봄
                {"id": "lunch", "type": 0, "allow": str(VIEW), "deny": "0"},  # 점심 역할은 봄
                {"id": "u4", "type": 1, "allow": str(VIEW), "deny": "0"},  # u4 는 개인으로 허용
            ],
        },
        "/guilds/g/roles": [
            {"id": "g", "permissions": str(VIEW)},
            {"id": "lunch", "permissions": "0"},
            {"id": "boss", "permissions": str(ADMIN)},
        ],
        "/guilds/g/members?limit=1000&after=0": [
            member("u1", ["lunch"]),
            member("u2", ["lunch"]),
            member("u3", []),  # 못 봄
            member("u4", []),
            member("u5", ["boss"]),  # 관리자는 항상 봄
            member("b1", ["lunch"], bot=True),  # 봇은 세지 않음
        ],
    }
    assert discord.channel_viewer_count("tok", "c", get=data.__getitem__) == 4


def test_none_when_member_list_is_not_allowed():
    def get(path):
        if "/members" in path:  # 개발자 포털에서 SERVER MEMBERS INTENT 를 켜지 않으면 거절된다
            raise urllib.error.HTTPError(path, 403, "Missing Access", {}, None)
        return {"/channels/c": {"guild_id": "g", "permission_overwrites": []}, "/guilds/g/roles": []}[path]

    assert discord.channel_viewer_count("tok", "c", get=get) is None
