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
  /생일 등록·지우기               생일 알려 주기 (선택, 생일 아침에 우사기 채널에서 축하) (모두)
  /게임 시작·답·결과·점수·끝        이미지 랜덤 주제 게임 (모두, 게임 안의 역할은 lunchbot/game.py)

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
import random
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime

from lunchbot import (birthdays, config, departed, discord, game, hachiware, inbox, meals, members, memory, messages,
                     reminders, roles, storage)
import recommend

log = logging.getLogger()

SUB, GROUP, STRING, INTEGER, USER = 1, 2, 3, 4, 6  # 명령 옵션 종류
CHANNEL_MESSAGE, UPDATE_MESSAGE, MODAL, EPHEMERAL = 4, 7, 9, 64
ROW, BUTTON, TEXT_INPUT, USER_SELECT = 1, 2, 4, 5  # 컴포넌트 종류


def _person(description: str) -> dict:
    return {"type": USER, "name": "사람", "description": description, "required": True}


def _rank(description: str) -> dict:
    choices = [{"name": name, "value": level} for level, name in members.RANKS.items()]
    return {"type": INTEGER, "name": "등급", "description": description, "required": True, "choices": choices}


def _text(name: str, description: str, max_length: int) -> dict:
    return {"type": STRING, "name": name, "description": description, "required": True, "max_length": max_length}


def _int(name: str, description: str, low: int, high: int, required: bool = True) -> dict:
    return {"type": INTEGER, "name": name, "description": description, "required": required,
            "min_value": low, "max_value": high}


def _sub(name: str, description: str, *options) -> dict:
    return {"type": SUB, "name": name, "description": description, "options": list(options)}


_YEAR = config.now_kst().year  # /리마인드 [년] 에 넣을 수 있는 해 (올해부터 5년)

# 디스코드에 등록할 명령. 이름에 띄어쓰기를 못 넣어서 '명령 → 묶음 → 하위 명령'으로 '/하치와레 번역 켜기'처럼 보이게 함.
# 서버 설정 → 연동의 명령별 권한은 맨 앞 명령 단위로만 걸리므로, 필요한 등급이 다른 명령은 맨 앞 명령을 따로 둠
# (/전체번역 은 /하치와레 와, /멤버추가 는 /멤버승급 과 따로)
DEFINITIONS = [
    {"name": "도움", "description": "내 등급으로 쓸 수 있는 우사기 명령과 사용법을 하치와레가 알려 줘요", "contexts": [0]},
    {"name": "우사기", "description": "나와 우사기 봇만 있는 비공개 스레드에서 1:1로 대화해요", "contexts": [0]},
    {"name": "리마인드", "description": "정한 시각에 하치와레가 1:1 스레드에서 알려 줘요 (년·월·일을 비우면 오늘)",
     "contexts": [0], "options": [
        _text("내용", "알려 받을 내용", reminders.TEXT_CHARS), _int("시간", "몇 시 (0~23)", 0, 23),
        _int("분", "몇 분 (0~59)", 0, 59), _int("년", "몇 년 (비우면 올해)", _YEAR, _YEAR + 5, required=False),
        _int("월", "몇 월 (비우면 이번 달)", 1, 12, required=False), _int("일", "며칠 (비우면 오늘)", 1, 31, required=False),
    ]},
    {"name": "리마인드목록", "description": "내가 걸어 둔 리마인드를 봐요 (나만 보여요)", "contexts": [0]},
    {"name": "전체리마인드", "description": "정한 시각에 하치와레가 이 채널에서 모두(@everyone)를 불러 알려 줘요",
     "contexts": [0], "options": [
        _text("내용", "모두에게 알릴 내용", reminders.TEXT_CHARS), _int("시간", "몇 시 (0~23)", 0, 23),
        _int("분", "몇 분 (0~59)", 0, 59), _int("년", "몇 년 (비우면 올해)", _YEAR, _YEAR + 5, required=False),
        _int("월", "몇 월 (비우면 이번 달)", 1, 12, required=False), _int("일", "며칠 (비우면 오늘)", 1, 31, required=False),
    ]},
    {"name": "전체리마인드목록", "description": "걸려 있는 전체 리마인드를 봐요 (나만 보여요)", "contexts": [0]},
    {"name": "전체리마인드취소", "description": "전체 리마인드 하나를 지워요 (건 사람이나 대장 갑옷씨)", "contexts": [0],
     "options": [_int("번호", "지울 전체 리마인드 번호 (/전체리마인드목록)", 1, reminders.LIMIT)]},
    {"name": "리마인드취소", "description": "리마인드 하나를 지워요 (번호는 /리마인드목록)", "contexts": [0], "options": [
        _int("번호", "지울 리마인드 번호", 1, reminders.LIMIT)]},
    {"name": "기억", "description": "1:1 대화에서 우사기가 나에 대해 기억하는 것 (나만 보여요)", "contexts": [0], "options": [
        _sub("보기", "우사기가 나에 대해 기억하는 것과 내가 가르친 것을 봐요"),
        _sub("지우기", "가르친 것 하나를 지우거나, 번호를 비우면 기억을 전부 지워요",
             _int("번호", "지울 가르친 것 번호 (비우면 전부 지워요)", 1, 50, required=False)),
    ]},
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
    {"name": "생일", "description": "생일 (선택, 생일 아침에 우사기 채널에서 축하해요)", "contexts": [0], "options": [
        _sub("등록", "생일을 알려 줘요. 생일 아침 9시에 우사기 채널에서 축하 알림을 보내요",
             _int("월", "생일 월", 1, 12), _int("일", "생일 일", 1, 31)),
        _sub("지우기", "알려 준 생일을 지워요"),
    ]},
    {"name": "게임", "description": "이미지 랜덤 주제 게임", "contexts": [0], "options": [
        _sub("시작", "주제를 정하고 참가자를 골라 게임을 시작해요", _text("주제", "이번 게임의 주제", 100)),
        _sub("답", "술래에 대한 내 생각을 보내요 (다른 사람에게는 안 보여요)", _text("내용", "주제에 맞춘 술래에 대한 생각", 200)),
        _sub("결과", "사회자가 술래가 맞힌 수를 보내요", _int("맞힌수", "술래가 맞힌 답의 수", 0, 25)),
        _sub("점수", "지금 점수판을 봐요"),
        _sub("끝", "게임을 멈춰요 (시작한 사람, 대장 갑옷씨)"),
    ]},
]

# /도움 에 보일 사용법과 뜻 (순서는 members.NEEDS)
USAGE = {
    "도움": ("/도움", "쓸 수 있는 명령과 사용법 보기"),
    "우사기": ("/우사기", "나와 우사기만 있는 비공개 스레드에서 1:1 대화"),
    "리마인드": ("/리마인드 [내용] [시간] [분] [년] [월] [일]", "정한 시각에 하치와레가 1:1 스레드에서 알려 줌 (년·월·일은 비우면 오늘)"),
    "리마인드목록": ("/리마인드목록", "내가 걸어 둔 리마인드 보기 (나만 보여요)"),
    "리마인드취소": ("/리마인드취소 [번호]", "리마인드 하나 지우기 (번호는 /리마인드목록)"),
    "전체리마인드": ("/전체리마인드 [내용] [시간] [분] [년] [월] [일]", "정한 시각에 하치와레가 이 채널에서 모두를 불러 알려 줌"),
    "전체리마인드목록": ("/전체리마인드목록", "걸려 있는 전체 리마인드 보기 (나만 보여요)"),
    "전체리마인드취소": ("/전체리마인드취소 [번호]", "전체 리마인드 하나 지우기 (건 사람이나 대장 갑옷씨)"),
    "기억 보기": ("/기억 보기", "1:1 대화에서 우사기가 나에 대해 기억하는 것 보기 (나만 보여요)"),
    "기억 지우기": ("/기억 지우기 [번호]", "가르친 것 하나, 또는 번호 없이 기억 전부 지우기 (나만 보여요)"),
    "점심 추천": ("/점심 추천", "오점뭐에 점심 메뉴 추천 보내기"),
    "저녁 추천": ("/저녁 추천", "오저뭐에 야근 저녁 메뉴 추천 보내기"),
    "하치와레 번역 켜기": ("/하치와레 번역 켜기", "내 /우사기 1:1 스레드에서 하치와레가 번역"),
    "하치와레 번역 끄기": ("/하치와레 번역 끄기", "내 1:1 스레드의 번역 멈추기"),
    "멤버추가": ("/멤버추가 [사람]", "멤버가 아닌 사람을 행인 갑옷씨로 등록"),
    "멤버승급": ("/멤버승급 [사람] [등급]", "나보다 낮은 멤버를 내 등급까지 올리기"),
    "멤버강등": ("/멤버강등 [사람] [등급]", "나보다 낮은 멤버의 등급 내리기"),
    "멤버삭제": ("/멤버삭제 [사람]", "나보다 낮은 멤버를 멤버에서 빼기"),
    "추방": ("/추방 [사람]", "나보다 낮은 사람을 서버에서 내보내기 (우사기가 '우라!')"),
    "생일 등록": ("/생일 등록 [월] [일]", "생일 알려 주기 (선택, 생일 아침에 우사기 채널에서 축하)"),
    "생일 지우기": ("/생일 지우기", "알려 준 생일 지우기"),
    "게임 시작": ("/게임 시작 [주제]", "이미지 랜덤 주제 게임 시작 (참가자 고르기)"),
    "게임 답": ("/게임 답 [내용]", "술래에 대한 내 생각 보내기 (나만 보여요)"),
    "게임 결과": ("/게임 결과 [맞힌수]", "사회자가 술래가 맞힌 수 보내기"),
    "게임 점수": ("/게임 점수", "지금 점수판 보기"),
    "게임 끝": ("/게임 끝", "게임 멈추기 (시작한 사람, 대장 갑옷씨)"),
    "전체번역 켜기": ("/전체번역 켜기", "모두가 보는 채널(우사기 채널·메뉴 추천·투표 결과·명령 안내) 번역 켜기"),
    "전체번역 끄기": ("/전체번역 끄기", "모두가 보는 채널의 번역 끄기"),
}


@dataclass
class Outcome:
    sound: str  # 우사기가 채널에 낼 소리
    notice: str  # 하치와레가 할 말
    private: bool = False  # 명령을 쓴 사람에게만 보일지 (/도움, 게임 답·사회자 답 보기, 생일)
    later: list = field(default_factory=list)  # 하치와레 말 뒤에 할 일
    always: bool = False  # 번역 설정과 상관없이 하치와레가 말할지 (게임)
    info: str = ""  # 우사기 소리 아래 작은 글씨 안내 (게임 점수판 등)
    components: list = field(default_factory=list)  # 버튼·선택칸
    direct: bool = False  # 우사기 소리를 옮기지 않고 하치와레가 바로 말함 (리마인드 등록, 번역 설정과 상관없이)


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
                               interaction=interaction, args=args)
    log.info("우사기 명령 /%s (%s): %s", command, actor.name, reason or "완료")
    return _reply(outcome, place)


def _direct(outcome: Outcome, place) -> tuple[dict, list]:
    """하치와레가 바로 말함 (우사기 소리 없이). 모두가 보는 곳이면 그 채널 웹훅으로 하치와레가 올리고 쓴 사람에게는 확인만."""
    hook_channel, thread, _ = place
    text = outcome.notice + (f"\n{outcome.info}" if outcome.info else "")
    hook = None if outcome.private else hachiware.hooks().get(hook_channel)
    if hook:
        url = f"{hook}?thread_id={thread}" if thread else hook
        ack = {"content": "-# 하치와레가 이곳에 알렸어요.", "flags": EPHEMERAL, "allowed_mentions": {"parse": []}}
        return {"type": CHANNEL_MESSAGE, "data": ack}, [lambda: discord.execute_webhook(url, text)] + outcome.later
    data = {"content": f">>> **하치와레** {text}", "allowed_mentions": {"parse": []}}
    if outcome.private:
        data["flags"] = EPHEMERAL
    return {"type": CHANNEL_MESSAGE, "data": data}, outcome.later


def _reply(outcome: Outcome, place) -> tuple[dict, list]:
    if outcome.direct:
        return _direct(outcome, place)
    hook_channel, thread, user_id = place
    content = outcome.sound + (f"\n{outcome.info}" if outcome.info else "")
    data = {"content": content, "allowed_mentions": {"parse": []}}  # 멘션 알림은 보내지 않음
    if outcome.components:
        data["components"] = outcome.components
    if not outcome.private and not outcome.always and not hachiware.is_on(user_id):  # 이곳의 번역이 꺼져 있으면 우사기 소리만
        return {"type": CHANNEL_MESSAGE, "data": data}, outcome.later
    hook = None if outcome.private else hachiware.hooks().get(hook_channel)
    if hook:  # 우사기 소리는 응답으로, 하치와레 말은 응답 뒤에 그 채널(스레드) 웹훅으로
        url = f"{hook}?thread_id={thread}" if thread else hook
        return {"type": CHANNEL_MESSAGE, "data": data}, [lambda: discord.execute_webhook(url, outcome.notice)] + outcome.later
    if outcome.info:  # 하치와레 말 한 줄 + 안내
        data["content"] = f"{outcome.sound}\n> **하치와레** {outcome.notice}\n{outcome.info}"
    else:
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
    later = [_role_job(guild_id, target.id, rank, interaction)] + _leave_thread_jobs(guild_id, target.id, rank)
    return _said("promoted" if up else "demoted", later=later, target=_mention(target),
                 new=f"**{members.RANKS[rank]}**")


def _remove(target, roster, guild_id, interaction, **_) -> Outcome:
    roster.pop(target.id, None)
    members.save(guild_id, roster)
    later = [_role_job(guild_id, target.id, 0, interaction)] + _leave_thread_jobs(guild_id, target.id, 0)
    return _said("removed", later=later, target=_mention(target))


def _leave_thread_jobs(guild_id: str, user_id: str, level: int) -> list:
    """직장인 갑옷씨 아래가 되면 응답 뒤에 1:1 스레드에서 내보냅니다 (기억과 스레드 기록은 그대로 둠).

    공개 답에는 스레드 이야기를 하지 않습니다 (그 사람이 1:1 을 썼는지 드러나지 않게).
    """
    if level >= members.NEEDS["우사기"]:
        return []
    thread = ((storage.get_json(storage.threads_key(guild_id)) or {}).get("usagi") or {}).get(user_id)
    if not thread:
        return []

    def run():
        try:
            discord.remove_thread_member(config.DISCORD_BOT_TOKEN, thread, user_id)
        except urllib.error.HTTPError as e:
            if e.code != 404:  # 이미 없으면 그대로
                log.warning("1:1 스레드에서 못 내보냄: HTTP %s", e.code)

    return [run]


def _kick(actor, target, roster, guild_id, **_) -> Outcome:
    try:
        discord.kick_member(config.DISCORD_BOT_TOKEN, guild_id, target.id, f"우사기 명령 /추방 ({actor.name})")
    except urllib.error.HTTPError as e:
        log.warning("추방 실패 (%s): HTTP %s", target.name, e.code)
        return _said("kick_gone" if e.code == 404 else "kick_failed", target=_mention(target))
    if roster.pop(target.id, None):
        members.save(guild_id, roster)
    departed.forget_person(guild_id, target.id)  # 사람별 기록과 1:1 스레드도 바로 지움 (처리 줄 안이라 겹치지 않음)
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
    try:
        tid = _open_thread(actor, guild_id)
    except urllib.error.HTTPError as e:
        log.warning("/우사기 스레드 실패 (%s): HTTP %s", actor.name, e.code)
        return _said("thread_failed")

    def greet():  # 우사기가 스레드에서 그 사람을 불러 인사 (알림이 가서 스레드를 찾게), 번역이 켜져 있으면 하치와레도
        script = hachiware.greet_script()
        discord.send_message(token, tid, {"content": f"<@{actor.id}> {script.sound}", "allowed_mentions": {"users": [actor.id]}})
        hachiware.say(parent, hachiware.relay(script.text), thread=tid, user_id=actor.id)

    return _said("usagi_thread", later=[greet], thread=f"<#{tid}>")


def _open_thread(actor, guild_id: str) -> str:
    """그 사람의 1:1 스레드를 열어 id 를 돌려줍니다 (없거나 지워졌으면 새로, 보관됐으면 다시 엶). 실패하면 HTTPError."""
    parent, token = config.USAGI_CHANNEL_ID, config.DISCORD_BOT_TOKEN
    record = storage.get_json(storage.threads_key(guild_id)) or {}
    mine = record.setdefault("usagi", {})
    thread = discord.get_channel(token, mine[actor.id]) if actor.id in mine else None
    if thread and (thread.get("thread_metadata") or {}).get("archived"):  # 오래 조용해서 보관됨
        discord.unarchive_thread(token, thread["id"])
    if not thread:  # 처음이거나 누가 스레드를 지웠으면 새로
        thread = discord.create_thread(token, parent, f"우사기 · {actor.name}")
        mine[actor.id] = thread["id"]
        storage.put_json(storage.threads_key(guild_id), record)
    discord.add_thread_member(token, thread["id"], actor.id)
    return thread["id"]


# ── /리마인드 (lunchbot/reminders.py, 나만 보기. 알림은 하치와레가 1:1 스레드에서) ──

def _remind_add(actor, guild_id, args, **_) -> Outcome:
    if not memory.usable():
        return _game_says("remind_locked", private=True)
    if not config.USAGI_CHANNEL_ID:
        return _game_says("no_usagi_channel", private=True)
    now = config.now_kst()
    try:
        at = reminders.when(now, int(args["시간"]), int(args["분"]), args.get("년"), args.get("월"), args.get("일"))
        if not str(args.get("내용", "")).strip():
            raise reminders.RemindError("empty")
        tid = _open_thread(actor, guild_id)
        reminders.add(guild_id, actor.id, actor.name, tid, args["내용"], at, now)
    except reminders.RemindError as e:
        return _game_says(f"remind_{e}", private=True, n=reminders.LIMIT)
    except urllib.error.HTTPError as e:
        log.warning("/리마인드 스레드 실패: HTTP %s", e.code)
        return _game_says("thread_failed", private=True)
    item_text = " ".join(str(args["내용"]).split())[:reminders.TEXT_CHARS]
    return Outcome("", f"{reminders._clock(at)}에 <#{tid}> 에서 불러서 알려 줄게! 알릴 거: \"{item_text}\"",
                   private=True, info="-# 지우려면 `/리마인드취소`, 목록은 `/리마인드목록`.", direct=True)


def _remind_list(actor, guild_id, **_) -> Outcome:
    if not memory.usable():
        return _game_says("remind_locked", private=True)
    items = reminders.mine(guild_id, actor.id)
    if not items:
        return _game_says("remind_none", private=True)
    out = _game_says("remind_list", private=True)
    lines = [f"{i}. {reminders._clock(datetime.fromisoformat(r['at']))} — {r['text']}" for i, r in enumerate(items, 1)]
    out.info = "\n".join(["**걸어 둔 리마인드** (나만 보여요, `/리마인드취소 [번호]`로 지워요)"] + lines)
    return out


def _remind_all_add(actor, guild_id, args, interaction, **_) -> Outcome:
    """모두에게: 이 채널(스레드)에서 하치와레가 걸었다고 알리고, 그 시각에 @everyone 으로 부름 (번역 설정과 상관없이)."""
    if not memory.usable():
        return _game_says("remind_locked", private=True)
    hook_channel, thread, _ = _place(interaction)
    now = config.now_kst()
    try:
        at = reminders.when(now, int(args["시간"]), int(args["분"]), args.get("년"), args.get("월"), args.get("일"))
        item = reminders.add_all(guild_id, actor.id, actor.name, hook_channel, thread, args.get("내용", ""), at, now)
    except reminders.RemindError as e:
        return _game_says(f"remind_{e}", private=True, n=reminders.LIMIT)
    clock = reminders._clock(at)
    return Outcome("", "다들! 전체 리마인드를 걸어 뒀어. 그 시각에 여기서 다 같이 불러서 알려 줄게!",
                   info=(f"**전체 리마인드** {clock} — \"{item['text']}\" ({actor.name} 님이 걸어 둠)\n"
                         "-# 목록은 `/전체리마인드목록`"), direct=True)  # 모두가 잘 보이게 보통 글로


def _remind_all_list(guild_id, **_) -> Outcome:
    if not memory.usable():
        return _game_says("remind_locked", private=True)
    items = reminders.everyone(guild_id)
    if not items:
        return _game_says("remind_none", private=True)
    out = _game_says("remind_list", private=True)
    lines = [f"{i}. {reminders._clock(datetime.fromisoformat(r['at']))} — {r['text']} ({r['name']} 님, <#{r['thread'] or r['channel']}>)"
             for i, r in enumerate(items, 1)]
    out.info = "\n".join(["**전체 리마인드** (나만 보여요, 건 사람이나 대장 갑옷씨가 `/전체리마인드취소 [번호]`로 지워요)"] + lines)
    return out


def _remind_all_cancel(actor, guild_id, args, **_) -> Outcome:
    if not memory.usable():
        return _game_says("remind_locked", private=True)
    number = int(args["번호"])
    result = reminders.cancel_all(guild_id, number, actor.id, captain=actor.level >= members.CAPTAIN)
    if result == "ok":
        return _game_says("remind_cancelled", private=True, n=number)
    return _game_says("remind_not_yours" if result == "not_yours" else "remind_bad_number", private=True)


def _remind_cancel(actor, guild_id, args, **_) -> Outcome:
    if not memory.usable():
        return _game_says("remind_locked", private=True)
    number = int(args["번호"])
    if reminders.cancel(guild_id, actor.id, number):
        return _game_says("remind_cancelled", private=True, n=number)
    return _game_says("remind_bad_number", private=True)


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

        return _said("recommend", later=[inbox.slow(send)], channel=f"<#{meal.channel_id}>", meal=what)

    return run


# ── 이미지 랜덤 주제 게임 (규칙은 lunchbot/game.py). 게임 안의 우사기 말은 번역 설정과 상관없이 하치와레가 번역 ──

def _button(label: str, custom_id: str, style: int = 2) -> dict:
    return {"type": BUTTON, "style": style, "label": label, "custom_id": custom_id}


def _load_game(channel_id: str):
    return storage.get_json(storage.game_key(channel_id))


def _save_game(channel_id: str, g: dict) -> None:
    storage.put_json(storage.game_key(channel_id), g)


def _game_says(key: str, private: bool = False, **kw) -> Outcome:
    script = hachiware.notice_script(key, **kw)
    return Outcome(script.sound, hachiware.relay(script.text), private=private, always=True)


def _game_refused(reason: str) -> Outcome:
    return _game_says(f"game_{reason}", private=True)  # 안 되는 까닭은 누른 사람에게만


def _pname(g: dict, user_id: str) -> str:
    """게임 참가자의 보일 이름."""
    return g["names"].get(user_id, user_id)


def _setup_info(g: dict) -> str:
    players = ", ".join(_pname(g, p) for p in g["players"]) or "아직 없어요"
    return (f"-# 주제: **{g['topic']}** · 시작한 사람: {g['starter_name']}\n"
            f"-# 참가자 ({len(g['players'])}명): {players}\n"
            f"-# 시작한 사람이 참가자를 고르거나 '서버 전체'를 누른 뒤 '시작'을 눌러요 ({game.MIN_PLAYERS}명 이상).")


def _setup_components() -> list:
    pick = {"type": USER_SELECT, "custom_id": "game:pick", "placeholder": "참가자 고르기", "min_values": 1, "max_values": 25}
    buttons = [_button("서버 전체", "game:all"), _button("시작", "game:start", 1), _button("취소", "game:cancel", 4)]
    return [{"type": ROW, "components": [pick]}, {"type": ROW, "components": buttons}]


def _round_info(g: dict) -> str:
    done, total = game.progress(g)
    return (f"-# **{g['round']}라운드** · 주제: **{g['topic']}**\n"
            f"-# 술래: <@{g['it']}> · 사회자: <@{g['host']}>\n"
            f"-# 술래를 뺀 사람은 `/게임 답 [내용]`으로 답을 보내요. 다른 사람에게는 안 보여요. 답 {done}/{total}")


def _scoreboard(g: dict) -> str:
    lines = ["-# 점수판"] + [f"-# {i}. {_pname(g, p)} {score}점" for i, (p, score) in enumerate(game.scoreboard(g), 1)]
    return "\n".join(lines)


def _winners(g: dict) -> str:
    board = game.scoreboard(g)
    top = board[0][1] if board else 0
    return ", ".join(_pname(g, p) for p, score in board if score == top) or "없음"


def _post(channel_id: str, script, info: str, mentions=(), components=None) -> str:
    """우사기 소리 + 안내를 채널에 올리고, 하치와레가 그 소리를 번역합니다 (게임이라 늘). 메시지 id 를 돌려줍니다."""
    hook = hachiware.hooks().get(str(channel_id))
    text = hachiware.relay(script.text)
    content = f"{script.sound}\n{info}" if hook else f"{script.sound}\n> **하치와레** {text}\n{info}"
    payload = {"content": content, "allowed_mentions": {"parse": [], "users": list(mentions)}}
    if components:
        payload["components"] = components
    sent = discord.send_message(config.DISCORD_BOT_TOKEN, channel_id, payload)
    if hook:
        discord.execute_webhook(hook, text)
    return (sent or {}).get("id")


def _post_round(channel_id: str, round_no: int) -> None:
    """그 라운드 메시지를 올립니다. 응답 뒤라 그 사이에 게임이 끝났거나 라운드가 넘어갔으면 올리지 않습니다."""
    g = _load_game(channel_id)
    if not g or g["status"] != "playing" or g["round"] != round_no:
        return
    script = hachiware.notice_script("game_round", round=g["round"], it=_pname(g, g["it"]), host=_pname(g, g["host"]))
    g["round_sound"], g["pinged"] = script.sound, False
    reveal = [{"type": ROW, "components": [_button("답 보기 (사회자만)", "game:reveal")]}]
    g["round_msg"] = _post(channel_id, script, _round_info(g), mentions=[g["it"], g["host"]], components=reveal)
    _save_game(channel_id, g)


def _post_final(channel_id: str, g: dict) -> None:
    """끝난 게임 g 의 점수판 (응답 뒤라 그 사이에 새 게임이 시작됐을 수 있어서 저장된 것을 다시 읽지 않음)."""
    script = hachiware.notice_script("game_end", winner=_winners(g))
    _post(channel_id, script, f"-# **게임 끝!** 주제: **{g['topic']}**\n{_scoreboard(g)}\n-# 1등: {_winners(g)}")


def _after_answer(channel_id: str) -> None:
    """라운드 메시지의 답 낸 수를 고치고, 다 모이면 사회자를 부릅니다."""
    g = _load_game(channel_id)
    if g.get("round_msg"):
        reveal = [{"type": ROW, "components": [_button("답 보기 (사회자만)", "game:reveal")]}]
        discord.edit_message(config.DISCORD_BOT_TOKEN, channel_id, g["round_msg"],
                             {"content": f"{g['round_sound']}\n{_round_info(g)}", "components": reveal})
    done, total = game.progress(g)
    if done == total and not g.get("pinged"):
        g["pinged"] = True
        _save_game(channel_id, g)
        script = hachiware.notice_script("game_all_in", host=_pname(g, g["host"]))
        _post(channel_id, script, f"-# <@{g['host']}> 사회자님, 답이 다 모였어요. 라운드 메시지의 '답 보기'를 눌러 주세요.",
              mentions=[g["host"]])


def _channel(interaction: dict) -> str:
    return str(interaction.get("channel_id") or (interaction.get("channel") or {}).get("id"))


def _game_start(actor, interaction, args, **_) -> Outcome:
    channel_id = _channel(interaction)
    g = _load_game(channel_id)
    if g and g["status"] != "done":
        return _game_refused("already")
    g = game.new(str(args["주제"]).strip()[:100], actor.id)
    g["starter_name"] = actor.name
    _save_game(channel_id, g)
    out = _game_says("game_setup", topic=g["topic"])
    out.info, out.components = _setup_info(g), _setup_components()
    return out


def _game_answer(actor, interaction, args, **_) -> Outcome:
    channel_id = _channel(interaction)
    g = _load_game(channel_id)
    if not g:
        return _game_refused("not_running")
    text = str(args["내용"]).strip()[:200]
    try:
        game.answer(g, actor.id, text)
    except game.GameError as e:
        return _game_refused(str(e))
    _save_game(channel_id, g)
    out = _game_says("game_answered", private=True)  # 낸 사람에게만
    out.info = f"-# 보낸 답: {text} (다시 보내면 바뀌어요)"
    out.later = [lambda: _after_answer(channel_id)]
    return out


def _game_result(actor, interaction, args, **_) -> Outcome:
    channel_id = _channel(interaction)
    g = _load_game(channel_id)
    if not g:
        return _game_refused("not_running")
    correct = int(args["맞힌수"])
    try:
        it = game.result(g, actor.id, correct, random)
    except game.GameError as e:
        return _game_refused(str(e))
    _save_game(channel_id, g)
    out = _game_says("game_score", it=_pname(g, it), n=correct)
    out.info = _scoreboard(g)
    out.later = [lambda: _post_round(channel_id, g["round"]) if g["status"] == "playing" else _post_final(channel_id, g)]
    return out


def _game_score(interaction, **_) -> Outcome:
    g = _load_game(_channel(interaction))
    if not g or g["status"] != "playing":
        return _game_refused("not_running")
    out = _game_says("game_scoreboard")
    out.info = _scoreboard(g)
    return out


def _game_end(actor, interaction, **_) -> Outcome:
    channel_id = _channel(interaction)
    g = _load_game(channel_id)
    if not g:
        return _game_refused("not_running")
    try:
        game.end(g, actor.id, captain=actor.level >= members.CAPTAIN)
    except game.GameError as e:
        return _game_refused(str(e))
    _save_game(channel_id, g)
    out = _game_says("game_end", winner=_winners(g))
    out.info = f"-# **게임 끝!** 주제: **{g['topic']}**\n{_scoreboard(g)}\n-# 1등: {_winners(g)}"
    return out


def handle_component(interaction: dict) -> tuple[dict, list]:
    """게임(game:…)과 생일(bday:…) 버튼·선택칸. (디스코드에 돌려줄 응답, 응답 뒤에 할 일)."""
    custom_id = interaction["data"]["custom_id"]
    if custom_id == "bday:open":
        return _birthday_modal(), []
    place = _place(interaction)
    member = interaction.get("member") or {}
    user = member.get("user") or {}
    uid = str(user.get("id"))
    channel_id = _channel(interaction)
    g = _load_game(channel_id)
    action = custom_id.split(":", 1)[1]
    if not g or g["status"] == "done":
        return _reply(_game_refused("not_running"), place)
    if action == "reveal":
        try:
            shown, missing = game.reveal(g, uid, random)
        except game.GameError as e:
            return _reply(_game_refused(str(e)), place)
        out = _game_says("game_reveal", private=True)  # 사회자에게만
        lines = [f"**{g['round']}라운드 답** (사회자만 보여요)"]
        lines += [f"{i}. {text} — {_pname(g, who)}" for i, (text, who) in enumerate(shown, 1)] or ["아직 답이 없어요"]
        if missing:
            lines.append(f"-# 아직 안 낸 사람: {', '.join(_pname(g, p) for p in missing)}")
        out.info = "\n".join(lines)
        return _reply(out, place)
    if g["status"] != "setup":
        return _reply(_game_refused("not_running"), place)
    if uid != g["starter"]:
        return _reply(_game_refused("not_starter"), place)
    later = []
    if action == "pick":
        resolved = interaction["data"].get("resolved") or {}
        users, nicks = resolved.get("users") or {}, resolved.get("members") or {}
        ids = [v for v in interaction["data"].get("values", []) if not (users.get(v) or {}).get("bot")]
        game.set_players(g, ids, {v: _name(nicks.get(v, {}), users.get(v, {})) for v in ids})
    elif action == "all":
        people = discord.list_members(config.DISCORD_BOT_TOKEN, interaction["guild_id"])
        game.set_players(g, [m["user"]["id"] for m in people], {m["user"]["id"]: _name(m, m["user"]) for m in people})
    elif action == "start":
        try:
            game.start(g, uid, random)
        except game.GameError as e:
            return _reply(_game_refused(str(e)), place)
        later = [lambda: _post_round(channel_id, g["round"])]
    elif action == "cancel":
        g["status"] = "done"
    _save_game(channel_id, g)
    if action == "start":
        content = f"{messages.picked_sound()}\n-# 게임 시작! 주제: **{g['topic']}** · 참가자 {len(g['players'])}명"
        return {"type": UPDATE_MESSAGE, "data": {"content": content, "components": []}}, later
    if action == "cancel":
        return {"type": UPDATE_MESSAGE, "data": {"content": f"{messages.skipped_sound()}\n-# 게임을 취소했어요.",
                                                 "components": []}}, []
    content = f"{messages.picked_sound()}\n{_setup_info(g)}"
    return {"type": UPDATE_MESSAGE, "data": {"content": content, "components": _setup_components()}}, []


# ── 생일 (선택) ──

BIRTHDAY_NOTE = "알려 주면 생일 아침 9시에 우사기 채널에서 축하해요"


def _birthday_modal() -> dict:
    def field_(custom_id, label, placeholder):
        return {"type": ROW, "components": [{"type": TEXT_INPUT, "custom_id": custom_id, "label": label, "style": 1,
                                             "min_length": 1, "max_length": 3, "required": True,
                                             "placeholder": placeholder}]}

    return {"type": MODAL, "data": {"custom_id": "bday:save", "title": "생일 알려 주기 (선택)", "components": [
        field_("month", "생일 월 (1~12)", BIRTHDAY_NOTE), field_("day", "생일 일 (1~31)", "예: 5")]}}


def _birthday_saved(guild_id: str, user, month: int, day: int) -> Outcome:
    try:
        birthdays.save(guild_id, user.id, month, day, by=user.name)
    except ValueError:
        return _game_says("bday_bad", private=True)
    out = _game_says("bday_saved", private=True, date=f"{month}월 {day}일")  # 넣은 사람에게만
    out.info = "-# 생일 아침 9시에 우사기 채널에서 축하 알림을 보내요. 지우려면 `/생일 지우기`."
    return out


def handle_modal(interaction: dict) -> tuple[dict, list]:
    """생일 입력창(bday:save)."""
    values = {c["custom_id"]: c.get("value", "") for row in interaction["data"].get("components", [])
              for c in row.get("components", [])}
    member = interaction.get("member") or {}
    user = member.get("user") or {}
    person = members.Person(str(user.get("id")), _name(member, user))
    try:
        month, day = birthdays.parse(values.get("month"), values.get("day"))
    except ValueError:
        return _reply(_game_says("bday_bad", private=True), _place(interaction))
    return _reply(_birthday_saved(interaction["guild_id"], person, month, day), _place(interaction))


def _birthday_set(actor, guild_id, args, **_) -> Outcome:
    return _birthday_saved(guild_id, actor, int(args["월"]), int(args["일"]))


# ── 1:1 대화 기억 (lunchbot/memory.py, 나만 보기) ──

_TOPIC_NAMES = {"lunch": "오늘 점심", "dinner": "오늘 저녁", "last": "지난번 고른 곳", "birthday": "내 생일",
                "game": "게임 점수", "rank": "내 등급", "time": "지금 시각", "off": "퇴근까지", "usagi": "우사기",
                "hachiware": "하치와레", "me": "나", "talk": "마지막 대화", "bored": "심심할 때",
                "tired": "힘들 때", "food": "뭐 먹을지", "place": "그 식당"}
_KIND_NAMES = {"sad": "슬픔", "worry": "걱정", "done": "해냄", "angry": "화남", "laugh": "웃음", "praise": "칭찬", "surprise": "놀람", "greet": "인사",
               "bye": "작별", "food": "음식", "agree": "맞장구", "call": "부르기"}


def _memory_locked() -> Outcome:
    out = _game_says("memory_locked", private=True)
    out.info = "-# 지금은 기억을 열 수 없어요 (기억 열쇠 문제). 서버 관리자에게 알려 주세요."
    return out


PAGE = 1900  # 디스코드 메시지 2000자 제한 안에서 한 쪽
SHOWN = 20  # /기억 보기 에서 한 항목을 보여 주는 글자 수


def _short(text: str, n: int = SHOWN) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _pages(lines: list) -> list:
    """줄들을 PAGE 글자 안의 쪽으로 나눕니다."""
    pages, page = [], ""
    for line in lines:
        if page and len(page) + 1 + len(line) > PAGE:
            pages.append(page)
            page = ""
        page = f"{page}\n{line}" if page else line
    return pages + [page] if page else pages


def _memory_show(actor, guild_id, interaction, **_) -> Outcome:
    """기억하는 것을 모두 보여 줍니다 (나만 보기). 길면 나만 보는 후속 메시지로 이어서."""
    if not memory.usable():
        return _memory_locked()
    mem = memory.load(guild_id, actor.id)
    if not mem["last_seen"] and not mem["taught"] and not mem["known"]:
        return _game_says("memory_none", private=True)
    lines = ["**우사기가 기억하는 것** (나만 보여요)"]
    if mem["last_seen"]:
        lines.append(f"- 마지막으로 이야기한 날: {mem['last_seen']}")
    if mem["moods"]:
        lines.append("- 최근 기분: " + ", ".join(f"{d} {_KIND_NAMES.get(k, k)}" for d, k in mem["moods"]))
    if mem["topics"]:
        top = sorted(mem["topics"].items(), key=lambda kv: -kv[1])
        lines.append("- 자주 하는 이야기: " + ", ".join(f"{_KIND_NAMES.get(k, k)} {n}번" for k, n in top))
    for field, label in (("likes", "좋아한다고 한 것"), ("dislikes", "싫어한다고 한 것")):
        if mem[field]:
            lines.append(f"- {label}: " + ", ".join(_short(x) for x in mem[field]))
    if mem["foods"]:
        lines.append("- 최근 이야기한 음식: " + ", ".join(f"{d} {f}" for d, f in mem["foods"]))
    if mem["known"]:
        lines.append("- 알게 된 낱말 (물어봤지만 그냥 쓰는 말): " + ", ".join(_short(w) for w in mem["known"]))
    if mem["taught"]:
        lines.append("**가르쳐 준 것** (`/기억 지우기 [번호]`로 하나씩 지워요)")
        for i, t in enumerate(mem["taught"], 1):
            if t["kind"] == "answer":
                meant = f"'{_short(t['answer'], 40)}'라고 답하기"
            elif t["kind"] == "word":
                meant = f"'{_short(t['means'], 40)}' 뜻"
            else:
                meant = f"{_TOPIC_NAMES.get(t['topic'], t['topic'])} 물음"
            lines.append(f"{i}. {_short(' '.join(t['words']))} → {meant}")
    first, *rest = _pages(lines)
    out = _game_says("memory_shown", private=True)
    out.info = first
    app, token = interaction["application_id"], interaction["token"]
    out.later = [lambda page=page: discord.followup(app, token, page) for page in rest]  # 나만 보기 (ephemeral)
    return out


def _memory_forget(actor, guild_id, args, **_) -> Outcome:
    if not memory.usable():
        return _memory_locked()
    number = args.get("번호")
    if number is None:
        return _game_says("memory_forgot" if memory.forget(guild_id, actor.id) else "memory_none", private=True)
    if memory.forget_taught(guild_id, actor.id, int(number)):
        return _game_says("memory_forgot_one", private=True, n=number)
    return _game_says("memory_bad_number", private=True)


def _birthday_remove(actor, guild_id, **_) -> Outcome:
    return _game_says("bday_removed" if birthdays.remove(guild_id, actor.id) else "bday_none", private=True)


RUN = {
    "도움": _help,
    "우사기": _usagi,
    "리마인드": _remind_add,
    "리마인드목록": _remind_list,
    "리마인드취소": _remind_cancel,
    "전체리마인드": _remind_all_add,
    "전체리마인드목록": _remind_all_list,
    "전체리마인드취소": _remind_all_cancel,
    "기억 보기": _memory_show,
    "기억 지우기": _memory_forget,
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
    "생일 등록": _birthday_set,
    "생일 지우기": _birthday_remove,
    "게임 시작": _game_start,
    "게임 답": _game_answer,
    "게임 결과": _game_result,
    "게임 점수": _game_score,
    "게임 끝": _game_end,
}
