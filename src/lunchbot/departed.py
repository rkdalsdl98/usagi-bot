"""서버를 나가거나 추방된 사람의 사람별 기록 지우기.

지우는 것: 우사기 기억(가르친 것 포함), 남은 리마인드, 생일, 개인 번역 설정, 갑옷씨 등급, 1:1 스레드 기록과 그 스레드.
모두의 기록에 섞인 것(지난 투표 결과, 게임 점수)은 남깁니다. /추방 은 그 자리에서, 스스로 나간 사람은
버튼 서버가 SWEEP_S 마다 서버 사람 목록과 견주어 지웁니다 (scripts/serve_local.py, 처리 줄 안에서).
같은 확인에서 직장인 갑옷씨 아래인데 1:1 스레드가 있는 사람은 그 스레드에서 내보냅니다 (기록은 그대로).
로그에는 몇 명인지만 남기고 누구인지는 남기지 않습니다.
"""
import logging
import urllib.error

from . import birthdays, config, discord, hachiware, members, memory, reminders, storage, vault

log = logging.getLogger(__name__)

SWEEP_S = 600  # 나간 사람을 찾는 간격 (10분)


def _threads(guild_id: str) -> dict:
    return storage.get_json(storage.threads_key(guild_id)) or {}


def forget_person(guild_id: str, user_id: str) -> None:
    """그 사람의 사람별 기록을 지웁니다. 하나가 실패해도 나머지는 지웁니다 (기억은 키가 멀쩡할 때만, 마지막에)."""
    uid = str(user_id)
    birthdays.remove(guild_id, uid)
    hachiware.forget(uid)
    roster = members.load(guild_id)
    if roster.pop(uid, None) is not None:
        members.save(guild_id, roster)
    _forget_thread(guild_id, uid)
    if memory.usable():
        try:
            memory.forget(guild_id, uid)
            reminders.forget(guild_id, uid)
        except (vault.Broken, OSError, ValueError) as e:
            log.warning("나간 사람의 기억·리마인드를 못 지움: %s", type(e).__name__)


def _forget_thread(guild_id: str, uid: str) -> None:
    record = _threads(guild_id)
    thread = (record.get("usagi") or {}).get(uid)
    if not thread:
        return
    try:
        discord.delete_channel(config.DISCORD_BOT_TOKEN, thread, "우사기: 서버를 나간 사람의 1:1 스레드")
    except urllib.error.HTTPError as e:
        if e.code != 404:  # 지우지 못했으면 스레드 기록을 남겨 다음 확인 때 다시 지움
            log.warning("1:1 스레드를 못 지움: 스레드 관리 권한을 확인해 주세요 (HTTP %s)", e.code)
            return
    except OSError as e:  # 연결 오류도 다음 확인 때 다시
        log.warning("1:1 스레드를 못 지움: %s", type(e).__name__)
        return
    record["usagi"].pop(uid, None)
    storage.put_json(storage.threads_key(guild_id), record)


def _known(guild_id: str) -> set:
    """사람별 기록이 있는 사람들 (기억 파일은 이름이 해시라 따로 봄)."""
    people = set((storage.get_json(storage.birthdays_key(guild_id)) or {}).get("people", {}))
    people |= set(storage.get_json(storage.HACHIWARE_PEOPLE_KEY) or {})
    people |= set(members.load(guild_id))
    people |= set(_threads(guild_id).get("usagi") or {})
    return {str(p) for p in people}


def sweep(guild_id: str, member_ids: set, owner_id: str | None) -> int:
    """지금 서버에 없는 사람의 기록을 지우고, 직장인 아래인 사람을 1:1 스레드에서 내보냅니다. 지운 사람 수.

    사람 목록이 비었거나 서버 주인이 없으면(덜 읽힌 목록) 아무것도 하지 않습니다 (모두를 지우지 않게).
    """
    here = {str(m) for m in member_ids}
    if not here or (owner_id and str(owner_id) not in here):
        return 0
    gone = sorted(_known(guild_id) - here)
    for uid in gone:
        forget_person(guild_id, uid)
    strays = memory.strays(guild_id, here) if memory.usable() else []  # 다른 키로는 누구 파일인지 모름
    for key in strays:
        storage.delete(key)
    roster = members.load(guild_id)
    for uid, thread in (_threads(guild_id).get("usagi") or {}).items():
        if uid in here and members.person(uid, "", roster, owner_id).level < members.NEEDS["우사기"]:
            try:
                discord.remove_thread_member(config.DISCORD_BOT_TOKEN, thread, uid)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    log.warning("1:1 스레드에서 못 내보냄: HTTP %s", e.code)
    return len(gone) + len(strays)
