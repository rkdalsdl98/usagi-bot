"""우사기 봇의 1:1 스레드: 대화 기억(dialog)으로 답하고, 로그에는 채팅 내용·이름·답을 남기지 않는다.

discord.py 가 있어야 돌아갑니다:
  uv run --python 3.12 --with discord.py==2.4.0 --with boto3 --with moto --with pytest --with pynacl==1.5.0 \
    pytest -q tests/test_usagi_threads.py
"""
import asyncio
import logging
import sys
import urllib.error
from pathlib import Path

import pytest

discord = pytest.importorskip("discord")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import local_env  # noqa: E402

local_env.load = lambda *a, **k: None  # 진짜 .env (토큰·웹훅 주소)를 읽지 않게
import usagi_bot as bot  # noqa: E402
from lunchbot import storage  # noqa: E402
from test_flow import aws  # noqa: E402,F401 (aws 는 fixture)

HOOK = "https://discord.com/api/webhooks/1/hachiware-token"
REAL_SLEEP = asyncio.sleep
SECRET = "비밀스러운 이야기"


class Guild:
    id, owner_id = "g", "own"


class Channel:
    def __init__(self, cid, parent_id=None):
        self.id, self.guild, self.sent = cid, Guild(), []
        if parent_id:
            self.parent_id = parent_id

    def typing(self):
        class Typing:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *a):
                return None

        return Typing()

    async def send(self, text, **kw):
        self.sent.append((text, kw))


class Author:
    def __init__(self, uid, name):
        self.id, self.display_name, self.bot = uid, name, False


class Message:
    def __init__(self, content, channel, author):
        self.content, self.channel, self.author = content, channel, author
        self.type, self.webhook_id = discord.MessageType.default, None

    async def reply(self, text, **kw):
        self.channel.sent.append((text, kw))


@pytest.fixture
def world(aws, vault_tmp, monkeypatch):
    storage.put_json(storage.threads_key("g"), {"usagi": {"a": "ta"}})
    storage.put_json(storage.members_key("g"), {"members": {"a": {"rank": 2}}})
    hooked = []

    async def no_wait(*a, **k):
        return None

    monkeypatch.setattr(bot.asyncio, "sleep", no_wait)
    monkeypatch.setattr(bot, "hachiware_url", HOOK)
    monkeypatch.setattr(bot, "translating", lambda user_id=None: True)
    monkeypatch.setattr(bot.discord_api, "execute_webhook", lambda url, text: hooked.append((url, text)) or {})
    monkeypatch.setattr(bot, "talks", bot.dialog.Dialog())
    return hooked


def run(*messages):
    asyncio.run(bot.answer(list(messages)))


def usagi_logs(caplog):
    return [r for r in caplog.records if r.name == "usagi"]


def test_thread_answers_go_through_dialog_and_log_nothing(world, caplog):
    caplog.set_level(logging.INFO)
    thread = Channel("ta", parent_id="555")
    run(Message(f"오늘 점심 뭐야? {SECRET}", thread, Author("a", "민지")))
    assert thread.sent and all(text for text, _ in thread.sent)
    assert world and all("thread_id=ta" in url for url, _ in world)
    assert not usagi_logs(caplog)
    assert all(SECRET not in r.getMessage() and "민지" not in r.getMessage() for r in caplog.records)


def test_plain_chat_in_thread_logs_nothing(world, caplog):
    caplog.set_level(logging.INFO)
    thread = Channel("ta", parent_id="555")
    for text in ("안녕", f"ㅋㅋ {SECRET}"):
        run(Message(text, thread, Author("a", "민지")))
    assert len(thread.sent) >= 2 and not usagi_logs(caplog)


def test_public_channel_is_unchanged(world, caplog):
    caplog.set_level(logging.INFO)
    public = Channel("555")
    run(Message("안녕", public, Author("x", "손님")))
    assert public.sent and any("답함" in r.getMessage() for r in usagi_logs(caplog))
    assert world and all("thread_id" not in url for url, _ in world)


def test_thread_messages_never_ping(world):
    thread = Channel("ta", parent_id="555")
    run(Message("오늘 점심 뭐야?", thread, Author("a", "민지")))
    run(Message("ㅋㅋ", thread, Author("a", "민지")))
    for _, kw in thread.sent:
        assert kw["allowed_mentions"].to_dict()["parse"] == []


def test_thread_failure_logs_only_the_kind(world, caplog, monkeypatch):
    caplog.set_level(logging.INFO)

    def broken(**kw):
        raise ValueError(SECRET)

    monkeypatch.setattr(bot.talks, "respond", broken)
    run(Message("오늘 점심 뭐야?", Channel("ta", parent_id="555"), Author("a", "민지")))
    [record] = usagi_logs(caplog)
    assert record.levelno == logging.WARNING and "ValueError" in record.getMessage()
    assert SECRET not in record.getMessage() and "민지" not in record.getMessage()


def test_guide_is_marked_seen_only_after_it_arrives(world, monkeypatch):
    from lunchbot import memory

    thread = Channel("ta", parent_id="555")
    run(Message("안녕", thread, Author("a", "민지")))
    assert memory.load("g", "a")["noticed"]  # 안내가 하치와레로 닿음

    def gone(url, text):
        raise urllib.error.HTTPError(url, 404, "Unknown Webhook", {}, None)

    storage.put_json(storage.threads_key("g"), {"usagi": {"a": "ta", "b": "tb"}})
    storage.put_json(storage.members_key("g"), {"members": {"a": {"rank": 2}, "b": {"rank": 2}}})
    monkeypatch.setattr(bot.discord_api, "execute_webhook", gone)  # 하치와레 웹훅이 지워짐
    run(Message("안녕", Channel("tb", parent_id="555"), Author("b", "현우")))
    assert not memory.load("g", "b")["noticed"]  # 안내가 안 닿았으니 기록 시작 안 함
    assert bot.hachiware_url == ""  # 그 뒤로는 번역이 꺼진 것으로 봄 (모르게 기록하지 않게)


def test_two_people_in_one_thread_are_never_mixed(world, monkeypatch):
    # 스레드 주인 a 와 스레드를 볼 수 있는 관리자 b 가 거의 같이 채팅해도 한 덩어리로 모으지 않는다
    from lunchbot import birthdays, memory

    async def yield_only(*a, **k):
        await REAL_SLEEP(0)

    monkeypatch.setattr(bot.asyncio, "sleep", yield_only)
    monkeypatch.setattr(bot.config, "USAGI_CHANNEL_ID", "555")
    storage.put_json(storage.members_key("g"), {"members": {"a": {"rank": 2}, "b": {"rank": 2}}})
    mem = memory.new()
    mem["noticed"] = "2026-10-26"
    memory.save("g", "a", mem)
    birthdays.save("g", "a", 3, 5, by="x")
    birthdays.save("g", "b", 12, 24, by="x")
    thread = Channel("ta", parent_id="555")

    async def together(*messages):
        await asyncio.gather(*(bot.handle(m) for m in messages))

    asyncio.run(together(Message("민트초코 좋아", thread, Author("b", "관리자")), Message("ㅋㅋ", thread, Author("a", "민지"))))
    assert "민트초코" not in memory.load("g", "a")["likes"]  # b 의 말이 a 의 기억에 들어가지 않음
    world.clear()
    asyncio.run(together(Message("내 생일 언제로 돼 있어?", thread, Author("a", "민지")), Message("ㅋㅋ", thread, Author("b", "관리자"))))
    said = " ".join(text for _, text in world)
    assert "3월 5일" in said and "12월 24일" not in said  # a 의 물음에 b 의 정보로 답하지 않음
