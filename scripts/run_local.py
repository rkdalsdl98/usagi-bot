"""추천 Lambda(recommend.py)를 로컬에서 실행해, 봇 계정으로 디스코드 채널에 실제 추천 메시지를 보냅니다.

S3 대신 로컬 폴더(기본 .local-s3/)에 저장합니다. 식당 목록 캐시도 여기에 남으므로
첫 실행만 카카오 API로 수집하고(1분 안팎), 그다음부터는 바로 보냅니다.
버튼 클릭까지 확인하려면 serve_local.py 를 함께 띄웁니다.

사용법:
  .env 에 KAKAO_REST_API_KEY, DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID 를 넣고 (.env.example 참고)
  uv run --python 3.12 --with boto3 scripts/run_local.py

  --dinner      저녁 추천을 오저뭐(DINNER_CHANNEL_ID)로 보내기 (식사 4곳 + 술집 1곳, 오늘 점심 식당 제외)
  --refresh     식당 목록을 카카오 API로 다시 수집
  --no-buttons  버튼만 빼고 보내기
  --sample      카카오 API 대신 샘플 식당으로 보내기 (메시지 확인용, KAKAO_REST_API_KEY 불필요)
  --preview     디스코드로 보내지 않고 보낼 메시지(JSON)만 출력 (봇 토큰, 채널 ID 불필요)
"""
import json
import logging
import os
import sys
import urllib.error
import urllib.parse

import local_env

local_env.load()
import local_storage  # noqa: E402  (.env 의 LOCAL_S3_DIR 을 읽도록 load 뒤에 import)

OPTIONS = {"--dinner", "--refresh", "--no-buttons", "--sample", "--preview"}
# 오타나 한 덩어리로 들어온 옵션('--dinner --preview')을 그냥 넘기면 기본값(점심 실제 전송)으로 보내 버리므로 멈춥니다
unknown = [a for a in sys.argv[1:] if a not in OPTIONS]
if unknown:
    sys.exit(f"모르는 옵션입니다: {' '.join(repr(a) for a in unknown)}\n{__doc__}")

SAMPLE = "--sample" in sys.argv
PREVIEW = "--preview" in sys.argv
DINNER = "--dinner" in sys.argv
CHANNEL_SETTING = "DINNER_CHANNEL_ID" if DINNER else "DISCORD_CHANNEL_ID"

# --sample 용 가짜 식당: (이름, 카카오 세부 분류, 강남역에서 거리 m)
SAMPLE_RESTAURANTS = [
    ("샘플 국밥집", "한식 > 국밥", 180),
    ("샘플 김치찌개", "한식 > 찌개,전골", 320),
    ("샘플 중화요리", "중식 > 중국요리", 410),
    ("샘플 초밥", "일식 > 초밥,롤", 260),
    ("샘플 라멘", "일식 > 일본식라면", 530),
    ("샘플 파스타", "양식 > 이탈리안", 640),
    ("샘플 버거", "양식 > 햄버거", 720),
    ("샘플 떡볶이", "분식", 150),
    ("샘플 쌀국수", "아시아음식 > 베트남음식", 880),
    ("샘플 샐러드", "샐러드", 470),
    ("샘플 이자카야", "술집 > 일본식주점", 390),  # 저녁 술집 자리용 (점심에서는 빠짐)
]

required = ([] if SAMPLE else ["KAKAO_REST_API_KEY"]) + ([] if PREVIEW else ["DISCORD_BOT_TOKEN", CHANNEL_SETTING])
missing = [k for k in required if not os.environ.get(k)]
if missing:
    sys.exit(f"환경 변수가 없습니다: {', '.join(missing)} (.env 에 넣어 주세요)\n{__doc__}")

logging.basicConfig(level=logging.INFO, format="%(message)s")
local_storage.install()
from lunchbot import config, discord  # noqa: E402
import recommend  # noqa: E402

if SAMPLE:
    # 카카오를 부르지 않고 식당 캐시에도 쓰지 않습니다 (나중에 실제 목록과 섞이지 않게).
    # 추천 기록에는 남으므로 serve_local.py 로 버튼 클릭은 처리됩니다.
    samples = [
        {
            "id": f"sample-{i}",
            "name": name,
            "category": detail.split(" > ")[0],
            "category_detail": detail,
            "address": "서울 강남구 (샘플)",
            "phone": "",
            "lat": config.CENTER_LAT,
            "lng": config.CENTER_LNG,
            "distance_m": distance,
            "kakao_url": "",
        }
        for i, (name, detail, distance) in enumerate(SAMPLE_RESTAURANTS, 1)
    ]
    recommend.load_restaurants = lambda force_refresh=False, exclude=None: samples

if PREVIEW:
    discord.send_message = lambda token, channel_id, payload: print(json.dumps(payload, ensure_ascii=False, indent=2))
    # 미리보기는 보내지 않으므로 채널 ID 가 없어도 됩니다 (정원은 셀 수 없어 '투표 N명'으로 보임)
    setattr(config, CHANNEL_SETTING, getattr(config, CHANNEL_SETTING) or "preview")

if "--no-buttons" in sys.argv:
    _build = discord.build_recommendation
    discord.build_recommendation = lambda *a, **kw: _build(*a, **kw, buttons=False)

try:
    out = recommend.handler({"refresh": "--refresh" in sys.argv, "meal": "dinner" if DINNER else "lunch"}, None)
except urllib.error.HTTPError as e:
    # 요청 주소는 호스트만 보여 줍니다 (봇 토큰은 헤더에 있어 출력되지 않음).
    host = urllib.parse.urlsplit(e.url).netloc
    sys.exit(f"{host} 요청 실패: HTTP {e.code}\n{e.read().decode('utf-8', 'replace')}")

what = "저녁 추천" if DINNER else "점심 추천"
done = f"{what} 미리보기만 출력했습니다 (보내지 않음)" if PREVIEW else f"{what}을 보냈습니다"
print(f"\n{out['date']} {done}{' (샘플 데이터)' if SAMPLE else ''}: {', '.join(out['picks'])}")
print(f"저장한 파일: {local_storage.LOCAL_DIR}")
