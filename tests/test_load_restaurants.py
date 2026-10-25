from datetime import timedelta

import boto3
import pytest
from moto import mock_aws

from lunchbot import config, storage
import recommend

M_PER_DEG_LAT = 6371000.0 * 3.141592653589793 / 180  # 경도가 같으면 haversine 거리 = 위도 차 x 이 값


def place(id, category, meters_north):
    """강남역에서 정북으로 meters_north 만큼 떨어진 가짜 식당."""
    return {
        "id": id,
        "name": f"식당{id}",
        "category": category,
        "category_detail": category,
        "address": "",
        "phone": "",
        "lat": config.CENTER_LAT + meters_north / M_PER_DEG_LAT,
        "lng": config.CENTER_LNG,
        "distance_m": round(meters_north),
        "kakao_url": "",
    }


def put_cache(restaurants, radius_m=1000, center=None, exclude=(), age_days=0):
    data = {
        "collected_at": (config.now_kst() - timedelta(days=age_days)).isoformat(),
        "center": center or [config.CENTER_LAT, config.CENTER_LNG],
        "radius_m": radius_m,
        "count": len(restaurants),
        "restaurants": restaurants,
    }
    if exclude is not None:
        data["exclude"] = list(exclude)
    storage.put_json(storage.CACHE_KEY, data)


@pytest.fixture
def collects(monkeypatch):
    """S3 를 흉내 내고, 카카오 수집은 호출 기록만 남기는 가짜로 바꾼다."""
    with mock_aws():
        boto3.client("s3").create_bucket(
            Bucket="lunch-test", CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"}
        )
        storage._s3 = None
        calls = []

        def fake_collect(api_key, lat, lng, radius_m, exclude=frozenset()):
            calls.append({"radius_m": radius_m, "exclude": set(exclude)})
            return [place("new", "한식", 100)]

        monkeypatch.setattr(recommend.kakao, "collect_restaurants", fake_collect)
        yield calls


def ids(restaurants):
    return sorted(r["id"] for r in restaurants)


def test_desserts_and_bars_are_filtered_at_pick_time(collects):
    # 캐시에는 디저트(간식)와 술집까지 전부 들어 있고, 점심 추천할 때 걸러 낸다
    put_cache([place("rice", "한식", 300), place("cake", "간식", 300), place("bar", "술집", 300)])
    assert ids(recommend.load_restaurants()) == ["rice"]
    assert collects == []  # 다시 모으지 않고 캐시에서 걸러 낸다


def test_only_places_within_800m_by_exact_distance(collects):
    # 1km 로 모아 둔 캐시에서 800m 안만 추천한다. 800.4m 는 반올림하면 800 이지만 밖이다
    put_cache(
        [
            place("near", "한식", 500),
            place("edge", "한식", 799),
            place("round", "한식", 800.4),
            place("far", "한식", 801),
            place("farther", "일식", 950),
        ]
    )
    assert ids(recommend.load_restaurants()) == ["edge", "near"]
    assert collects == []


def test_cache_recollected_when_it_cannot_cover_settings(collects):
    cases = {
        "반경이 캐시보다 넓음": dict(radius_m=500),
        "중심 좌표가 바뀜": dict(center=[37.5, 127.0]),
        "분류를 빼고 모은 예전 캐시": dict(exclude=["술집"]),
        "무엇을 뺐는지 모르는 예전 캐시": dict(exclude=None),
        "7일 지남": dict(age_days=8),
    }
    for why, kw in cases.items():
        collects.clear()
        put_cache([place("old", "한식", 100)], **kw)
        assert ids(recommend.load_restaurants()) == ["new"], why
        assert len(collects) == 1, why
    # 새로 모을 때는 지금 반경(800m)으로, 점심·저녁 모두 쓸 수 있게 분류를 빼지 않고 전부 모은다
    assert collects[-1] == {"radius_m": 800, "exclude": set()}
    assert storage.get_json(storage.CACHE_KEY)["exclude"] == []
