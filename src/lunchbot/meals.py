"""점심과 저녁 추천이 다른 부분을 한곳에 모읍니다.

추천·투표·저장 코드는 끼니 이름("lunch" / "dinner")으로 이 설정을 꺼내 씁니다.
설정값은 부를 때마다 config 에서 읽으므로, 테스트에서 config 를 바꾸면 그대로 반영됩니다.
"""
from dataclasses import dataclass

from . import config

LUNCH, DINNER = "lunch", "dinner"


@dataclass(frozen=True)
class Meal:
    name: str
    label: str  # 정보 줄 날짜 뒤에 붙는 말 (점심은 없음)
    channel_id: str
    channel_setting: str  # 채널 ID 를 넣는 설정 이름 (안내용)
    voter_count: int  # 0 이면 채널 인원을 자동으로 셈
    exclude: frozenset  # 식사 자리에서 뺄 분류
    drink_slots: int  # 술집 자리 수 (마지막 자리)
    accent: int  # 카드 왼쪽 띠 색
    key_prefix: str  # S3 키 앞 (점심은 예전 그대로 없음)


def get(name: str = LUNCH) -> Meal:
    if name == DINNER:
        return Meal(
            name=DINNER,
            label="저녁",
            channel_id=config.DINNER_CHANNEL_ID,
            channel_setting="DINNER_CHANNEL_ID",
            voter_count=config.DINNER_VOTER_COUNT,
            exclude=frozenset(config.DINNER_EXCLUDE_CATEGORIES | {config.DRINK_CATEGORY}),
            drink_slots=1,
            accent=0x3A5BA0,  # 남색
            key_prefix="dinner/",
        )
    return Meal(
        name=LUNCH,
        label="",
        channel_id=config.DISCORD_CHANNEL_ID,
        channel_setting="DISCORD_CHANNEL_ID",
        voter_count=config.VOTER_COUNT,
        exclude=frozenset(config.EXCLUDE_CATEGORIES),
        drink_slots=0,
        accent=0xEF9F27,  # 노란 주황
        key_prefix="",
    )
