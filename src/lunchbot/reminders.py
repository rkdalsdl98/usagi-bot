"""리마인드: /리마인드 로 정한 시각에 하치와레가 그 사람의 1:1 스레드에서 불러 알려 줍니다.

/전체리마인드 는 모두에게: 건 채널(스레드)에서 하치와레가 @everyone 으로 부릅니다 (kind "all", 서버당 LIMIT 개,
목록은 누구나, 취소는 건 사람이나 대장 갑옷씨). 모두의 것이라 건 사람이 서버를 나가도 남깁니다.

날짜(년·월·일)를 비우면 오늘로 보고, 그 시각이 이미 지났으면 내일로 잡습니다 (날짜를 넣었는데 지났으면 거절).
알림은 보낼 때까지만 서버마다 한 파일(reminders/{서버 id}.json)에 마스터 키로 잠가 두고, 보내면 지웁니다.
사람마다 LIMIT 개까지, 자기 것만 보고 지웁니다. 보내기는 버튼 서버가 처리 줄 안에서 30초마다 합니다
(scripts/serve_local.py). 봇이 꺼져 있던 동안 지난 알림은 다시 켜질 때 "늦었지만"을 붙여 보냅니다.
"""
import logging
import urllib.error
from datetime import datetime, timedelta

from . import config, discord, hachiware, members, memory, storage, vault

log = logging.getLogger(__name__)

LIMIT = 20  # 한 사람이 걸어 둘 수 있는 알림
TEXT_CHARS = 100
LATE_S = 120  # 이보다 늦게 보내면 "늦었지만"
DROP_S = 86400  # 하루 넘게 못 보낸 알림은 버림
FIRE_S = 30  # 보낼 알림을 찾는 간격


class RemindError(Exception):
    """까닭: bad_date, past, too_many, empty"""


def when(now: datetime, hour: int, minute: int, year=None, month=None, day=None) -> datetime:
    given = any(v is not None for v in (year, month, day))
    try:
        at = datetime(year or now.year, month or now.month, day or now.day, hour, minute, tzinfo=config.KST)
    except ValueError:
        raise RemindError("bad_date") from None
    if at <= now:
        if given:
            raise RemindError("past")
        at += timedelta(days=1)
    return at


def _key(guild_id: str) -> bytes:
    return vault.guild_key(vault.master(), guild_id, "reminders")


def _load(guild_id: str) -> dict:
    record = storage.get_json(storage.reminders_key(guild_id))
    if record is None:
        return {"items": [], "next": 1}
    try:
        return vault.unseal(_key(guild_id), record)
    except (vault.Broken, ValueError, OSError) as e:
        log.warning("리마인드 파일을 못 읽음: %s", type(e).__name__)
        return {"items": [], "next": 1}


def _save(guild_id: str, data: dict) -> None:
    if not memory.usable():  # 다른 키로는 쓰지 않음 (기억과 같은 키 지문)
        raise vault.Broken("key")
    storage.put_json(storage.reminders_key(guild_id), vault.seal(_key(guild_id), data))


def _personal(item: dict) -> bool:
    return item.get("kind", "me") != "all"


def _put(guild_id: str, item: dict, same) -> dict:
    """item 을 더합니다. same(i) 인 것이 이미 LIMIT 개면 too_many."""
    item["text"] = " ".join(str(item["text"]).split())[:TEXT_CHARS]
    if not item["text"]:
        raise RemindError("empty")
    data = _load(guild_id)
    if sum(1 for i in data["items"] if same(i)) >= LIMIT:
        raise RemindError("too_many")
    item["id"] = data["next"]
    data["items"].append(item)
    data["next"] += 1
    _save(guild_id, data)
    return item


def add(guild_id: str, user_id: str, name: str, thread_id: str, text: str, at: datetime, now: datetime) -> dict:
    """개인 리마인드 (그 사람의 1:1 스레드로)."""
    uid = str(user_id)
    item = {"kind": "me", "user": uid, "name": name, "thread": str(thread_id), "text": text,
            "at": at.isoformat(), "made": now.isoformat()}
    return _put(guild_id, item, lambda i: _personal(i) and i["user"] == uid)


def add_all(guild_id: str, by_id: str, by_name: str, channel_id: str, thread_id: str | None, text: str,
            at: datetime, now: datetime) -> dict:
    """전체 리마인드 (건 채널, 스레드면 그 스레드에서 @everyone)."""
    item = {"kind": "all", "user": str(by_id), "name": by_name, "channel": str(channel_id),
            "thread": str(thread_id) if thread_id else None, "text": text, "at": at.isoformat(), "made": now.isoformat()}
    return _put(guild_id, item, lambda i: not _personal(i))


def mine(guild_id: str, user_id: str) -> list:
    """그 사람의 개인 알림 (이른 것부터)."""
    return sorted((i for i in _load(guild_id)["items"] if _personal(i) and i["user"] == str(user_id)),
                  key=lambda i: i["at"])


def everyone(guild_id: str) -> list:
    """전체 알림 (이른 것부터, 누가 걸었든)."""
    return sorted((i for i in _load(guild_id)["items"] if not _personal(i)), key=lambda i: i["at"])


def cancel_all(guild_id: str, number: int, actor_id: str, captain: bool) -> str:
    """everyone() 순서의 번호로 하나 지웁니다. ok, bad_number, not_yours (건 사람이나 대장만)."""
    items = everyone(guild_id)
    if not 1 <= number <= len(items):
        return "bad_number"
    target = items[number - 1]
    if target["user"] != str(actor_id) and not captain:
        return "not_yours"
    data = _load(guild_id)
    data["items"] = [i for i in data["items"] if i["id"] != target["id"]]
    _save(guild_id, data)
    return "ok"


def cancel(guild_id: str, user_id: str, number: int) -> bool:
    """mine() 순서의 번호(1부터)로 하나 지웁니다."""
    items = mine(guild_id, user_id)
    if not 1 <= number <= len(items):
        return False
    data = _load(guild_id)
    data["items"] = [i for i in data["items"] if i["id"] != items[number - 1]["id"]]
    _save(guild_id, data)
    return True


def forget(guild_id: str, user_id: str) -> int:
    """그 사람의 개인 알림을 모두 지웁니다 (서버를 나간 사람, 전체 알림은 모두의 것이라 남김). 지운 수."""
    data = _load(guild_id)
    kept = [i for i in data["items"] if not (_personal(i) and i["user"] == str(user_id))]
    gone = len(data["items"]) - len(kept)
    if gone:
        data["items"] = kept
        _save(guild_id, data)
    return gone


def fire_due(guild_id: str, now: datetime, send) -> int:
    """시각이 된 알림을 send(item, late) 로 보내고 지웁니다. 못 보낸 것은 다음에 다시 (하루 넘으면 버림). 보낸 수."""
    data = _load(guild_id)
    sent, kept = 0, []
    for item in data["items"]:
        overdue = (now - datetime.fromisoformat(item["at"])).total_seconds()
        if overdue < 0:
            kept.append(item)
            continue
        try:
            ok = bool(send(item, overdue > LATE_S))
        except Exception as e:  # 내용이 들어갈 수 있는 오류 문구는 남기지 않음
            log.warning("리마인드를 못 보냄: %s", type(e).__name__)
            ok = False
        sent += ok
        if not ok and overdue <= DROP_S:
            kept.append(item)
    if len(kept) != len(data["items"]):
        data["items"] = kept
        _save(guild_id, data)
    return sent


def _deliver_all(item: dict, late: bool) -> bool:
    token, thread, channel = config.DISCORD_BOT_TOKEN, item.get("thread"), item["channel"]
    if thread:
        try:
            discord.unarchive_thread(token, thread)
        except urllib.error.HTTPError:
            pass
    text = message(item, late)
    hook = hachiware.hooks().get(str(channel))
    if hook:
        discord.execute_webhook(f"{hook}?thread_id={thread}" if thread else hook, text, everyone=True)
    else:  # 그 채널에 하치와레 웹훅이 없으면 봇 계정으로 하치와레 말을
        discord.send_message(token, thread or channel, {"content": f"> **하치와레** {text}",
                                                        "allowed_mentions": {"parse": ["everyone"]}})
    return True


def fire_all(guild_id: str, owner_id: str | None, now: datetime) -> int:
    """시각이 된 알림을 하치와레가 보냅니다 (버튼 서버가 FIRE_S 마다 처리 줄 안에서 부름). 보낸 수."""
    return fire_due(guild_id, now, lambda item, late: deliver(guild_id, owner_id, item, late))


def _clock(at: datetime) -> str:
    h = at.hour % 12 or 12
    return f"{at.month}월 {at.day}일 {'오전' if at.hour < 12 else '오후'} {h}시 {at.minute}분"


def message(item: dict, late: bool) -> str:
    """하치와레의 알림 한 줄."""
    at, again = datetime.fromisoformat(item["at"]), "늦었지만 " if late else ""
    if not _personal(item):
        return f"@everyone {again}다들! 알려 달랬던 거야: \"{item['text']}\" ({_clock(at)}, {item['name']} 님이 걸어 둠)"
    return f"<@{item['user']}> {again}시간 됐어! 알려 달라던 거야: \"{item['text']}\" ({_clock(at)})"


def deliver(guild_id: str, owner_id: str | None, item: dict, late: bool) -> bool:
    """하치와레가 알립니다. 개인: 그 사람의 1:1 스레드에서 그 사람만 (직장인 갑옷씨 아래가 됐으면 버림).
    전체: 건 채널(스레드)에서 @everyone."""
    if not _personal(item):
        return _deliver_all(item, late)
    if members.person(item["user"], "", members.load(guild_id), owner_id).level < members.NEEDS["리마인드"]:
        return True  # 1:1 스레드에서 내보내졌으니 못 봄
    token, thread = config.DISCORD_BOT_TOKEN, item["thread"]
    try:
        discord.unarchive_thread(token, thread)  # 일주일 조용해서 보관됐어도 알림이 보이게
    except urllib.error.HTTPError:
        pass
    text = message(item, late)
    hook = hachiware.hooks().get(str(config.USAGI_CHANNEL_ID))
    if hook:
        discord.execute_webhook(f"{hook}?thread_id={thread}", text, users=[item["user"]])
    else:  # 하치와레 웹훅이 없으면 봇 계정으로 하치와레 말을
        discord.send_message(token, thread, {"content": f"> **하치와레** {text}",
                                             "allowed_mentions": {"parse": [], "users": [item["user"]]}})
    return True
