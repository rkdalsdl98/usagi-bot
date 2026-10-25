"""생일 (선택): 월·일만 저장하고, 그날 아침 우사기 채널에서 한 번 축하한다."""
from datetime import date

import pytest

from lunchbot import birthdays, storage
from test_flow import aws  # noqa: F401 (aws 는 fixture)


def test_save_and_remove(aws):
    birthdays.save("g1", "u1", 3, 5, by="민지")
    assert birthdays.get("g1", "u1") == (3, 5)
    birthdays.save("g1", "u1", 12, 31, by="민지")  # 다시 넣으면 바뀜
    assert birthdays.get("g1", "u1") == (12, 31)
    assert birthdays.remove("g1", "u1") is True and birthdays.get("g1", "u1") is None
    assert birthdays.remove("g1", "u1") is False
    assert storage.get_json(storage.birthdays_key("g1"))["people"] == {}


@pytest.mark.parametrize("month, day", [(0, 1), (13, 1), (2, 30), (4, 31), (1, 0), (1, 32)])
def test_bad_dates_are_refused(aws, month, day):
    with pytest.raises(ValueError):
        birthdays.save("g1", "u1", month, day, by="x")


def test_who_has_a_birthday_today(aws):
    birthdays.save("g1", "u1", 3, 5, by="x")
    birthdays.save("g1", "u2", 3, 5, by="x")
    birthdays.save("g1", "u3", 2, 29, by="x")
    assert sorted(birthdays.today("g1", date(2026, 3, 5))) == ["u1", "u2"]
    assert birthdays.today("g1", date(2027, 2, 28)) == ["u3"]  # 윤년이 아니면 2월 29일 생일은 28일에
    assert birthdays.today("g1", date(2028, 2, 28)) == []  # 윤년엔 29일에
    assert birthdays.today("g1", date(2028, 2, 29)) == ["u3"]


def test_each_day_is_celebrated_once(aws):
    assert birthdays.mark_sent("g1", date(2026, 3, 5)) is True
    assert birthdays.mark_sent("g1", date(2026, 3, 5)) is False  # 봇을 다시 띄워도 같은 날 두 번 축하하지 않음
    assert birthdays.mark_sent("g1", date(2026, 3, 6)) is True


def test_parse_month_day():
    assert birthdays.parse("3", "5") == (3, 5)
    assert birthdays.parse(" 03 ", "05월") == (3, 5)
    with pytest.raises(ValueError):
        birthdays.parse("삼", "5")
