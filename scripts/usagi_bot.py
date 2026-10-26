"""우사기 채널 봇: 디스코드에 계속 연결해 두고, 우사기 채널에 사람이 채팅을 보내면 우사기 소리로 답합니다.

우사기 채널 아래 스레드(/우사기 로 만든 1:1 비공개 스레드)에서는 대화 기억(lunchbot/dialog.py)으로 답합니다:
물음의 의도에 맞춰 봇이 아는 정보로 답하고, 앞 문맥을 잇고, 그 사람의 기억(암호화)과 가르쳐 준 것을 씁니다.
1:1 스레드 대화는 로그에 남기지 않습니다 (채팅 내용·이름·우사기 소리·하치와레 말 모두).

버튼 처리(serve_local.py)는 디스코드가 우리 주소로 요청을 보내 주지만, 일반 채팅은 그렇게 받을 수 없어서
디스코드 게이트웨이(웹소켓)에 계속 붙어 있어야 합니다. 그래서 항상 켜 두는 서버로 띄웁니다 (docker compose 의 usagi).

답하는 모양 (어떤 소리를 낼지는 src/lunchbot/chat.py):
  - 연달아 보낸 채팅은 끝날 때까지(1.5초 조용할 때까지) 기다렸다가 합쳐서 한 번에 답합니다
  - 보내기 전에 '우사기 봇 입력 중…' 을 답 길이만큼 보여 주고, 답장 표시는 달 때도 안 달 때도 있습니다
  - 가끔 짧게 한마디를 더 보내고, 바로 전과 같은 답은 하지 않습니다
  - 하치와레 번역이 켜져 있으면 우사기가 답한 뒤 하치와레가 그 뜻을 번역해 올립니다. 우사기 채널은 서버 전체 설정
    (/전체번역 켜기, 기본 꺼짐), 1:1 스레드는 그 사람의 개인 설정(/하치와레 번역 켜기)을 따릅니다
    (src/lunchbot/hachiware.py). HACHIWARE_WEBHOOK_URLS 중 우사기 채널 웹훅으로 보내고, 없으면 번역하지 않습니다.
    켜짐/꺼짐은 버튼 서버와 같은 저장소(.local-s3/settings/hachiware.json)에서 답할 때마다 읽습니다

새로 들어온 사람은 우사기 채널에서 불러 환영하고, 생일 입력(선택)을 권합니다 (버튼 → 입력창, 처리는 버튼 서버).
생일 아침 9시에는 우사기 채널에서 그 사람을 불러 정해 둔 우사기 소리와 하치와레 번역 한 세트로 축하합니다
(번역 설정과 상관없이 늘, lunchbot/birthdays.py). 환영에는 SERVER MEMBERS INTENT 가 필요합니다.

채팅 내용에 맞춰 답하려면 개발자 포털 Bot 탭의 MESSAGE CONTENT INTENT 를 켜야 합니다.
시작할 때 켜져 있는지 확인하고, 꺼져 있으면 내용을 읽지 않고 무작위 소리로 답합니다 (켠 뒤 봇을 다시 띄우기).
꺼져 있어도 우사기 봇을 @멘션한 채팅은 디스코드가 내용을 보내 주므로 내용에 맞춰 답합니다.

사용법:
  .env 에 DISCORD_BOT_TOKEN, USAGI_CHANNEL_ID 를 넣고
  docker compose up -d usagi
  (도커 없이: uv run --python 3.12 --with discord.py==2.4.0 --with boto3 --with pynacl==1.5.0 scripts/usagi_bot.py)
"""
import asyncio
import logging
import os
import random
import sys
import urllib.error

import local_env

local_env.load()
sys.path.insert(0, str(local_env.ENV_FILE.parent / "src"))
import local_storage  # noqa: E402  (.env 의 LOCAL_S3_DIR 을 읽도록 load 뒤에 import)
import discord  # noqa: E402  (pip 의 discord.py 라이브러리. 우리 코드의 lunchbot.discord 와는 다른 것)
from lunchbot import birthdays, chat, config, dialog, hachiware  # noqa: E402
from lunchbot import discord as discord_api  # noqa: E402

GATHER_S = 1.5  # 이만큼 새 채팅이 없으면 다 보낸 것으로 보고 답합니다
REPLYABLE = (discord.MessageType.default, discord.MessageType.reply)  # 입장 알림 같은 시스템 메시지에는 답 안 함
HACHIWARE_DELAY_S = (1.0, 2.2)  # 우사기가 답한 뒤 하치와레가 번역을 올리기까지 (초)

log = logging.getLogger("usagi")
waiting: dict = {}  # 채널 id (1:1 스레드는 (스레드 id, 채팅한 사람 id)) → 답하려고 모으는 중인 채팅
last_reply: dict = {}  # 채널 id → 바로 전에 한 답 (되풀이하지 않게)
last_translation: dict = {}  # 채널 id → 하치와레의 바로 전 번역
hachiware_url = ""  # 우사기 채널 웹훅인지 확인한 뒤 main 에서 정함
talks = dialog.Dialog()  # 1:1 스레드 대화 (짧은 문맥은 사람마다 메모리에만)
QUIET = discord.AllowedMentions.none()  # 1:1 스레드에서는 누구도 부르지 않음


async def handle(message):
    """채팅 하나를 받습니다. 이미 모으는 중이면 끼워 넣고, 아니면 조용해질 때까지 모았다가 답합니다."""
    if message.type not in REPLYABLE or message.webhook_id:  # 웹훅(하치와레)과는 주고받지 않음
        return
    parent = getattr(message.channel, "parent_id", None)  # 스레드면 그 스레드가 달린 채널
    if not chat.should_reply(message.author.bot, message.channel.id, config.USAGI_CHANNEL_ID, parent_id=parent):
        return
    # 1:1 스레드는 사람마다 따로 모음: 스레드를 볼 수 있는 다른 사람의 채팅이 주인의 채팅과 섞이지 않게
    where = (message.channel.id, message.author.id) if parent else message.channel.id
    if where in waiting:
        waiting[where].append(message)
        return
    batch = waiting[where] = [message]
    seen = 0
    while seen < len(batch):
        seen = len(batch)
        await asyncio.sleep(GATHER_S)
    del waiting[where]
    await answer(batch)


async def _say(channel, steps, target=None, **kw) -> None:
    """우사기 답을 '입력 중…' 뒤에 보냅니다 (답장 표시를 달 때도)."""
    for step in steps:
        async with channel.typing():
            await asyncio.sleep(step.delay)
        if step.quote and target is not None:
            await target.reply(step.text, mention_author=False, **kw)
        else:
            await channel.send(step.text, **kw)


async def answer(batch):
    channel, target = batch[-1].channel, batch[-1]
    if getattr(channel, "parent_id", None):  # 1:1 스레드는 따로 (기억·로그 없음)
        await answer_in_thread(batch)
        return
    text = "\n".join(m.content for m in batch)
    steps = chat.plan(text, last=last_reply.get(channel.id))
    last_reply[channel.id] = steps[0].text
    await _say(channel, steps, target)
    log.info("%s 의 채팅 %d개에 답함: %s", target.author.display_name, len(batch), " / ".join(s.text for s in steps))
    if hachiware_url and translating():  # 모두가 보는 우사기 채널은 서버 전체 설정
        await translate(channel.id, text, " ".join(s.text for s in steps), target.author.display_name)


async def answer_in_thread(batch):
    """1:1 스레드: 대화 기억(lunchbot/dialog.py)으로 답합니다.

    스레드 대화는 어디에도 남기지 않으므로 로그도 남기지 않습니다 (채팅 내용·이름·우사기 소리·하치와레 말 모두).
    실패하면 무슨 종류의 오류인지만 남깁니다. 번역은 채팅한 사람의 개인 설정을 따릅니다.
    """
    channel, target = batch[-1].channel, batch[-1]
    text = "\n".join(m.content for m in batch)
    try:
        on = bool(hachiware_url) and translating(target.author.id)
        guild = channel.guild
        talk = await asyncio.to_thread(
            talks.respond, guild_id=str(guild.id), thread_id=str(channel.id), author_id=str(target.author.id),
            owner_id=str(guild.owner_id) if guild.owner_id else None, text=text, now=config.now_kst(), translating=on)
        for i, out in enumerate(talk.outs):
            await _say(channel, [chat.Step(out.sound, chat._typing(text, out.sound, random), quote=False)],
                       allowed_mentions=QUIET)
            delivered = bool(out.hachiware) and await _hachiware_in_thread(channel.id, out.hachiware)
            if talk.notice and i == 0 and delivered:  # 안내가 닿았을 때만 기록 시작
                await asyncio.to_thread(talks.noticed, str(guild.id), str(target.author.id), config.now_kst().date())
        if talk.plain:
            steps = chat.plan(text, last=last_reply.get(channel.id))
            last_reply[channel.id] = steps[0].text
            await _say(channel, steps, target, allowed_mentions=QUIET)
            if on:
                usagi = " ".join(s.text for s in steps)
                line = hachiware.translate(chat.read(text), usagi, name=target.author.display_name,
                                           last=last_translation.get(channel.id))
                last_translation[channel.id] = line
                await _hachiware_in_thread(channel.id, f"{line} {talk.remark}" if talk.remark else line)
    except Exception as e:  # 내용이 들어갈 수 있는 오류 문구는 남기지 않음
        log.warning("1:1 스레드 답을 못 보냄: %s", type(e).__name__)


async def _hachiware_in_thread(thread_id, line: str) -> bool:
    """하치와레가 1:1 스레드에 말합니다. 닿았으면 True.

    웹훅이 지워졌으면(401·404) 그 뒤로는 번역이 꺼진 것으로 봅니다 (안내를 못 보는 사람을 모르게 기록하지 않게).
    """
    global hachiware_url
    await asyncio.sleep(random.uniform(*HACHIWARE_DELAY_S))
    try:
        await asyncio.to_thread(discord_api.execute_webhook, f"{hachiware_url}?thread_id={thread_id}", line)
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            hachiware_url = ""
            log.warning("하치와레 웹훅이 없어져 번역을 멈춥니다 (HTTP %s). 웹훅을 다시 만들고 봇을 다시 띄워 주세요", e.code)
        else:
            log.warning("1:1 스레드에 하치와레 말을 못 보냄: HTTP %s", e.code)
        return False
    except OSError as e:
        log.warning("1:1 스레드에 하치와레 말을 못 보냄: %s", type(e).__name__)
        return False
    return True


async def translate(channel_id, text: str, usagi: str, name: str):
    """하치와레가 우사기 채널에서 우사기 말을 번역해 웹훅으로 올립니다. 실패해도 우사기 답에는 영향이 없습니다."""
    await asyncio.sleep(random.uniform(*HACHIWARE_DELAY_S))
    line = hachiware.translate(chat.read(text), usagi, name=name, last=last_translation.get(channel_id))
    last_translation[channel_id] = line
    try:
        await asyncio.to_thread(discord_api.execute_webhook, hachiware_url, line)
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


BIRTHDAY_HOUR = 9  # 생일 축하 시각 (KST). 봇이 그때 꺼져 있었으면 그날 켜지자마자
def welcome_payload(user_id: str, sound: str, guide: str = "") -> dict:
    """새로 들어온 사람 환영: 그 사람을 부르는 우사기 소리 + '생일 알려 주기' 버튼 (누르면 입력창, 버튼 서버가 처리).

    생일 안내는 하치와레가 합니다. 하치와레 웹훅이 없을 때만 guide 를 같은 메시지에 붙입니다.
    """
    button = {"type": 2, "style": 1, "label": "생일 알려 주기 (선택)", "custom_id": "bday:open"}
    content = f"<@{user_id}> {sound}"
    if guide:
        content += f"\n> **하치와레** {guide}"
    return {"content": content, "components": [{"type": 1, "components": [button]}],
            "allowed_mentions": {"parse": [], "users": [str(user_id)]}}


def welcome(user_id: str) -> None:
    """생일 안내가 꼭 닿아야 하니 번역 설정과 상관없이 하치와레가 말합니다 (버튼은 웹훅에 못 달아 우사기 메시지에)."""
    script = hachiware.welcome_script()
    line = hachiware.welcome_line(script)
    hook = hachiware.hooks().get(str(config.USAGI_CHANNEL_ID))
    discord_api.send_message(config.DISCORD_BOT_TOKEN, config.USAGI_CHANNEL_ID,
                             welcome_payload(user_id, script.sound, "" if hook else line))
    if hook:
        discord_api.execute_webhook(hook, line)


def celebrate(guild_id: str, day) -> list:
    """그날 생일인 사람마다 우사기 채널에서 축하합니다 (하루 한 번). 정해 둔 소리와 하치와레 번역을 한 세트로 늘."""
    if not birthdays.mark_sent(guild_id, day):
        return []
    people = birthdays.today(guild_id, day)
    hook = hachiware.hooks().get(str(config.USAGI_CHANNEL_ID))
    for uid in people:
        content = f"<@{uid}> {hachiware.BIRTHDAY.sound}"
        if not hook:  # 하치와레 웹훅이 없으면 같은 메시지에
            content += f"\n> **하치와레** {hachiware.BIRTHDAY_LINE}"
        discord_api.send_message(config.DISCORD_BOT_TOKEN, config.USAGI_CHANNEL_ID,
                                 {"content": content, "allowed_mentions": {"parse": [], "users": [str(uid)]}})
        if hook:
            discord_api.execute_webhook(hook, hachiware.BIRTHDAY_LINE)
    return people


async def birthday_loop(client) -> None:
    while True:
        now = config.now_kst()
        channel = client.get_channel(int(config.USAGI_CHANNEL_ID))
        if now.hour >= BIRTHDAY_HOUR and channel is not None:
            try:
                people = await asyncio.to_thread(celebrate, str(channel.guild.id), now.date())
                if people:
                    log.info("생일 축하: %s", people)
            except Exception:  # 다음 분에 다시 (오늘 이미 했으면 mark_sent 가 막음)
                log.exception("생일 축하 실패")
        await asyncio.sleep(60)


def make_client(read_content: bool, read_members: bool = False) -> discord.Client:
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = read_content
    intents.members = read_members  # 새로 들어온 사람 환영
    client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions.none())

    @client.event
    async def on_member_join(member):
        if member.bot or not config.USAGI_CHANNEL_ID:
            return
        try:
            await asyncio.to_thread(welcome, str(member.id))
            log.info("%s 환영", member.display_name)
        except Exception:
            log.exception("환영 실패")

    @client.event
    async def on_ready():
        if not getattr(client, "birthday_task", None):
            client.birthday_task = asyncio.create_task(birthday_loop(client))
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
    read_members = discord_api.can_read_members(config.DISCORD_BOT_TOKEN)
    hachiware_url = hachiware_webhook(config.HACHIWARE_WEBHOOK_URLS)
    if not read_content:
        log.info("MESSAGE CONTENT INTENT 가 꺼져 있습니다. 개발자 포털 Bot 탭에서 켜고 다시 띄우면 채팅 내용에 맞춰 답합니다")
    if not read_members:
        log.info("SERVER MEMBERS INTENT 가 꺼져 있어 새로 들어온 사람을 환영하지 않습니다")
    try:
        make_client(read_content, read_members).run(config.DISCORD_BOT_TOKEN, log_handler=None)
    except discord.PrivilegedIntentsRequired:  # 확인한 뒤에 포털에서 꺼졌을 때
        log.warning("특권 인텐트가 거절되어 채팅 내용·멤버 없이 다시 연결합니다")
        make_client(False, False).run(config.DISCORD_BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
