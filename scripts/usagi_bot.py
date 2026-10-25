"""우사기 채널 봇: 디스코드에 계속 연결해 두고, 우사기 채널에 사람이 채팅을 보내면 우사기 소리로 답합니다.

우사기 채널 아래 스레드(/우사기 로 만든 1:1 비공개 스레드)의 채팅에도 같은 방식으로 답합니다.

버튼 처리(serve_local.py)는 디스코드가 우리 주소로 요청을 보내 주지만, 일반 채팅은 그렇게 받을 수 없어서
디스코드 게이트웨이(웹소켓)에 계속 붙어 있어야 합니다. 그래서 항상 켜 두는 서버로 띄웁니다 (docker compose 의 usagi).

답하는 모양 (어떤 소리를 낼지는 src/lunchbot/chat.py):
  - 연달아 보낸 채팅은 끝날 때까지(1.5초 조용할 때까지) 기다렸다가 합쳐서 한 번에 답합니다
  - 보내기 전에 '우사기 봇 입력 중…' 을 답 길이만큼 보여 주고, 답장 표시는 달 때도 안 달 때도 있습니다
  - 가끔 짧게 한마디를 더 보내고, 바로 전과 같은 답은 하지 않습니다
  - 하치와레 번역이 켜져 있으면 우사기가 답한 뒤 하치와레가 그 뜻을 번역해 올립니다. 우사기 채널은 서버 전체 설정
    (/하치와레 전체 켜기, 기본 꺼짐), 1:1 스레드는 그 사람의 개인 설정(/하치와레 번역 켜기)을 따릅니다
    (src/lunchbot/hachiware.py). HACHIWARE_WEBHOOK_URLS 중 우사기 채널 웹훅으로 보내고, 없으면 번역하지 않습니다.
    켜짐/꺼짐은 버튼 서버와 같은 저장소(.local-s3/settings/hachiware.json)에서 답할 때마다 읽습니다

채팅 내용에 맞춰 답하려면 개발자 포털 Bot 탭의 MESSAGE CONTENT INTENT 를 켜야 합니다.
시작할 때 켜져 있는지 확인하고, 꺼져 있으면 내용을 읽지 않고 무작위 소리로 답합니다 (켠 뒤 봇을 다시 띄우기).
꺼져 있어도 우사기 봇을 @멘션한 채팅은 디스코드가 내용을 보내 주므로 내용에 맞춰 답합니다.

사용법:
  .env 에 DISCORD_BOT_TOKEN, USAGI_CHANNEL_ID 를 넣고
  docker compose up -d usagi
  (도커 없이: uv run --python 3.12 --with discord.py==2.4.0 --with boto3 scripts/usagi_bot.py)
"""
import asyncio
import logging
import os
import random
import sys

import local_env

local_env.load()
sys.path.insert(0, str(local_env.ENV_FILE.parent / "src"))
import local_storage  # noqa: E402  (.env 의 LOCAL_S3_DIR 을 읽도록 load 뒤에 import)
import discord  # noqa: E402  (pip 의 discord.py 라이브러리. 우리 코드의 lunchbot.discord 와는 다른 것)
from lunchbot import chat, config, hachiware  # noqa: E402
from lunchbot import discord as discord_api  # noqa: E402

GATHER_S = 1.5  # 이만큼 새 채팅이 없으면 다 보낸 것으로 보고 답합니다
REPLYABLE = (discord.MessageType.default, discord.MessageType.reply)  # 입장 알림 같은 시스템 메시지에는 답 안 함
HACHIWARE_DELAY_S = (1.0, 2.2)  # 우사기가 답한 뒤 하치와레가 번역을 올리기까지 (초)

log = logging.getLogger("usagi")
waiting: dict = {}  # 채널 id → 답하려고 모으는 중인 채팅
last_reply: dict = {}  # 채널 id → 바로 전에 한 답 (되풀이하지 않게)
last_translation: dict = {}  # 채널 id → 하치와레의 바로 전 번역
hachiware_url = ""  # 우사기 채널 웹훅인지 확인한 뒤 main 에서 정함


async def handle(message):
    """채팅 하나를 받습니다. 이미 모으는 중이면 끼워 넣고, 아니면 조용해질 때까지 모았다가 답합니다."""
    if message.type not in REPLYABLE or message.webhook_id:  # 웹훅(하치와레)과는 주고받지 않음
        return
    parent = getattr(message.channel, "parent_id", None)  # 스레드면 그 스레드가 달린 채널
    if not chat.should_reply(message.author.bot, message.channel.id, config.USAGI_CHANNEL_ID, parent_id=parent):
        return
    channel_id = message.channel.id
    if channel_id in waiting:
        waiting[channel_id].append(message)
        return
    batch = waiting[channel_id] = [message]
    seen = 0
    while seen < len(batch):
        seen = len(batch)
        await asyncio.sleep(GATHER_S)
    del waiting[channel_id]
    await answer(batch)


async def answer(batch):
    channel, target = batch[-1].channel, batch[-1]
    text = "\n".join(m.content for m in batch)
    steps = chat.plan(text, last=last_reply.get(channel.id))
    last_reply[channel.id] = steps[0].text
    for step in steps:
        async with channel.typing():
            await asyncio.sleep(step.delay)
        if step.quote:
            await target.reply(step.text, mention_author=False)
        else:
            await channel.send(step.text)
    log.info("%s 의 채팅 %d개에 답함: %s", target.author.display_name, len(batch), " / ".join(s.text for s in steps))
    in_thread = bool(getattr(channel, "parent_id", None))
    # 모두가 보는 우사기 채널은 서버 전체 설정, 1:1 스레드는 채팅한 사람(여럿이면 마지막 사람)의 개인 설정
    if hachiware_url and translating(target.author.id if in_thread else None):
        await translate(channel.id, text, " ".join(s.text for s in steps), target.author.display_name, in_thread)


async def translate(channel_id, text: str, usagi: str, name: str, in_thread: bool = False):
    """하치와레가 우사기 말을 번역해 웹훅으로 올립니다 (스레드면 그 스레드에). 실패해도 우사기 답에는 영향이 없습니다."""
    await asyncio.sleep(random.uniform(*HACHIWARE_DELAY_S))
    line = hachiware.translate(chat.read(text), usagi, name=name, last=last_translation.get(channel_id))
    last_translation[channel_id] = line
    url = f"{hachiware_url}?thread_id={channel_id}" if in_thread else hachiware_url
    try:
        await asyncio.to_thread(discord_api.execute_webhook, url, line)
    except OSError as e:  # 오류 문구에는 웹훅 주소(토큰)가 들어가지 않음
        log.warning("하치와레 번역을 못 보냄: %s", e)
        return
    log.info("하치와레: %s", line)


def translating(user_id=None) -> bool:
    try:
        return hachiware.is_on(None if user_id is None else str(user_id))
    except Exception as e:  # 저장소를 못 읽으면 번역하지 않음
        log.warning("하치와레 번역 설정을 못 읽음: %s", e)
        return False


def hachiware_webhook(urls, channel_of=None) -> str:
    """하치와레 웹훅들 중 우사기 채널 것의 주소 (다른 채널에 번역이 올라가지 않게). 없으면 빈 글자."""
    if not urls:
        return ""
    url = discord_api.channel_webhooks(urls, channel_of).get(str(config.USAGI_CHANNEL_ID), "")
    if not url:
        log.warning("하치와레 웹훅 중 우사기 채널 것이 없어서(지워졌거나 다른 채널 주소) 번역하지 않습니다")
    return url


def make_client(read_content: bool) -> discord.Client:
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = read_content
    client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions.none())

    @client.event
    async def on_ready():
        how = "내용에 맞춰" if read_content else "내용을 읽지 않고 무작위로"
        log.info("%s 로 연결됨. 채널 %s 의 채팅에 %s 답합니다", client.user, config.USAGI_CHANNEL_ID, how)
        if hachiware_url:
            log.info("하치와레 웹훅 있음. 우사기 채널 번역(서버 전체) %s, 1:1 스레드는 사람마다",
                     "켜짐" if translating() else "꺼짐")
        else:
            log.info("하치와레 웹훅 없음 (HACHIWARE_WEBHOOK_URLS 에 우사기 채널 웹훅이 없거나 확인 실패)")

    @client.event
    async def on_message(message):
        await handle(message)

    return client


def main():
    global hachiware_url
    missing = [k for k in ("DISCORD_BOT_TOKEN", "USAGI_CHANNEL_ID") if not os.environ.get(k)]
    if missing:
        sys.exit(f"환경 변수가 없습니다: {', '.join(missing)} (.env 에 넣어 주세요)\n{__doc__}")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    local_storage.install()

    read_content = discord_api.can_read_messages(config.DISCORD_BOT_TOKEN)
    hachiware_url = hachiware_webhook(config.HACHIWARE_WEBHOOK_URLS)
    if not read_content:
        log.info("MESSAGE CONTENT INTENT 가 꺼져 있습니다. 개발자 포털 Bot 탭에서 켜고 다시 띄우면 채팅 내용에 맞춰 답합니다")
    try:
        make_client(read_content).run(config.DISCORD_BOT_TOKEN, log_handler=None)
    except discord.PrivilegedIntentsRequired:  # 확인한 뒤에 포털에서 꺼졌을 때
        log.warning("채팅 내용 읽기 권한이 거절되어 내용을 읽지 않고 다시 연결합니다")
        make_client(False).run(config.DISCORD_BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
