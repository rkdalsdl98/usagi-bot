"""S3 저장소. 키 구조:

  latest/selection.json                 가장 최근에 고른 식당 (투표로 정해질 때마다 덮어씀)
  selections/{카테고리}/{YYYY-MM-DD}.json  카테고리별 선택 기록 (한식/중식/일식 ...)
  recommendations/{YYYY-MM-DD}.json     그날 추천한 5곳 (같은 날 다시 추천하면 덮어씀)
  cache/restaurants.json                강남역 반경 안 식당 목록 캐시
  votes/{메시지 id}/meta.json            그 메시지의 투표 정보 (날짜, 5곳, 정원, 우사기 소리, 지난번 선택)
  votes/{메시지 id}/ballots/{사용자 id}.json  사람마다 한 표 (다시 누르면 덮어씀)
  votes/{메시지 id}/result.json          마감 결과 (처음 한 번만 써짐)
  members/{서버 id}.json                 갑옷씨 멤버와 등급 (우사기 명령 /멤버추가 등)
  settings/hachiware.json               하치와레 번역 서버 전체 (/전체번역 켜기·끄기, 없으면 꺼짐)
  settings/hachiware_people.json        하치와레 번역 개인 설정 (/하치와레 번역 켜기·끄기)
  threads/{서버 id}.json                 /우사기 로 만든 1:1 비공개 스레드 (사람마다 스레드 id)
  roles/{서버 id}.json                   갑옷씨 등급마다 디스코드 역할 id
  birthdays/{서버 id}.json               생일 (선택, 월·일), 마지막으로 축하한 날
  games/{채널 id}.json                   이미지 랜덤 주제 게임 진행 상태

저녁(오저뭐)의 latest, selections, recommendations 는 앞에 dinner/ 를 붙여 점심과 따로 둡니다.
식당 목록 캐시와 votes/ 는 함께 씁니다 (투표는 메시지마다 따로이고, 어느 끼니인지는 meta.json 에 있음).
"""
import json

import boto3
from botocore.exceptions import ClientError

from . import config, meals

CACHE_KEY = "cache/restaurants.json"

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _prefix(meal: str) -> str:
    return meals.get(meal).key_prefix


def latest_key(meal: str = meals.LUNCH) -> str:
    return f"{_prefix(meal)}latest/selection.json"


LATEST_KEY = latest_key()  # 점심


def recommendation_key(date: str, meal: str = meals.LUNCH) -> str:
    return f"{_prefix(meal)}recommendations/{date}.json"


def selection_key(category: str, date: str, meal: str = meals.LUNCH) -> str:
    safe = (category or "기타").replace("/", "_").strip() or "기타"
    return f"{_prefix(meal)}selections/{safe}/{date}.json"


def vote_meta_key(message_id: str) -> str:
    return f"votes/{message_id}/meta.json"


def ballots_prefix(message_id: str) -> str:
    return f"votes/{message_id}/ballots/"


def ballot_key(message_id: str, user_id: str) -> str:
    return f"{ballots_prefix(message_id)}{user_id}.json"


def vote_result_key(message_id: str) -> str:
    return f"votes/{message_id}/result.json"


def members_key(guild_id: str) -> str:
    return f"members/{guild_id}.json"


HACHIWARE_KEY = "settings/hachiware.json"  # 하치와레 번역 서버 전체 (메뉴 추천·투표 결과, 정하지 않은 사람의 기본)
HACHIWARE_PEOPLE_KEY = "settings/hachiware_people.json"  # 하치와레 번역 개인 설정 {사용자 id: {"translate": …}}


def roles_key(guild_id: str) -> str:
    return f"roles/{guild_id}.json"  # 갑옷씨 등급 역할의 디스코드 역할 id


def birthdays_key(guild_id: str) -> str:
    return f"birthdays/{guild_id}.json"  # 생일 (선택): 사람마다 월·일 (버튼 서버가 씀)


def birthdays_sent_key(guild_id: str) -> str:
    return f"birthdays/{guild_id}-sent.json"  # 마지막으로 축하한 날 (우사기 봇이 씀, 생일 목록과 따로)


def game_key(channel_id: str) -> str:
    return f"games/{channel_id}.json"  # 이미지 랜덤 주제 게임 (채널마다 하나)


def threads_key(guild_id: str) -> str:
    return f"threads/{guild_id}.json"  # /우사기 1:1 스레드: 사람마다 스레드 id


def _body(data) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def get_json(key: str):
    try:
        obj = _client().get_object(Bucket=config.BUCKET_NAME, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise
    return json.loads(obj["Body"].read())


def put_json(key: str, data) -> None:
    _client().put_object(
        Bucket=config.BUCKET_NAME, Key=key, Body=_body(data), ContentType="application/json; charset=utf-8"
    )


def put_json_if_absent(key: str, data) -> bool:
    """키가 없을 때만 씁니다. 이미 있으면 쓰지 않고 False (S3 조건부 쓰기 If-None-Match)."""
    try:
        _client().put_object(
            Bucket=config.BUCKET_NAME,
            Key=key,
            Body=_body(data),
            ContentType="application/json; charset=utf-8",
            IfNoneMatch="*",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] in ("PreconditionFailed", "ConditionalRequestConflict"):
            return False
        raise
    return True


def list_json(prefix: str) -> list:
    """접두어 아래의 JSON 을 모두 읽어 돌려줍니다 (표를 모을 때 씀, 많아야 수십 개)."""
    keys = []
    for page in _client().get_paginator("list_objects_v2").paginate(Bucket=config.BUCKET_NAME, Prefix=prefix):
        keys += [o["Key"] for o in page.get("Contents", [])]
    return [get_json(k) for k in sorted(keys)]


def list_keys(prefix: str) -> list:
    """접두어 아래의 키 이름들 (정렬). 1:1 기억 파일처럼 이름만 보면 될 때 씁니다."""
    keys = []
    for page in _client().get_paginator("list_objects_v2").paginate(Bucket=config.BUCKET_NAME, Prefix=prefix):
        keys += [o["Key"] for o in page.get("Contents", [])]
    return sorted(keys)


def delete(key: str) -> bool:
    """지웁니다. 없었으면 False."""
    try:
        _client().head_object(Bucket=config.BUCKET_NAME, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return False
        raise
    _client().delete_object(Bucket=config.BUCKET_NAME, Key=key)
    return True
