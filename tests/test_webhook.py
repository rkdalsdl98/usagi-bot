"""하치와레 웹훅으로 글 보내기와, 웹훅이 어느 채널 것인지 확인하기."""
import json
import urllib.error
import urllib.parse

from lunchbot import discord

URL = "https://discord.com/api/webhooks/1563/abc-token"


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *a):
        return self.data


def capture(monkeypatch, reply):
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append({
            "url": req.full_url,
            "method": req.get_method(),
            "headers": {k.lower(): v for k, v in req.header_items()},
            "body": json.loads(req.data) if req.data else None,
        })
        return FakeResponse(reply)

    monkeypatch.setattr(discord.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_execute_webhook_posts_text_without_pinging(monkeypatch):
    seen = capture(monkeypatch, {"id": "9", "channel_id": "555"})
    assert discord.execute_webhook(URL, '우사기가 "안녕!"래') == {"id": "9", "channel_id": "555"}
    req = seen[0]
    assert req["url"] == URL + "?wait=true" and req["method"] == "POST"
    assert req["body"] == {"content": '우사기가 "안녕!"래', "allowed_mentions": {"parse": []}}
    assert "authorization" not in req["headers"]  # 웹훅 주소 안의 토큰으로 보냄 (봇 토큰 아님)
    assert req["headers"]["user-agent"] and req["headers"]["content-type"] == "application/json"

    discord.execute_webhook(URL + "?thread_id=7", "하")
    assert seen[1]["url"] == URL + "?thread_id=7&wait=true"


def test_webhook_channel(monkeypatch):
    seen = capture(monkeypatch, {"id": "1563", "channel_id": "555", "token": "abc-token"})
    assert discord.webhook_channel(URL) == "555"
    assert seen[0]["url"] == URL and seen[0]["method"] == "GET" and "authorization" not in seen[0]["headers"]

    def down(url):
        raise urllib.error.HTTPError(url, 404, "Unknown Webhook", {}, None)

    assert discord.webhook_channel(URL, get=down) is None  # 지워졌거나 잘못된 주소
    assert discord.webhook_channel(URL, get=lambda url: {"id": "1563"}) is None


def test_channel_webhooks_groups_urls_by_channel():
    channels = {"https://a": "555", "https://b": "42", "https://gone": None}
    hooks = discord.channel_webhooks(["https://a", "https://b", "https://gone"], channel_of=channels.get)
    assert hooks == {"555": "https://a", "42": "https://b"}  # 읽을 수 없는 주소는 뺌


def test_guild_owner():
    asked = []
    assert discord.guild_owner("t", "g1", get=lambda p: asked.append(p) or {"id": "g1", "owner_id": 77}) == "77"
    assert asked == ["/guilds/g1"]

    def down(path):
        raise urllib.error.URLError("x")

    assert discord.guild_owner("t", "g1", get=down) is None


def test_kick_member(monkeypatch):
    seen = capture(monkeypatch, {})
    seen.clear()

    class Empty(FakeResponse):
        def __init__(self):
            self.data = b""

    def fake_urlopen(req, timeout=None):
        seen.append({"url": req.full_url, "method": req.get_method(), "headers": {k.lower(): v for k, v in req.header_items()}})
        return Empty()

    monkeypatch.setattr(discord.urllib.request, "urlopen", fake_urlopen)
    discord.kick_member("tok", "g1", "u9", "우사기 명령 /추방 (직장인)")
    req = seen[0]
    assert req["url"] == "https://discord.com/api/v10/guilds/g1/members/u9" and req["method"] == "DELETE"
    assert req["headers"]["authorization"] == "Bot tok"
    assert urllib.parse.unquote(req["headers"]["x-audit-log-reason"]) == "우사기 명령 /추방 (직장인)"


def test_put_guild_commands(monkeypatch):
    seen = capture(monkeypatch, [{"id": "1", "name": "도움"}])
    out = discord.put_guild_commands("tok", "app1", "g1", [{"name": "도움", "description": "d"}])
    assert out == [{"id": "1", "name": "도움"}]
    req = seen[0]
    assert req["url"] == "https://discord.com/api/v10/applications/app1/guilds/g1/commands" and req["method"] == "PUT"
    assert req["body"] == [{"name": "도움", "description": "d"}] and req["headers"]["authorization"] == "Bot tok"


def test_followup(monkeypatch):
    seen = capture(monkeypatch, {"id": "5"})
    discord.followup("app1", "itok", "추천을 못 보냈어…")
    req = seen[0]
    assert req["url"] == "https://discord.com/api/v10/webhooks/app1/itok" and req["method"] == "POST"
    assert req["body"] == {"content": "추천을 못 보냈어…", "flags": 64, "allowed_mentions": {"parse": []}}
    assert "authorization" not in req["headers"]  # 명령의 토큰으로 보냄
    discord.followup("app1", "itok", "모두에게", ephemeral=False)
    assert seen[1]["body"] == {"content": "모두에게", "allowed_mentions": {"parse": []}}



def test_thread_helpers(monkeypatch):
    seen = capture(monkeypatch, {"id": "t1"})
    assert discord.create_thread("tok", "555", "우사기 · 민지") == {"id": "t1"}
    assert seen[0]["url"] == "https://discord.com/api/v10/channels/555/threads" and seen[0]["method"] == "POST"
    # 비공개 스레드(12), 다른 사람은 초대 못 함, 일주일 조용하면 보관
    assert seen[0]["body"] == {"name": "우사기 · 민지", "type": 12, "invitable": False, "auto_archive_duration": 10080}
    discord.add_thread_member("tok", "t1", "u9")
    assert seen[1]["url"].endswith("/channels/t1/thread-members/u9") and seen[1]["method"] == "PUT"
    discord.unarchive_thread("tok", "t1")
    assert seen[2]["url"].endswith("/channels/t1") and seen[2]["method"] == "PATCH"
    assert seen[2]["body"] == {"archived": False}
    assert all(s["headers"]["authorization"] == "Bot tok" for s in seen)


def test_get_channel(monkeypatch):
    seen = capture(monkeypatch, {"id": "t1", "thread_metadata": {"archived": True}})
    assert discord.get_channel("tok", "t1")["thread_metadata"]["archived"] is True
    assert seen[0]["url"].endswith("/channels/t1") and seen[0]["method"] == "GET"

    def gone(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Unknown Channel", {}, None)

    monkeypatch.setattr(discord.urllib.request, "urlopen", gone)
    assert discord.get_channel("tok", "t1") is None  # 지워진 스레드
