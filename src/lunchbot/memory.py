"""우사기 1:1 대화 기억 (사람마다 따로, 원문 없이).

채팅 원문은 남기지 않고 뽑은 것만 남깁니다: 마지막으로 이야기한 날, 최근 기분, 자주 하는 이야기 종류,
좋아한다/싫어한다고 한 것, 최근 이야기한 음식, 그 사람이 가르쳐 준 것, 기억 안내를 본 날.
사람마다 다른 키로 잠가(vault) memories/{서버 id}/{해시}.json 에 둡니다. 파일이 망가졌거나 키를 잃었으면
빈 기억으로 봅니다 (봇은 계속 대화함).
"""
import logging
import re
from datetime import date

from . import chat, storage, talk, vault

log = logging.getLogger(__name__)

MOOD_KINDS = ("sad", "angry", "laugh", "praise", "surprise")
KINDS = frozenset(kind for kind, _ in chat.KINDS)
KEY_ID_KEY = "memories/key-id.json"  # 기억 파일들을 잠근 마스터 키의 지문 (키 자체는 아님)
LIMITS = {"moods": 10, "likes": 20, "dislikes": 20, "foods": 5, "taught": 50}  # 최근 것만 (오래된 것은 밀려남)
NOT_THINGS = frozenset({"너", "나", "넌", "난", "우사기", "그거", "이거", "저거", "다", "진짜", "너무", "완전", "정말"})
FOOD_WORDS = ("라멘", "라면", "국밥", "순대국", "치킨", "피자", "햄버거", "버거", "떡볶이", "초밥", "스시", "파스타",
              "짜장면", "짬뽕", "탕수육", "삼겹살", "고기", "김밥", "샐러드", "커피", "돈까스", "돈가스", "카레", "쌀국수",
              "냉면", "김치찌개", "된장찌개", "부대찌개", "비빔밥", "샌드위치", "마라탕", "족발", "보쌈", "우동", "덮밥")  # 두 글자 이상만 (한 글자는 '회의'·'회사'처럼 잘못 잡힘)
_LIKE = re.compile(r"(\S+)\s+(?:좋아|최고)")
_DISLIKE = re.compile(r"(\S+)\s+싫어")


def new() -> dict:
    return {"v": 1, "last_seen": None, "moods": [], "topics": {}, "likes": [], "dislikes": [], "foods": [],
            "taught": [], "noticed": None}


def _master() -> bytes:
    return vault.master()


def usable() -> bool:
    """기억을 쓸 수 있는지: 마스터 키가 멀쩡하고, 기억 파일들을 잠근 키와 같은지.

    두 서버가 서로 다른 키를 쓰면(VAULT_PATH·usagi-vault 볼륨이 다름) 남의 키로는 아무 파일도 못 알아보므로
    기억을 읽지도 쓰지도, 나간 사람 파일로 보고 지우지도 않습니다.
    """
    try:
        mine = vault.key_id(_master())
        stored = storage.get_json(KEY_ID_KEY)
        if stored is None:
            storage.put_json_if_absent(KEY_ID_KEY, {"id": mine})
            stored = storage.get_json(KEY_ID_KEY)
        if (stored or {}).get("id") == mine:
            return True
        log.warning("기억 열쇠가 기억 파일들을 잠근 열쇠와 달라 기억을 쓰지 않습니다 (VAULT_PATH·usagi-vault 볼륨 확인)")
    except (vault.Broken, OSError, ValueError) as e:
        log.warning("기억 열쇠를 읽지 못해 기억을 쓰지 않습니다: %s", type(e).__name__)
    return False


def key(guild_id: str, user_id: str) -> str:
    return f"memories/{guild_id}/{vault.file_name(_master(), str(guild_id), str(user_id))}.json"


def load(guild_id: str, user_id: str) -> dict:
    """그 사람의 기억. 없거나, 못 풀거나(다른 키·위조), 파일이 망가졌으면 빈 기억."""
    try:
        record = storage.get_json(key(guild_id, user_id))
        if record is None:
            return new()
        return {**new(), **vault.unseal(vault.person_key(_master(), str(guild_id), str(user_id)), record)}
    except (vault.Broken, ValueError, OSError) as e:
        log.warning("기억 파일을 못 읽어 빈 기억으로 봅니다: %s", type(e).__name__)  # 누구 것인지는 남기지 않음
        return new()


def save(guild_id: str, user_id: str, mem: dict) -> None:
    """잠가서 저장합니다. 처음 저장할 때 키 지문을 남기고, 지문이 다른 키로는 쓰지 않습니다 (vault.Broken)."""
    if not usable():
        raise vault.Broken("key")
    kept = {**mem, **{field: mem[field][-n:] for field, n in LIMITS.items()}}
    record = vault.seal(vault.person_key(_master(), str(guild_id), str(user_id)), kept)
    storage.put_json(key(guild_id, user_id), record)


def forget(guild_id: str, user_id: str) -> bool:
    return storage.delete(key(guild_id, user_id))


def forget_taught(guild_id: str, user_id: str, number: int) -> bool:
    """가르친 것 하나를 지웁니다 (1부터). 없는 번호면 False."""
    mem = load(guild_id, user_id)
    if not 1 <= number <= len(mem["taught"]):
        return False
    del mem["taught"][number - 1]
    save(guild_id, user_id, mem)
    return True


def _remember(items: list, thing: str) -> None:
    if thing in items:
        items.remove(thing)
    items.append(thing)


def observe(mem: dict, text: str, reading: chat.Reading, today: date) -> None:
    """채팅에서 기억할 것만 뽑아 mem 을 고칩니다 (원문은 넣지 않음)."""
    day = today.isoformat()
    mem["last_seen"] = day
    if reading.kind in KINDS:
        mem["topics"][reading.kind] = mem["topics"].get(reading.kind, 0) + 1
    if reading.kind in MOOD_KINDS:
        mem["moods"].append([day, reading.kind])
    clean = chat._clean(text)
    for pattern, field in ((_LIKE, "likes"), (_DISLIKE, "dislikes")):
        for raw in pattern.findall(clean):
            thing = talk.strip(raw)
            if thing and thing not in NOT_THINGS:
                _remember(mem[field], thing)
    tokens = [chat._word(t) for t in clean.split()]
    for food in FOOD_WORDS:  # 낱말이 음식 이름으로 시작할 때만 (치킨이랑 → 치킨, 햄버거 속 '버거' 는 아님)
        if any(t.startswith(food) for t in tokens):
            mem["foods"].append([day, food])


def strays(guild_id: str, user_ids: set) -> list:
    """memories/{서버}/ 아래 파일 중 지금 서버에 있는 누구의 것도 아닌 것 (나간 사람의 기억)."""
    mine = {key(guild_id, u) for u in user_ids}
    return [k for k in storage.list_keys(f"memories/{guild_id}/") if k not in mine]
