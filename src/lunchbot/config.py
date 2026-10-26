"""환경 변수와 공통 상수."""
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

# 한국은 서머타임이 없어서 고정 오프셋으로 충분합니다.
KST = timezone(timedelta(hours=9))

# 강남역 중심 좌표와 반경
CENTER_LAT = float(os.environ.get("CENTER_LAT", "37.497952"))
CENTER_LNG = float(os.environ.get("CENTER_LNG", "127.027619"))
RADIUS_M = int(os.environ.get("RADIUS_M", "800"))

PICK_COUNT = min(int(os.environ.get("PICK_COUNT", "5")), 5)  # 버튼은 한 줄에 최대 5개
# 투표 정원. 0 이면 채널을 볼 수 있는 사람 수(봇 제외)를 자동으로 셉니다 (개발자 포털 SERVER MEMBERS INTENT 필요).
# 자동으로 셀 수도 없으면 정원 없이 '투표 종료' 버튼으로만 끝납니다.
VOTER_COUNT = int(os.environ.get("VOTER_COUNT") or 0)
CACHE_DAYS = int(os.environ.get("CACHE_DAYS", "7"))  # 식당 목록 재수집 주기
SEARCH_PREFIX = os.environ.get("SEARCH_PREFIX", "강남역")  # 네이버 검색어 앞에 붙일 지역명

def _categories(name: str, default: str) -> set:
    return {c.strip() for c in os.environ.get(name, default).split(",") if c.strip()}


# 점심 추천에서 뺄 카카오 2단계 카테고리 (쉼표 구분). 간식은 빵집·케이크·아이스크림 같은 디저트
EXCLUDE_CATEGORIES = _categories("EXCLUDE_CATEGORIES", "술집,간식")

# 저녁 추천 (오저뭐). 야근 저녁이라 식사 4곳 + 술집 1곳을 고르고, 오늘 점심으로 정해진 식당은 뺍니다
DRINK_CATEGORY = "술집"
DINNER_CHANNEL_ID = os.environ.get("DINNER_CHANNEL_ID", "")
DINNER_VOTER_COUNT = int(os.environ.get("DINNER_VOTER_COUNT") or 0)  # 0 이면 저녁 채널 인원을 자동으로 셈
DINNER_EXCLUDE_CATEGORIES = _categories("DINNER_EXCLUDE_CATEGORIES", "간식,구내식당")

# 우사기 채널: 사람이 채팅을 보내면 우사기 봇이 채팅 내용에 맞춰 우사기 소리로 답합니다 (scripts/usagi_bot.py)
USAGI_CHANNEL_ID = os.environ.get("USAGI_CHANNEL_ID", "")
# 1:1 대화 기억을 잠그는 마스터 키 (프로젝트 폴더·.local-s3·.env 밖. 도커에서는 usagi-vault 볼륨의 /vault/master.key)
VAULT_PATH = os.environ.get("VAULT_PATH", str(Path.home() / ".lunchbot-vault" / "master.key"))
# 하치와레 웹훅 주소들 (쉼표로 구분). 웹훅은 채널마다 따로라, 하치와레가 말할 채널마다 하나씩 만듭니다.
# 우사기 채널 웹훅이 있으면 우사기 말을 번역하고, 명령을 쓴 채널의 웹훅으로 안내합니다.
# HACHIWARE_WEBHOOK_URL (하나) 도 예전처럼 읽습니다.
HACHIWARE_WEBHOOK_URLS = list(dict.fromkeys(
    u.strip()
    for u in f"{os.environ.get('HACHIWARE_WEBHOOK_URLS', '')},{os.environ.get('HACHIWARE_WEBHOOK_URL', '')}".split(",")
    if u.strip()
))

# 배포했을 때 /점심 추천 · /저녁 추천 으로 따로 부를 추천 Lambda 이름 (비우면 같은 프로세스에서 추천)
RECOMMEND_FUNCTION_NAME = os.environ.get("RECOMMEND_FUNCTION_NAME", "")

BUCKET_NAME = os.environ.get("BUCKET_NAME", "")
KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "")
# 메시지는 웹훅이 아니라 봇 계정이 채널에 직접 보냅니다
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "")
DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "")
# 디스코드 API 주소. 로컬 검사에서 가짜 서버로 바꿀 때만 씁니다
DISCORD_API_BASE = os.environ.get("DISCORD_API_BASE", "https://discord.com/api/v10")


def now_kst() -> datetime:
    return datetime.now(KST)


def today_kst() -> str:
    return now_kst().date().isoformat()
