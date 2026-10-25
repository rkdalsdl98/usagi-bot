"""디스코드 버튼 클릭과 우사기 명령(Interaction)을 받는 Lambda (Function URL). 버튼은 투표입니다.

- 식당·패스 버튼: 누른 사람의 한 표를 저장합니다 (다시 누르면 바뀜). 메시지에 식당마다 투표한 사람이 보입니다.
- 정원만큼 투표하거나 '투표 종료'를 누르면 마감합니다. 가장 많이 받은 식당을
  latest/selection.json 과 selections/{카테고리}/{날짜}.json 에 저장합니다 (총 2번 저장).
  동점이면 동점인 식당 중 무작위, 패스와 식당이 동점이면 식당. 패스가 가장 많거나 아무도 안 했으면 선택 없음.
- 표는 메시지마다 따로 셉니다 (votes/{메시지 id}/…). 마감 결과는 처음 한 번만 써집니다.
- 점심·저녁은 meta.json 의 meal 로 구분합니다. 저녁 결과는 dinner/latest, dinner/selections 에 따로 저장합니다.
- 마감되면 그 채널의 하치와레가 결과 메시지의 우사기 소리를 번역합니다 (번역이 켜져 있을 때만, 응답 뒤에).
우사기 명령(슬래시 명령)은 commands.py 가 처리합니다.
디스코드는 3초 안에 응답해야 합니다. 응답 뒤에 할 일(하치와레 말, 명령으로 보내는 추천)은 respond 가 따로 돌려주고,
로컬 서버(serve_local.py)는 응답부터 보낸 뒤 그 일을 합니다. Lambda 는 응답을 돌려주면 멈추므로 handler 가 먼저 합니다.
"""
import base64
import json
import logging
import random
from collections import Counter

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from lunchbot import config, discord, hachiware, meals, messages, storage
import commands

log = logging.getLogger()
log.setLevel(logging.INFO)

PING, COMMAND, COMPONENT, MODAL_SUBMIT = 1, 2, 3, 5
PONG, CHANNEL_MESSAGE, UPDATE_MESSAGE = 1, 4, 7
EPHEMERAL = 64

_verify_key = None


def _response(status: int, body: dict | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body or {}, ensure_ascii=False),
    }


def verify_signature(headers: dict, body: str) -> bool:
    global _verify_key
    sig = headers.get("x-signature-ed25519")
    ts = headers.get("x-signature-timestamp")
    if not sig or not ts:
        return False
    if _verify_key is None:
        _verify_key = VerifyKey(bytes.fromhex(config.DISCORD_PUBLIC_KEY))
    try:
        _verify_key.verify(f"{ts}{body}".encode(), bytes.fromhex(sig))
        return True
    except (BadSignatureError, ValueError):
        return False


def _voter(interaction: dict):
    """(사용자 id, 보일 이름). 이름은 서버 별명 → 디스코드 표시 이름 → 아이디 순서."""
    member = interaction.get("member") or {}
    user = member.get("user") or interaction.get("user") or {}
    name = member.get("nick") or user.get("global_name") or user.get("username") or "누군가"
    return user.get("id") or name, name


def _updated_message(data: dict) -> dict:
    return {"type": UPDATE_MESSAGE, "data": data}


def _ephemeral(text: str) -> dict:
    return {"type": CHANNEL_MESSAGE, "data": {"content": text, "flags": EPHEMERAL}}


def _winner(counts: Counter):
    """가장 많이 받은 식당 id. 동점이면 무작위, 패스와 동점이면 식당. 패스만 가장 많거나 표가 없으면 None."""
    if not counts:
        return None
    top = max(counts.values())
    tied = sorted(c for c, n in counts.items() if n == top and c != discord.SKIP)
    return random.choice(tied) if tied else None


def _labels(counts: dict, meta: dict) -> dict:
    """{보일 이름: 표 수}. 표의 식당 id 를 식당 이름으로, 패스는 '패스'로."""
    names = {p["id"]: p["name"] for p in meta["picks"]}
    return {(messages.SKIP_LABEL if c == discord.SKIP else names[c]): n for c, n in counts.items()}


def _result_message(result: dict, meta: dict) -> dict:
    # 많은 순, 같으면 식당이 패스보다 먼저
    tally = sorted(_labels(result["counts"], meta).items(), key=lambda t: (-t[1], t[0] == messages.SKIP_LABEL))
    info = messages.vote_summary(tally, result["voted"], result["expected"])
    winner = next((p for p in meta["picks"] if p["id"] == result["winner"]), None)
    voters = result["voters"].get(result["winner"], [])
    return discord.build_result(result["sound"], info, winner, voters, meal=meta.get("meal", meals.LUNCH))


def _close(message_id: str, meta: dict, closed_by: str, ballots=None, announce=None) -> dict:
    """투표를 마감하고 결과 메시지를 돌려줍니다. 이미 누가 마감했으면 그 결과를 그대로 씁니다.

    이번에 마감했으면 announce(결과 메시지의 우사기 소리와 번역, 정해진 식당 이름 또는 None)를 부릅니다.
    """
    if ballots is None:
        ballots = storage.list_json(storage.ballots_prefix(message_id))
    counts = Counter(b["choice"] for b in ballots)
    voters = discord.voters_by_choice(ballots)
    winner_id = _winner(counts)
    winner = next((p for p in meta["picks"] if p["id"] == winner_id), None)
    script = hachiware.result_script(winner["name"] if winner else None)  # 우사기 소리와 번역을 한 토막씩 짝지음
    result = {
        "winner": winner_id,
        "counts": dict(counts),
        "voters": voters,
        "voted": len(ballots),
        "expected": meta["expected"],
        "sound": script.sound,
        "closed_by": closed_by,
        "closed_at": config.now_kst().isoformat(),
    }
    if not storage.put_json_if_absent(storage.vote_result_key(message_id), result):
        return _result_message(storage.get_json(storage.vote_result_key(message_id)), meta)

    if winner_id:
        restaurant = next(p for p in meta["picks"] if p["id"] == winner_id)
        record = {
            **restaurant,
            "date": meta["date"],
            "selected_at": result["closed_at"],
            "selected_by": "투표",
            "voters": voters[winner_id],
            "votes": _labels(counts, meta),
            "naver_url": discord.naver_link(restaurant["name"]),
        }
        meal = meta.get("meal", meals.LUNCH)
        storage.put_json(storage.latest_key(meal), record)
        storage.put_json(storage.selection_key(restaurant["category"], meta["date"], meal), record)
        log.info("투표 마감 (%s): %s %d표", closed_by, restaurant["name"], counts[winner_id])
    else:
        log.info("투표 마감 (%s): 선택 없음", closed_by)
    if announce:
        announce(script, winner["name"] if winner else None)
    return _result_message(result, meta)


def _announcer(interaction: dict, later: list):
    """마감되면 그 채널의 하치와레가 결과를 번역하도록 응답 뒤에 할 일에 넣습니다."""
    channel_id = interaction.get("channel_id") or (interaction.get("channel") or {}).get("id")

    def announce(script, winner):
        text = hachiware.retell(script.text, "won" if winner else "none", name=winner)
        later.append(lambda: hachiware.say(channel_id, text))

    return announce


def handle_component(interaction: dict) -> tuple[dict, list]:
    """(디스코드에 돌려줄 응답, 응답 뒤에 할 일)."""
    later = []
    return _component(interaction, _announcer(interaction, later)), later


def _component(interaction: dict, announce) -> dict:
    action, date, *rest = interaction["data"]["custom_id"].split(":")
    message_id = (interaction.get("message") or {}).get("id")
    meta = storage.get_json(storage.vote_meta_key(message_id)) if message_id else None
    if not meta or action not in ("pick", "skip", "end") or (action == "pick" and not rest):
        return _ephemeral(messages.huh_sound())

    result = storage.get_json(storage.vote_result_key(message_id))
    if result:  # 이미 끝난 투표: 늦게 누른 버튼에도 결과를 보여 줍니다
        return _updated_message(_result_message(result, meta))

    user_id, name = _voter(interaction)
    if action == "end":
        return _updated_message(_close(message_id, meta, closed_by=name, announce=announce))

    if action == "pick":
        choice = next((p["id"] for p in meta["picks"] if p["id"] == rest[0]), None)
        if not choice:
            return _ephemeral(messages.huh_sound())
    else:
        choice = discord.SKIP
    storage.put_json(
        storage.ballot_key(message_id, user_id),
        {"user_id": user_id, "name": name, "choice": choice, "voted_at": config.now_kst().isoformat()},
    )
    log.info("%s 투표: %s (%s)", name, choice, message_id)

    ballots = storage.list_json(storage.ballots_prefix(message_id))
    if meta["expected"] and len(ballots) >= meta["expected"]:
        return _updated_message(_close(message_id, meta, closed_by="모두 투표", ballots=ballots, announce=announce))
    return _updated_message(
        discord.build_recommendation(
            meta["date"],
            meta["picks"],
            meta["latest"],
            ballots=ballots,
            expected=meta["expected"],
            sound=meta["sound"],
            meal=meta.get("meal", meals.LUNCH),
            today_lunch=meta.get("today_lunch"),
        )
    )


def respond(event) -> tuple[dict, list]:
    """(디스코드에 돌려줄 응답, 응답 뒤에 할 일 목록)."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")

    if not verify_signature(headers, body):
        return _response(401, {"error": "invalid request signature"}), []

    interaction = json.loads(body)
    if interaction["type"] == PING:
        return _response(200, {"type": PONG}), []
    if interaction["type"] == COMPONENT:
        custom_id = interaction["data"]["custom_id"]
        if custom_id.startswith(("game:", "bday:")):  # 게임·생일 버튼은 commands.py
            reply, later = commands.handle_component(interaction)
        else:  # 투표 버튼
            reply, later = handle_component(interaction)
        return _response(200, reply), later
    if interaction["type"] == MODAL_SUBMIT:  # 생일 입력창
        reply, later = commands.handle_modal(interaction)
        return _response(200, reply), later
    if interaction["type"] == COMMAND:
        reply, later = commands.handle(interaction)
        return _response(200, reply), later
    return _response(400, {"error": "unsupported interaction type"}), []


def run_later(jobs) -> None:
    for job in jobs:
        try:
            job()
        except Exception:  # 응답은 이미 정해졌으므로 기록만 남김
            log.exception("응답 뒤에 할 일 실패")


def handler(event, context):
    response, later = respond(event)
    run_later(later)  # Lambda 는 응답을 돌려주면 멈추므로 먼저 함 (그래서 하치와레 말이 우사기 소리보다 먼저 보일 수 있음)
    return response
