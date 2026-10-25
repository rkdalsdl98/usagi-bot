"""생일 (선택). 월·일만 저장하고, 그날 아침 우사기 채널에서 축하합니다 (scripts/usagi_bot.py).

새로 들어온 사람에게 우사기 채널에서 입력을 권하고(버튼 → 입력창), /생일 등록·지우기로 언제든 바꿉니다.
2월 29일 생일은 윤년이 아니면 2월 28일에 축하합니다. 서버마다 birthdays/{서버 id}.json 에 저장합니다.
"""
import calendar
import re
from datetime import date

from . import config, storage

LEAP_YEAR = 2024  # 2월 29일도 받도록 윤년 기준으로 날짜를 확인


def _load(guild_id: str) -> dict:
    return storage.get_json(storage.birthdays_key(guild_id)) or {"people": {}, "sent": None}


def parse(month: str, day: str) -> tuple[int, int]:
    """입력창의 글자에서 월·일 숫자를 읽습니다 ("03", "5월" 도 받음). 숫자가 아니면 ValueError."""
    def num(text):
        m = re.fullmatch(r"\s*0*(\d{1,2})\s*(월|일)?\s*", text or "")
        if not m:
            raise ValueError("not_number")
        return int(m.group(1))

    return num(month), num(day)


def save(guild_id: str, user_id: str, month: int, day: int, by: str) -> None:
    if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(LEAP_YEAR, month)[1]:
        raise ValueError("bad_date")
    data = _load(guild_id)
    data["people"][str(user_id)] = {"month": month, "day": day, "by": by, "at": config.now_kst().isoformat()}
    storage.put_json(storage.birthdays_key(guild_id), data)


def get(guild_id: str, user_id: str):
    one = _load(guild_id)["people"].get(str(user_id))
    return (one["month"], one["day"]) if one else None


def remove(guild_id: str, user_id: str) -> bool:
    data = _load(guild_id)
    if data["people"].pop(str(user_id), None) is None:
        return False
    storage.put_json(storage.birthdays_key(guild_id), data)
    return True


def today(guild_id: str, day: date) -> list:
    """그날 생일인 사람들."""
    def celebrated_on(month, d):
        if (month, d) == (2, 29) and not calendar.isleap(day.year):
            return 2, 28
        return month, d

    return [uid for uid, b in _load(guild_id)["people"].items()
            if celebrated_on(b["month"], b["day"]) == (day.month, day.day)]


def mark_sent(guild_id: str, day: date) -> bool:
    """그날 축하를 했다고 적어 둡니다. 이미 했으면 False (봇을 다시 띄워도 한 번만)."""
    data = _load(guild_id)
    if data.get("sent") == day.isoformat():
        return False
    data["sent"] = day.isoformat()
    storage.put_json(storage.birthdays_key(guild_id), data)
    return True
