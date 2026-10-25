"""우사기 명령 (슬래시 명령): 멤버 등급, 추방, 점심·저녁 추천, 하치와레 번역 켜기·끄기, 도움.

명령을 쓰면 우사기가 그 채널에 소리로 답하고(모두가 봄), 하치와레 번역이 켜져 있으면 이어서 그 채널의 하치와레
웹훅이 결과나 까닭을 글로 알린다. 번역이 꺼져 있으면 하치와레는 아무 말도 하지 않고 우사기 소리만 나간다.
명령을 쓴 사람에게만 보이는 답은 /도움 뿐이고, /도움 은 번역이 꺼져 있어도 사용법을 보여 준다.
하치와레 웹훅이 없는 채널에서는 우사기 답 아래에 하치와레 말을 붙인다.
"""
import json
import re
import urllib.error

import pytest

from lunchbot import config, hachiware, members, messages, storage
import commands
import interaction
import recommend
from test_flow import aws, signed_event  # noqa: F401 (aws 는 fixture)

GUILD, HERE, BARE = "g1", "c-usagi", "c-plain"
HOOK = "https://discord.com/api/webhooks/9/hachiware-token"
HACHIWARE = "\n>>> **하치와레** "
NAMES = {"own": "주인", "cap": "대장", "work": "직장인", "walk": "행인", "x": "손님", "y": "손님2", "bot": "다른 봇"}
PUZZLED = set(messages.PUZZLED)
REFUSED = set(messages.PUZZLED + messages.SULKY)  # 거절할 때 우사기 소리 (갸웃·시무룩)


def slash(command, actor="own", target=None, rank=None, channel=HERE, thread=False):
    words = command.split()
    opts = []
    if target:
        opts.append({"type": 6, "name": "사람", "value": target})
    if rank:
        opts.append({"type": 4, "name": "등급", "value": rank})
    for i, w in reversed(list(enumerate(words[1:], 1))):
        opts = [{"type": 1 if i == len(words) - 1 else 2, "name": w, "options": opts}]
    resolved = {}
    if target:
        resolved = {"users": {target: {"id": target, "username": target, "global_name": NAMES[target],
                                       "bot": target == "bot"}},
                    "members": {target: {"nick": None}}}
    event = {
        "type": 2, "id": "i1", "token": "itoken", "application_id": "app", "guild_id": GUILD, "channel_id": channel,
        "member": {"user": {"id": actor, "username": actor, "global_name": NAMES[actor]}},
        "data": {"name": words[0], "type": 1, "options": opts, "resolved": resolved},
    }
    if thread:  # 우사기 채널 아래 비공개 스레드 (/우사기 1:1 스레드) 안에서 쓴 명령
        event["channel_id"] = channel = "t9"
        event["channel"] = {"id": channel, "type": 12, "parent_id": HERE}
    return event


@pytest.fixture
def bot(aws, monkeypatch):
    """서버 주인은 own. 우사기 채널(c-usagi)에는 하치와레 웹훅이 있고, c-plain 에는 없다."""
    hooked, kicked, sent, followed, posted = [], [], [], [], []
    monkeypatch.setattr(hachiware, "hooks", lambda: {HERE: HOOK})
    monkeypatch.setattr(commands.discord, "guild_owner", lambda token, guild_id: "own")
    monkeypatch.setattr(commands.discord, "execute_webhook", lambda url, text: hooked.append((url, text)) or {"id": "h"})
    monkeypatch.setattr(commands.discord, "followup", lambda app_id, token, text, ephemeral=True:
                        followed.append((app_id, token, text, ephemeral)) or {"id": "f"})

    def kick(token, guild_id, user_id, reason):
        if kick.fail:
            raise urllib.error.HTTPError("u", kick.fail, "no", {}, None)
        kicked.append((guild_id, user_id, reason))

    kick.fail = None
    monkeypatch.setattr(commands.discord, "kick_member", kick)

    def send(token, channel_id, payload):
        sent.append(channel_id)
        posted.append((channel_id, payload))
        return {"id": f"m{len(sent)}"}

    monkeypatch.setattr(recommend.discord, "send_message", send)

    threads = {"made": [], "added": [], "unarchived": [], "info": {}, "fail": None}

    def create_thread(token, channel_id, name):
        if threads["fail"]:
            raise urllib.error.HTTPError("u", threads["fail"], "no", {}, None)
        tid = f"t{len(threads['made']) + 1}"
        threads["made"].append((channel_id, name))
        threads["info"][tid] = {"id": tid, "parent_id": channel_id, "thread_metadata": {"archived": False}}
        return {"id": tid}

    monkeypatch.setattr(commands.discord, "create_thread", create_thread)
    monkeypatch.setattr(commands.discord, "add_thread_member", lambda token, tid, uid: threads["added"].append((tid, uid)))
    monkeypatch.setattr(commands.discord, "get_channel", lambda token, cid: threads["info"].get(cid))
    monkeypatch.setattr(commands.discord, "unarchive_thread", lambda token, tid: threads["unarchived"].append(tid))
    monkeypatch.setattr(config, "USAGI_CHANNEL_ID", HERE)

    hachiware.turn(True, "테스트")  # 대부분의 테스트는 번역이 켜진 채로

    def run(*a, **kw):
        n = len(hooked)
        body = json.loads(interaction.handler(signed_event(slash(*a, **kw)), None)["body"])
        data = body["data"]
        assert body["type"] == 4 and data["allowed_mentions"] == {"parse": []}
        assert (data.get("flags") == 64) == (a[0] == "도움")  # 나만 보기는 /도움 뿐
        if HACHIWARE in data["content"]:  # /도움, 또는 웹훅이 없는 채널: 답 안에 하치와레 말
            assert len(hooked) == n
            return body, data["content"].split(HACHIWARE, 1)[1]
        # 답은 우사기 소리만 (모두가 봄), 하치와레 말은 그 채널 웹훅으로
        assert "\n" not in data["content"] and hooked[n][0] == HOOK
        return body, hooked[n][1]

    run.kicked, run.kick, run.sent, run.followed, run.posted, run.hooked = kicked, kick, sent, followed, posted, hooked
    run.threads = threads
    run.roster = lambda: members.load(GUILD)
    return run


def sound_of(body):
    return body["data"]["content"].split("\n")[0]


def made_of(line, pool):
    return all(w.strip("!?…~") in pool or re.fullmatch("푸르{3,}", w.strip("!?…~")) for w in line.split())


def test_commands_are_valid_for_discord():
    def names(items):
        for item in items:
            yield item
            yield from names(item.get("options") or [])

    every = list(names(commands.DEFINITIONS))
    assert all(re.fullmatch(r"[\w-]{1,32}", c["name"]) for c in every)  # 띄어쓰기 없는 한글 이름
    assert all(1 <= len(c["description"]) <= 100 for c in every)
    paths = set()
    for top in commands.DEFINITIONS:
        assert top["contexts"] == [0]  # 서버에서만
        subs = [o for o in top.get("options") or [] if o["type"] in (1, 2)]
        if not subs:
            paths.add(top["name"])
        for s in subs:
            for leaf in [o for o in s.get("options") or [] if o["type"] == 1] or [s]:
                paths.add(" ".join(dict.fromkeys([top["name"], s["name"], leaf["name"]])))
    assert paths == set(members.NEEDS) == set(commands.USAGE)


def test_first_captain_is_the_server_owner(bot):
    body, said = bot("멤버 추가", "own", "walk")
    assert made_of(sound_of(body), messages.EXCITED)  # 첫 줄은 우사기 소리
    assert "<@walk>" in said and "행인 갑옷씨" in said
    assert bot.roster()["walk"]["rank"] == members.WALKER and bot.roster()["walk"]["by"] == "주인"


def test_member_ladder(bot):
    bot("멤버 추가", "own", "work")
    bot("멤버 승급", "own", "work", rank=members.WORKER)
    assert bot.roster()["work"]["rank"] == members.WORKER
    bot("멤버 추가", "work", "walk")  # 직장인도 추가할 수 있음
    _, said = bot("멤버 승급", "work", "walk", rank=members.CAPTAIN)
    assert "직장인 갑옷씨**까지만" in said and bot.roster()["walk"]["rank"] == members.WALKER  # 자기 등급까지만
    _, said = bot("멤버 승급", "work", "walk", rank=members.WORKER)
    assert "직장인 갑옷씨" in said and bot.roster()["walk"]["rank"] == members.WORKER
    bot("멤버 강등", "own", "walk", rank=members.WALKER)
    assert bot.roster()["walk"]["rank"] == members.WALKER
    _, said = bot("멤버 삭제", "work", "walk")
    assert "<@walk>" in said and "walk" not in bot.roster()


def test_refused_commands_explain_why(bot):
    body, said = bot("멤버 추가", "x", "y")  # 멤버가 아닌 사람
    assert made_of(sound_of(body), REFUSED)
    assert len(sound_of(body).split()) == 3  # 번역이 세 토막이면 소리도 세 토막
    assert "행인 갑옷씨**부터" in said and bot.roster() == {}
    bot("멤버 추가", "own", "walk")
    _, said = bot("추방", "walk", "x")
    assert "직장인 갑옷씨**부터" in said and bot.kicked == []
    _, said = bot("멤버 추가", "walk", "bot")
    assert "봇" in said and "bot" not in bot.roster()
    _, said = bot("멤버 삭제", "walk", "own")
    assert "직장인 갑옷씨**부터" in said


def test_kick(bot):
    bot("멤버 추가", "own", "work")
    bot("멤버 승급", "own", "work", rank=members.WORKER)
    bot("멤버 추가", "own", "walk")
    body, said = bot("추방", "work", "walk")
    assert sound_of(body) == "우라!"
    assert bot.kicked == [(GUILD, "walk", "우사기 명령 /추방 (직장인)")]
    assert "<@walk> 나가!" in said and "walk" not in bot.roster()
    assert body["data"]["content"] == "우라!" and bot.posted == []  # 우사기의 '우라!' 가 곧 모두가 보는 답

    body, said = bot("추방", "work", "own")  # 주인은 못 내보냄
    assert made_of(sound_of(body), REFUSED) and len(bot.kicked) == 1 and "서버 주인" in said

    bot.kick.fail = 403  # 봇 권한이 없거나 역할이 더 높음
    body, said = bot("추방", "work", "x")
    assert made_of(sound_of(body), REFUSED) and "멤버 추방하기" in said
    bot.kick.fail = 404
    _, said = bot("추방", "work", "y")
    assert "벌써 없어" in said


def raw(*a, **kw):
    return json.loads(interaction.handler(signed_event(slash(*a, **kw)), None)["body"])


def test_personal_switch_is_for_your_1on1_thread_only(bot):
    hachiware.turn(False, "테스트")  # 서버 전체 (모두가 보는 채널)는 꺼짐
    n = len(bot.hooked)
    body = raw("하치와레 번역 켜기", "x")  # 누구나, 나에게만 적용
    assert hachiware.is_on("x") is True and hachiware.is_on("y") is False and hachiware.is_on() is False
    # 모두가 보는 우사기 채널에서는 개인 설정을 켜도 서버 전체(꺼짐)를 따름 → 우사기 소리만
    assert "\n" not in body["data"]["content"] and len(bot.hooked) == n
    assert "\n" not in raw("멤버 추가", "x", "y")["data"]["content"] and len(bot.hooked) == n
    # 내 1:1 스레드 안에서는 개인 설정을 따름 → 하치와레가 그 스레드에 (우사기 채널 웹훅 + thread_id)
    raw("하치와레 번역 켜기", "x", thread=True)
    assert bot.hooked[-1][0] == HOOK + "?thread_id=t9" and "이미" in bot.hooked[-1][1]
    n = len(bot.hooked)
    raw("하치와레 번역 끄기", "x", thread=True)  # 끄면 그때부터 내 스레드에서도 조용
    assert hachiware.is_on("x") is False and len(bot.hooked) == n
    hachiware.turn(True, "테스트")  # 서버 전체를 켜면 모두가 보는 채널은 개인 설정과 상관없이 번역
    _, said = bot("멤버 추가", "x", "walk")
    assert "행인 갑옷씨**부터" in said
    assert hachiware.is_on("x") is False and hachiware.is_on("y") is True  # 1:1 스레드: 정한 사람은 내 설정, 안 정한 사람은 서버 전체
    assert storage.get_json(storage.HACHIWARE_PEOPLE_KEY)["x"]["translate"] is False


def test_server_wide_switch_needs_a_worker(bot):
    hachiware.turn(False, "테스트")
    body = raw("하치와레 전체 켜기", "x")  # 멤버가 아님 → 거절 (전체가 꺼져 있어 우사기 소리만)
    assert made_of(sound_of(body), REFUSED) and hachiware.is_on() is False
    raw("멤버 추가", "own", "work")
    raw("멤버 승급", "own", "work", rank=members.WORKER)
    _, said = bot("하치와레 전체 켜기", "work")  # 켜자마자 하치와레가 채널에서 말함
    assert hachiware.is_on() is True and "메뉴" in said
    assert storage.get_json(storage.HACHIWARE_KEY)["by"] == "직장인"
    body = raw("하치와레 전체 끄기", "work")  # 끄면 그때부터 채널에서 조용
    assert hachiware.is_on() is False and "\n" not in body["data"]["content"]


def test_switch_off_means_usagi_only(bot):
    hachiware.turn(False, "테스트")
    n = len(bot.hooked)
    for args in [("멤버 추가", "own", "walk"), ("멤버 추가", "x", "y"), ("점심 추천", "x"), ("추방", "own", "x")]:
        body = raw(*args)
        assert "flags" not in body["data"] and "\n" not in body["data"]["content"]  # 우사기 소리만
    body = raw("멤버 추가", "own", "y", channel=BARE)  # 웹훅이 없는 채널에서도 하치와레 말을 붙이지 않음
    assert "하치와레" not in body["data"]["content"]
    assert len(bot.hooked) == n and bot.sent == ["42"]  # 추천 메시지는 그대로 나감
    body = raw("도움", "x")  # /도움 은 꺼져 있어도 사용법을 보여 줌 (나만 보기)
    assert body["data"]["flags"] == 64 and "`/도움`" in body["data"]["content"]


def test_help_lists_what_your_rank_can_use(bot):
    _, said = bot("도움", "x")
    assert "아직 멤버가 아니야" in said
    assert "`/점심 추천`" in said and "`/하치와레 번역 켜기`" in said and "`/멤버 추가 [사람]`" not in said
    assert "멤버한테 `/멤버 추가`를 부탁해" in said  # 멤버가 되는 법
    bot("멤버 추가", "own", "walk")
    _, said = bot("도움", "walk")
    assert "**행인 갑옷씨**" in said and "`/멤버 추가 [사람]`" in said and "/추방" not in said
    _, said = bot("도움", "own")
    assert "**대장 갑옷씨**" in said and "`/추방 [사람]`" in said and "`/멤버 승급 [사람] [등급]`" in said
    assert "1:1 스레드 번역은 켜져 있고" in said and "채널 번역(메뉴 추천 포함)은 켜져 있어" in said


def test_lunch_and_dinner_recommendation(bot, monkeypatch):
    body, said = bot("점심 추천", "x")
    assert bot.sent == ["42"]  # 추천 메시지는 오점뭐로 (모두가 봄)
    assert "<#42>" in said and "점심" in said
    monkeypatch.setattr(config, "DINNER_CHANNEL_ID", "")
    _, said = bot("저녁 추천", "x")
    assert "DINNER_CHANNEL_ID" in said and bot.sent == ["42"]  # 채널이 없으면 안내만
    monkeypatch.setattr(config, "DINNER_CHANNEL_ID", "77")
    _, said = bot("저녁 추천", "x")
    assert bot.sent == ["42", "77"] and "<#77>" in said


def test_hachiware_speaks_after_usagi(bot):
    # 하치와레 말과 추천은 우사기 답을 돌려준 뒤에 한다 (식당 수집은 3초를 넘길 수 있음)
    response, later = interaction.respond(signed_event(slash("점심 추천", "x")))
    assert "flags" not in json.loads(response["body"])["data"] and bot.sent == [] and bot.hooked == []
    for job in later:
        job()
    assert bot.sent == ["42"] and len(bot.hooked) == 1 and "<#42>" in bot.hooked[0][1]


def test_deployed_recommendation_calls_the_recommend_function(bot, monkeypatch):
    calls = []
    monkeypatch.setattr(config, "RECOMMEND_FUNCTION_NAME", "lunchbot-recommend")
    monkeypatch.setattr(commands, "_invoke", lambda name, payload: calls.append((name, payload)))
    bot("점심 추천", "x")
    assert calls[-1] == ("lunchbot-recommend", {"meal": "lunch"}) and bot.sent == []


def test_recommendation_failure_is_reported(bot, monkeypatch):
    def boom(event, context):
        raise RuntimeError("카카오 응답 없음")

    monkeypatch.setattr(commands.recommend, "handler", boom)
    bot("점심 추천", "x")
    # 우사기 소리는 명령의 후속 메시지로(모두가 봄), 이어서 하치와레가 그 채널에 번역
    assert "못 보냈어" in bot.hooked[-1][1] and len(bot.followed) == 1
    app, token, sound, private = bot.followed[0]
    assert (app, token, private) == ("app", "itoken", False) and made_of(sound, REFUSED) and len(sound.split()) == 3
    bot("점심 추천", "x", channel=BARE)  # 웹훅이 없는 채널: 후속 메시지 하나에 소리와 하치와레 말을 함께
    assert "못 보냈어" in bot.followed[-1][2] and "**하치와레**" in bot.followed[-1][2] and bot.followed[-1][3] is False


def test_only_help_is_private(bot):
    body, said = bot("도움", "x")  # 웹훅이 있는 채널에서도 /도움 은 나만 보기 (답 안에 하치와레 말)
    assert "`/도움`" in said
    body, said = bot("멤버 추가", "own", "y", channel=BARE)  # 웹훅이 없으면 답 아래에 하치와레 말, 모두가 봄
    assert made_of(sound_of(body), messages.EXCITED) and "<@y>" in said
    body, said = bot("멤버 추가", "x", "walk", channel=BARE)  # 거절도 모두가 봄
    assert "행인 갑옷씨**부터" in said


def test_unknown_command(bot):
    event = slash("도움", "x", channel=BARE)
    event["data"]["name"] = "모르는명령"
    body = json.loads(interaction.handler(signed_event(event), None)["body"])
    assert made_of(sound_of(body), PUZZLED) and "그게 뭐야?" in body["data"]["content"]



def test_usagi_opens_a_private_thread(bot):
    body, said = bot("우사기", "x")
    assert bot.threads["made"] == [(HERE, "우사기 · 손님")]  # 우사기 채널 아래 비공개 스레드
    assert bot.threads["added"] == [("t1", "x")]  # 그 사람만 넣음
    assert "<#t1>" in said  # 하치와레가 스레드로 안내
    # 응답 뒤: 스레드에 우사기가 인사하며 그 사람을 부름 (알림이 가서 스레드를 찾게)
    greet = [p for c, p in bot.posted if c == "t1"]
    assert len(greet) == 1 and greet[0]["content"].startswith("<@x> ")
    assert greet[0]["allowed_mentions"] == {"users": ["x"]}
    # 번역이 켜져 있으면 하치와레가 그 스레드에 번역 (우사기 채널 웹훅 + thread_id)
    assert bot.hooked[-1][0] == HOOK + "?thread_id=t1"


def test_usagi_reuses_your_thread(bot):
    bot("우사기", "x")
    bot.threads["info"]["t1"]["thread_metadata"]["archived"] = True  # 오래 조용해서 보관됨
    _, said = bot("우사기", "x")
    assert len(bot.threads["made"]) == 1 and bot.threads["unarchived"] == ["t1"] and "<#t1>" in said
    bot("우사기", "y")  # 다른 사람은 따로
    assert bot.threads["made"][-1] == (HERE, "우사기 · 손님2")
    del bot.threads["info"]["t1"]  # 누가 스레드를 지웠으면 새로 만듦
    _, said = bot("우사기", "x")
    assert len(bot.threads["made"]) == 3 and "<#t3>" in said


def test_usagi_thread_without_translation(bot):
    hachiware.turn(False, "테스트")
    body = raw("우사기", "x")
    assert "\n" not in body["data"]["content"]  # 우사기 소리만
    greet = [p for c, p in bot.posted if c == "t1"]
    assert greet and greet[0]["content"].startswith("<@x> ")  # 스레드 인사는 그대로 (알림)
    assert not [u for u, _ in bot.hooked if "thread_id" in u]  # 하치와레는 조용


def test_usagi_thread_problems(bot, monkeypatch):
    bot.threads["fail"] = 403  # 봇에 스레드 권한이 없음
    _, said = bot("우사기", "x")
    assert "스레드" in said and bot.threads["made"] == []
    monkeypatch.setattr(config, "USAGI_CHANNEL_ID", "")
    _, said = bot("우사기", "x")
    assert "USAGI_CHANNEL_ID" in said
