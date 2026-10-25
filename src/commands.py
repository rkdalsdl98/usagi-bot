"""우사기 명령 (디스코드 슬래시 명령). interaction.py 가 받아서 여기로 넘깁니다.

  /도움                         내 등급으로 쓸 수 있는 명령과 사용법 (모두)
  /우사기                        나와 우사기 봇만 있는 비공개 스레드에서 1:1 대화 (모두)
  /점심 추천, /저녁 추천           오점뭐·오저뭐로 메뉴 추천 보내기 (모두)
  /하치와레 번역 켜기·끄기          내 /우사기 1:1 스레드의 번역 켜고 끄기 (모두, 개인 설정)
  /전체번역 켜기·끄기          모두가 보는 채널의 번역 켜고 끄기: 우사기 채널 대화, 메뉴 추천·투표 결과, 명령 안내
                               (직장인 갑옷씨 이상, 서버 전체, 기본 꺼짐)
  /멤버추가 [사람]               멤버가 아닌 사람을 행인 갑옷씨로 (행인 갑옷씨 이상)
  /멤버승급·강등 [사람] [등급]     자기보다 낮은 멤버의 등급 바꾸기 (직장인 갑옷씨 이상)
  /멤버삭제 [사람]               자기보다 낮은 멤버를 멤버에서 빼기 (직장인 갑옷씨 이상)
  /추방 [사람]                   자기보다 낮은 사람을 서버에서 내보내기, 우사기가 '우라!' (직장인 갑옷씨 이상)

등급 규칙은 lunchbot/members.py 에 있습니다. 등급이 바뀌면 응답 뒤에 디스코드 갑옷씨 역할도 맞춥니다 (lunchbot/roles.py).

명령을 쓰면 우사기가 그 채널에 소리로 답하고(명령에 대한 응답, 모두가 봄), 하치와레 번역이 켜져 있으면 이어서
그 채널의 하치와레 웹훅이 결과나 까닭을 알립니다. 번역이 꺼져 있으면 하치와레는 말하지 않고 우사기 소리만 나갑니다. 하치와레 말은 응답을 돌려준 뒤에 보내야 우사기 소리 다음에 올라가므로 '나중에 할 일'(later)로
돌려줍니다. 하치와레 웹훅이 없는 채널에서는 우사기 답 아래에 하치와레 말을 붙입니다.
명령을 쓴 사람에게만 보이는 답은 /도움 뿐입니다. 웹훅은 '나만 보기'가 안 되므로 도움말은 답 안에 붙입니다.
/도움 은 사용법을 보는 명령이라 번역이 꺼져 있어도 보여 줍니다.

/점심 추천 · /저녁 추천의 실제 추천도 나중에 할 일입니다 (식당 수집이 디스코드의 3초 제한을 넘길 수 있음).
배포 환경에서는 추천 Lambda 를 따로 부릅니다 (RECOMMEND_FUNCTION_NAME).

명령 등록은 scripts/register_commands.py 로 합니다 (DEFINITIONS 를 서버에 올림).
"""
import json
import logging
import urllib.error
from dataclasses import dataclass, field

from lunchbot import config, discord, hachiware, meals, members, messages, roles, storage
import recommend

log = logging.getLogger()

SUB, GROUP, INTEGER, USER = 1, 2, 4, 6  # 명령 옵션 종류
CHANNEL_MESSAGE, EPHEMERAL = 4, 64


def _person(description: str) -> dict:
    return {"type": USER, "name": "사람", "description": description, "required": True}


def _rank(description: str) -> dict:
    choices = [{"name": name, "value": level} for level, name in members.RANKS.items()]
    return {"type": INTEGER, "name": "등급", "description": description, "required": True, "choices": choices}


def _sub(name: str, description: str, *options) -> dict:
    return {"type": SUB, "name": name, "description": description, "options": list(options)}


# 디스코드에 등록할 명령. 이름에 띄어쓰기를 못 넣어서 '명령 → 묶음 → 하위 명령'으로 '/하치와레 번역 켜기'처럼 보이게 함.
# 서버 설정 → 연동의 명령별 권한은 맨 앞 명령 단위로만 걸리므로, 필요한 등급이 다른 명령은 맨 앞 명령을 따로 둠
# (/전체번역 은 /하치와레 와, /멤버추가 는 /멤버승급 과 따로)
DEFINITIONS = [
    {"name": "도움", "description": "내 등급으로 쓸 수 있는 우사기 명령과 사용법을 하치와레가 알려 줘요", "contexts": [0]},
    {"name": "우사기", "description": "나와 우사기 봇만 있는 비공개 스레드에서 1:1로 대화해요", "contexts": [0]},
    {"name": "점심", "description": "점심 메뉴", "contexts": [0],
     "options": [_sub("추천", "오점뭐 채널에 점심 메뉴 5곳을 추천해요")]},
    {"name": "저녁", "description": "저녁 메뉴", "contexts": [0],
     "options": [_sub("추천", "오저뭐 채널에 야근 저녁 메뉴(식사 4곳 + 술집 1곳)를 추천해요")]},
    {"name": "하치와레", "description": "하치와레 (누구나)", "contexts": [0],
     "options": [{"type": GROUP, "name": "번역", "description": "내 /우사기 1:1 스레드의 번역 (개인 설정)",
                  "options": [_sub("켜기", "내 /우사기 1:1 스레드에서 우사기 말을 번역해요"),
                              _sub("끄기", "내 /우사기 1:1 스레드의 번역을 꺼요")]}]},
    {"name": "전체번역", "description": "모두가 보는 채널의 하치와레 번역 (서버 전체, 직장인 갑옷씨 이상)", "contexts": [0],
     "options": [_sub("켜기", "우사기 채널·메뉴 추천·투표 결과·명령 안내를 번역해요 (직장인 갑옷씨 이상)"),
                 _sub("끄기", "모두가 보는 채널의 번역을 꺼요 (직장인 갑옷씨 이상)")]},
    {"name": "멤버추가", "description": "멤버가 아닌 사람을 행인 갑옷씨로 등록해요 (행인 갑옷씨 이상)", "contexts": [0],
     "options": [_person("등록할 사람")]},
    {"name": "멤버승급", "description": "나보다 낮은 멤버를 내 등급까지 올려요 (직장인 갑옷씨 이상)", "contexts": [0],
     "options": [_person("올릴 멤버"), _rank("올릴 등급")]},
    {"name": "멤버강등", "description": "나보다 낮은 멤버의 등급을 내려요 (직장인 갑옷씨 이상)", "contexts": [0],
     "options": [_person("내릴 멤버"), _rank("내릴 등급")]},
    {"name": "멤버삭제", "description": "나보다 낮은 멤버를 멤버에서 빼요 (직장인 갑옷씨 이상)", "contexts": [0],
     "options": [_person("뺄 멤버")]},
    {"name": "추방", "description": "나보다 낮은 사람을 서버에서 내보내요 (직장인 갑옷씨 이상)", "contexts": [0],
     "options": [_person("내보낼 사람")]},
]

# /도움 에 보일 사용법과 뜻 (순서는 members.NEEDS)
USAGE = {
    "도움": ("/도움", "쓸 수 있는 명령과 사용법 보기"),
    "우사기": ("/우사기", "나와 우사기만 있는 비공개 스레드에서 1:1 대화"),
    "점심 추천": ("/점심 추천", "오점뭐에 점심 메뉴 추천 보내기"),
    "저녁 추천": ("/저녁 추천", "오저뭐에 야근 저녁 메뉴 추천 보내기"),
    "하치와레 번역 켜기": ("/하치와레 번역 켜기", "내 /우사기 1:1 스레드에서 하치와레가 번역"),
    "하치와레 번역 끄기": ("/하치와레 번역 끄기", "내 1:1 스레드의 번역 멈추기"),
    "멤버추가": ("/멤버추가 [사람]", "멤버가 아닌 사람을 행인 갑옷씨로 등록"),
    "멤버승급": ("/멤버승급 [사람] [등급]", "나보다 낮은 멤버를 내 등급까지 올리기"),
    "멤버강등": ("/멤버강등 [사람] [등급]", "나보다 낮은 멤버의 등급 내리기"),
    "멤버삭제": ("/멤버삭제 [사람]", "나보다 낮은 멤버를 멤버에서 빼기"),
    "추방": ("/추방 [사람]", "나보다 낮은 사람을 서버에서 내보내기 (우사기가 '우라!')"),
    "전체번역 켜기": ("/전체번역 켜기", "모두가 보는 채널(우사기 채널·메뉴 추천·투표 결과·명령 안내) 번역 켜기"),
    "전체번역 끄기": ("/전체번역 끄기", "모두가 보는 채널의 번역 끄기"),
}


@dataclass
class Outcome:
    sound: str  # 우사기가 채널에 낼 소리
    notice: str  # 하치와레가 할 말
    private: bool = False  # 명령을 쓴 사람에게만 보일지 (/도움)
    later: list = field(default_factory=list)  # 하치와레 말 뒤에 할 일


def _said(key: str, later=None, **kw) -> Outcome:
    """명령 결과를 우사기 소리와 하치와레 번역으로 (소리 한 토막마다 번역 한 토막, hachiware.notice_script)."""
    script = hachiware.notice_script(key, **kw)
    return Outcome(script.sound, hachiware.relay(script.text), later=later or [])


_owners: dict = {}


def _owner(guild_id: str):
    if guild_id not in _owners:
        _owners[guild_id] = discord.guild_owner(config.DISCORD_BOT_TOKEN, guild_id)
    return _owners[guild_id]


def parse(data: dict) -> tuple[str, dict]:
    """('멤버추가', {'사람': '123'}). 하위 명령과 묶음은 이름에 이어 붙입니다."""
    words, opts = [data["name"]], data.get("options") or []
    while opts and opts[0]["type"] in (SUB, GROUP):
        words.append(opts[0]["name"])
        opts = opts[0].get("options") or []
    return " ".join(words), {o["name"]: o["value"] for o in opts}


def _name(member: dict, user: dict) -> str:
    return member.get("nick") or user.get("global_name") or user.get("username") or "누군가"


def _place(interaction: dict) -> tuple[str, str | None, str | None]:
    """(하치와레 웹훅을 고를 채널, 스레드 id, 따를 개인 설정의 사용자 id).

    모두가 보는 채널은 서버 전체 설정(사용자 id 없음), 우사기 채널 아래 1:1 스레드 안이면 그 사람의 개인 설정을 따르고
    하치와레는 우사기 채널 웹훅으로 그 스레드에 말합니다.
    """
    channel = interaction.get("channel") or {}
    channel_id = str(interaction.get("channel_id") or channel.get("id"))
    usagi = str(config.USAGI_CHANNEL_ID)
    if usagi and channel.get("type") in (11, 12) and str(channel.get("parent_id")) == usagi:  # 공개·비공개 스레드
        return usagi, channel_id, ((interaction.get("member") or {}).get("user") or {}).get("id")
    return channel_id, None, None


def handle(interaction: dict) -> tuple[dict, list]:
    """(디스코드에 돌려줄 응답, 응답 뒤에 할 일)."""
    command, args = parse(interaction["data"])
    place = _place(interaction)
    if command not in members.NEEDS:
        return _reply(_said("unknown"), place)

    guild_id = interaction["guild_id"]
    roster = members.load(guild_id)
    owner_id = _owner(guild_id)
    member = interaction.get("member") or {}
    user = member.get("user") or {}
    actor = members.person(user["id"], _name(member, user), roster, owner_id)
    target = None
    if "사람" in args:
        resolved = interaction["data"].get("resolved") or {}
        tid = str(args["사람"])
        tuser = (resolved.get("users") or {}).get(tid, {})
        target = members.person(tid, _name((resolved.get("members") or {}).get(tid, {}), tuser), roster, owner_id,
                                bot=bool(tuser.get("bot")))
    rank = args.get("등급")

    reason = members.check(command, actor, target, rank)
    if reason:
        outcome = _refused(reason, actor, target, rank, command)
    else:
        outcome = RUN[command](actor=actor, target=target, rank=rank, roster=roster, guild_id=guild_id,
                               interaction=interaction)
    log.info("우사기 명령 /%s (%s): %s", command, actor.name, reason or "완료")
    return _reply(outcome, place)


def _reply(outcome: Outcome, place) -> tuple[dict, list]:
    hook_channel, thread, user_id = place
    data = {"content": outcome.sound, "allowed_mentions": {"parse": []}}  # 멘션 알림은 보내지 않음
    if not outcome.private and not hachiware.is_on(user_id):  # 이곳의 번역이 꺼져 있으면 우사기 소리만
        return {"type": CHANNEL_MESSAGE, "data": data}, outcome.later
    hook = None if outcome.private else hachiware.hooks().get(hook_channel)
    if hook:  # 우사기 소리는 응답으로, 하치와레 말은 응답 뒤에 그 채널(스레드) 웹훅으로
        url = f"{hook}?thread_id={thread}" if thread else hook
        return {"type": CHANNEL_MESSAGE, "data": data}, [lambda: discord.execute_webhook(url, outcome.notice)] + outcome.later
    data["content"] = f"{outcome.sound}\n>>> **하치와레** {outcome.notice}"
    if outcome.private:
        data["flags"] = EPHEMERAL
    return {"type": CHANNEL_MESSAGE, "data": data}, outcome.later


def _mention(person) -> str:
    return f"<@{person.id}>" if person else ""


def _refused(reason, actor, target, rank, command) -> Outcome:
    level = actor.level
    return _said(
        reason,
        actor=_mention(actor),
        target=_mention(target),
        need=f"**{members.RANKS.get(members.NEEDS[command], '')}**",
        now=f"지금은 **{members.RANKS[level]}**…" if level else "아직 멤버가 아니야…",
        rank=f"**{members.RANKS.get(level, '')}**",
        target_rank=f"**{members.RANKS.get(target.level, '')}**" if target else "",
    )


def _stamp(actor) -> dict:
    return {"by": actor.name, "at": config.now_kst().isoformat()}


def _role_job(guild_id: str, user_id: str, level: int, interaction: dict):
    """응답 뒤에 그 사람의 갑옷씨 역할을 맞춥니다. 못 맞추면 명령을 쓴 사람에게만 알립니다 (등급은 이미 바뀜)."""
    def run():
        try:
            roles.sync(guild_id, user_id, level)
        except OSError as e:  # HTTPError(권한·역할 순서)·연결 오류
            log.warning("갑옷씨 역할을 못 맞춤 (%s): %s", user_id, e)
            discord.followup(interaction["application_id"], interaction["token"],
                             f"{messages.huh_sound()}\n-# 갑옷씨 역할을 못 맞췄어요. 봇 역할에 '역할 관리' 권한이 있고, "
                             "봇 역할이 갑옷씨 역할들보다 위에 있는지 확인해 주세요.")

    return run


def _add(actor, target, roster, guild_id, interaction, **_) -> Outcome:
    roster[target.id] = {"rank": members.WALKER, "name": target.name, **_stamp(actor)}
    members.save(guild_id, roster)
    return _said("added", later=[_role_job(guild_id, target.id, members.WALKER, interaction)], target=_mention(target))


def _set_rank(actor, target, rank, roster, guild_id, interaction, **_) -> Outcome:
    up = rank > target.level
    roster[target.id] = {**roster.get(target.id, {}), "rank": rank, "name": target.name, **_stamp(actor)}
    members.save(guild_id, roster)
    return _said("promoted" if up else "demoted", later=[_role_job(guild_id, target.id, rank, interaction)],
                 target=_mention(target), new=f"**{members.RANKS[rank]}**")


def _remove(target, roster, guild_id, interaction, **_) -> Outcome:
    roster.pop(target.id, None)
    members.save(guild_id, roster)
    return _said("removed", later=[_role_job(guild_id, target.id, 0, interaction)], target=_mention(target))


def _kick(actor, target, roster, guild_id, **_) -> Outcome:
    try:
        discord.kick_member(config.DISCORD_BOT_TOKEN, guild_id, target.id, f"우사기 명령 /추방 ({actor.name})")
    except urllib.error.HTTPError as e:
        log.warning("추방 실패 (%s): HTTP %s", target.name, e.code)
        return _said("kick_gone" if e.code == 404 else "kick_failed", target=_mention(target))
    if roster.pop(target.id, None):
        members.save(guild_id, roster)
    return _said("kicked", target=_mention(target))  # 우사기가 '우라!'


def _help(actor, **_) -> Outcome:
    text = hachiware.help_text(_mention(actor), actor.level, USAGE, hachiware.is_on(actor.id), hachiware.is_on())
    return Outcome(messages.picked_sound(), text, private=True)


def _translate(on: bool):
    """나에 대한 번역 (개인 설정)."""
    def run(actor, **_) -> Outcome:
        changed = hachiware.turn(on, actor.name, user_id=actor.id)
        return _said(("translate_on" if on else "translate_off") + ("" if changed else "_already"))

    return run


def _menu_translate(on: bool):
    """메뉴 추천·투표 결과 번역 (서버 전체)."""
    def run(actor, **_) -> Outcome:
        changed = hachiware.turn(on, actor.name)
        return _said(("menu_on" if on else "menu_off") + ("" if changed else "_already"))

    return run


def _usagi(actor, guild_id, **_) -> Outcome:
    """나와 우사기 봇만 있는 비공개 스레드 (우사기 채널 아래). 사람마다 하나이고, 다시 부르면 그 스레드를 다시 엽니다.

    스레드 안의 대화는 우사기 채널 봇(usagi_bot.py)이 우사기 채널에서처럼 받습니다.
    """
    parent, token = config.USAGI_CHANNEL_ID, config.DISCORD_BOT_TOKEN
    if not parent:
        return _said("no_usagi_channel")
    record = storage.get_json(storage.threads_key(guild_id)) or {}
    mine = record.setdefault("usagi", {})
    try:
        thread = discord.get_channel(token, mine[actor.id]) if actor.id in mine else None
        if thread and (thread.get("thread_metadata") or {}).get("archived"):  # 오래 조용해서 보관됨
            discord.unarchive_thread(token, thread["id"])
        if not thread:  # 처음이거나 누가 스레드를 지웠으면 새로
            thread = discord.create_thread(token, parent, f"우사기 · {actor.name}")
            mine[actor.id] = thread["id"]
            storage.put_json(storage.threads_key(guild_id), record)
        discord.add_thread_member(token, thread["id"], actor.id)
    except urllib.error.HTTPError as e:
        log.warning("/우사기 스레드 실패 (%s): HTTP %s", actor.name, e.code)
        return _said("thread_failed")
    tid = thread["id"]

    def greet():  # 우사기가 스레드에서 그 사람을 불러 인사 (알림이 가서 스레드를 찾게), 번역이 켜져 있으면 하치와레도
        script = hachiware.greet_script()
        discord.send_message(token, tid, {"content": f"<@{actor.id}> {script.sound}", "allowed_mentions": {"users": [actor.id]}})
        hachiware.say(parent, hachiware.relay(script.text), thread=tid, user_id=actor.id)

    return _said("usagi_thread", later=[greet], thread=f"<#{tid}>")


def _invoke(function_name: str, payload: dict) -> None:
    import boto3  # 배포 환경에서만 씀

    boto3.client("lambda").invoke(FunctionName=function_name, InvocationType="Event", Payload=json.dumps(payload).encode())


def _recommend(meal_name: str):
    def run(actor, interaction, **_) -> Outcome:
        meal = meals.get(meal_name)
        what = "저녁" if meal_name == meals.DINNER else "점심"
        if not meal.channel_id:
            return _said("no_channel", meal=what, setting=meal.channel_setting)
        hook_channel, thread, user_id = _place(interaction)
        hook = hachiware.hooks().get(hook_channel)
        if hook and thread:
            hook = f"{hook}?thread_id={thread}"

        def send():
            try:
                if config.RECOMMEND_FUNCTION_NAME:  # 배포: 추천 Lambda 를 따로 부름 (오래 걸릴 수 있어서)
                    _invoke(config.RECOMMEND_FUNCTION_NAME, {"meal": meal_name})
                else:
                    recommend.handler({"meal": meal_name}, None)
            except Exception:
                log.exception("/%s 추천 실패", what)
                failed = hachiware.notice_script("recommend_failed", meal=what)
                app, token = interaction["application_id"], interaction["token"]
                if not hachiware.is_on(user_id):  # 이곳의 번역이 꺼져 있으면 우사기 소리만, 쓴 사람에게
                    discord.followup(app, token, failed.sound)
                elif hook:  # 우사기 소리 (명령의 후속 메시지) 다음에 하치와레 번역
                    discord.followup(app, token, failed.sound, ephemeral=False)
                    discord.execute_webhook(hook, hachiware.relay(failed.text))
                else:  # 웹훅이 없는 채널: 후속 메시지 하나에 함께
                    discord.followup(app, token, f"{failed.sound}\n>>> **하치와레** {hachiware.relay(failed.text)}",
                                     ephemeral=False)

        return _said("recommend", later=[send], channel=f"<#{meal.channel_id}>", meal=what)

    return run


RUN = {
    "도움": _help,
    "우사기": _usagi,
    "점심 추천": _recommend(meals.LUNCH),
    "저녁 추천": _recommend(meals.DINNER),
    "하치와레 번역 켜기": _translate(True),
    "하치와레 번역 끄기": _translate(False),
    "전체번역 켜기": _menu_translate(True),
    "전체번역 끄기": _menu_translate(False),
    "멤버추가": _add,
    "멤버승급": _set_rank,
    "멤버강등": _set_rank,
    "멤버삭제": _remove,
    "추방": _kick,
}
