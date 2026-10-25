"""갑옷씨 멤버와 등급: 행인 갑옷씨 → 직장인 갑옷씨 → 대장 갑옷씨.

우사기 명령(/멤버추가 · /멤버승급 · /멤버강등 · /멤버삭제, /추방)으로 서버 사람을 멤버로 등록하고 등급을 정합니다. 멤버가 아닌 사람은 등급 0 입니다.
자기 등급과 그 아래 등급의 명령을 쓸 수 있습니다 (NEEDS).

  승급        자기보다 낮은 멤버를, 지금보다 높고 자기 등급 이하인 등급으로 (대장은 대장까지)
  강등        자기보다 낮은 멤버를, 지금보다 낮은 등급으로
  삭제·추방   자기보다 낮은 사람에게만 (추방은 멤버가 아닌 사람도)

서버 주인은 멤버 목록에 없어도 항상 대장이고, 다른 대장보다도 높습니다 (아무도 주인을 내리거나 내보낼 수 없음).
멤버 목록은 서버마다 members/{서버 id}.json 에 저장합니다.
"""
from dataclasses import dataclass

from . import config, storage

WALKER, WORKER, CAPTAIN = 1, 2, 3
RANKS = {WALKER: "행인 갑옷씨", WORKER: "직장인 갑옷씨", CAPTAIN: "대장 갑옷씨"}

# 명령마다 필요한 등급 (0 은 누구나). 순서대로 /도움 에 보입니다
NEEDS = {
    "도움": 0,
    "우사기": 0,
    "점심 추천": 0,
    "저녁 추천": 0,
    "하치와레 번역 켜기": 0,
    "하치와레 번역 끄기": 0,
    "생일 등록": 0,
    "생일 지우기": 0,
    "게임 시작": 0,  # 게임 안에서 누가 무엇을 할 수 있는지는 lunchbot/game.py (시작한 사람, 술래, 사회자)
    "게임 답": 0,
    "게임 결과": 0,
    "게임 점수": 0,
    "게임 끝": 0,
    "멤버추가": WALKER,
    "멤버승급": WORKER,  # 행인은 자기보다 낮은 멤버가 없어 아무도 올릴 수 없음
    "멤버강등": WORKER,
    "멤버삭제": WORKER,
    "추방": WORKER,
    "전체번역 켜기": WORKER,  # 메뉴 추천·투표 결과 번역 (서버 전체)
    "전체번역 끄기": WORKER,
}
_TARGETS_MEMBER = {"멤버승급", "멤버강등", "멤버삭제"}  # 대상이 멤버여야 하는 명령


@dataclass(frozen=True)
class Person:
    id: str
    name: str = ""
    level: int = 0  # 0 이면 멤버 아님
    owner: bool = False  # 서버 주인
    bot: bool = False


def person(user_id: str, name: str, roster: dict, owner_id: str | None, bot: bool = False) -> Person:
    """멤버 목록(roster)과 서버 주인으로 그 사람의 등급을 정합니다."""
    owner = bool(owner_id) and str(user_id) == str(owner_id)
    level = CAPTAIN if owner else int((roster.get(str(user_id)) or {}).get("rank", 0))
    return Person(str(user_id), name, level, owner, bot)


def outranks(a: Person, b: Person) -> bool:
    """a 가 b 보다 높은지. 서버 주인은 다른 대장보다도 높습니다."""
    return a.level > b.level or (a.owner and not b.owner)


def allowed(level: int) -> list[str]:
    return [command for command, need in NEEDS.items() if level >= need]


def check(command: str, actor: Person, target: Person | None = None, rank: int | None = None) -> str | None:
    """명령을 할 수 없으면 그 까닭(hachiware.NOTICES 의 키), 할 수 있으면 None."""
    if actor.level < NEEDS[command]:
        return "rank_low"
    if target is None:
        return None
    if target.bot:
        return "bot"
    if target.id == actor.id:
        return "self"
    if command == "멤버추가":
        return "already" if target.level else None
    if target.owner:
        return "owner" if command != "멤버승급" else "not_lower"
    if command in _TARGETS_MEMBER and not target.level:
        return "not_member"
    if not outranks(actor, target):
        return "not_lower"
    if command == "멤버승급":
        if rank not in RANKS:
            return "bad_rank"
        if rank <= target.level:
            return "not_up"
        if rank > actor.level:
            return "rank_too_high"
    if command == "멤버강등":
        if rank not in RANKS:
            return "bad_rank"
        if rank >= target.level:
            return "not_down"
    return None


def load(guild_id: str) -> dict:
    """{사용자 id: {"rank", "name", "by", "at"}}"""
    return (storage.get_json(storage.members_key(guild_id)) or {}).get("members", {})


def save(guild_id: str, roster: dict) -> None:
    storage.put_json(storage.members_key(guild_id), {"members": roster, "updated_at": config.now_kst().isoformat()})
