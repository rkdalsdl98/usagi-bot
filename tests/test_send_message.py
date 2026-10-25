import json

from lunchbot import discord


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *a):
        return self.data


def test_send_message_posts_to_channel_as_bot(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"], seen["method"] = req.full_url, req.get_method()
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        seen["body"] = json.loads(req.data)
        return FakeResponse({"id": "999"})

    monkeypatch.setattr(discord.urllib.request, "urlopen", fake_urlopen)
    payload = {"flags": 1 << 15, "components": [{"type": 17, "components": []}]}

    assert discord.send_message("tok", "42", payload) == {"id": "999"}
    # 웹훅이 아니라 봇 계정으로 채널에 직접 보낸다
    assert seen["url"] == "https://discord.com/api/v10/channels/42/messages"
    assert seen["method"] == "POST"
    assert seen["headers"]["authorization"] == "Bot tok"
    assert seen["headers"]["content-type"] == "application/json"
    assert seen["body"] == payload
