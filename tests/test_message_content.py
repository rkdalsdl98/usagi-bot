"""우사기 채널 봇이 시작할 때 채팅 내용을 읽을 수 있는지(MESSAGE CONTENT INTENT) 확인한다."""
import urllib.error

from lunchbot import discord

MEMBERS_LIMITED, CONTENT_LIMITED, CONTENT = 1 << 15, 1 << 19, 1 << 18


def app(flags):
    asked = []

    def get(path):
        asked.append(path)
        return {"id": "1", "flags": flags}

    return get, asked


def test_reads_the_app_flags():
    get, asked = app(MEMBERS_LIMITED | CONTENT_LIMITED)
    assert discord.can_read_messages("t", get=get) is True
    assert asked == ["/applications/@me"]
    assert discord.can_read_messages("t", get=app(CONTENT)[0]) is True  # 인증된 봇은 이쪽 플래그


def test_off_when_the_intent_is_not_enabled():
    assert discord.can_read_messages("t", get=app(MEMBERS_LIMITED)[0]) is False


def test_off_when_discord_cannot_be_asked():
    def down(path):
        raise urllib.error.URLError("no network")

    assert discord.can_read_messages("t", get=down) is False
    assert discord.can_read_messages("t", get=lambda path: {"id": "1"}) is False  # 플래그가 없으면 꺼진 것


def test_can_read_members_for_welcomes():
    assert discord.can_read_members("t", get=app(MEMBERS_LIMITED)[0]) is True  # SERVER MEMBERS INTENT
    assert discord.can_read_members("t", get=app(CONTENT_LIMITED)[0]) is False
