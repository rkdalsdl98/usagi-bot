"""카카오 로컬 API로 강남역 반경(RADIUS_M) 안 음식점(FD6) 전체를 수집합니다.

카테고리 검색은 한 번에 최대 45개(15개 x 3페이지)까지만 돌려주기 때문에,
검색 영역(rect)의 결과가 45개를 넘으면 4등분해서 다시 검색합니다.
원 밖으로 완전히 벗어난 사각형은 건너뜁니다.

메시지에 붙일 대표 사진은 카카오 장소 페이지의 og:image(링크 미리보기용 그림)에서 가져옵니다.
"""
import html
import json
import logging
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API_URL = "https://dapi.kakao.com/v2/local/search/category.json"
MAX_PAGEABLE = 45
PAGE_SIZE = 15
MAX_DEPTH = 8
EARTH_R = 6371000.0
OG_IMAGE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"')

log = logging.getLogger(__name__)


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; lunchbot/1.0)"})
    with urllib.request.urlopen(req, timeout=5) as res:
        return res.read().decode("utf-8", "replace")


def place_photo(place_url: str, fetch=_http_get):
    """카카오 장소 페이지의 대표 사진 주소. 사진이 없으면 카카오가 주는 지도 이미지, 못 가져오면 None."""
    if not place_url:
        return None
    try:
        page = fetch(place_url.replace("http://", "https://", 1))
    except Exception as e:  # 사진은 없어도 추천은 보내야 하므로 어떤 오류든 None
        log.warning("대표 사진을 가져오지 못했습니다 (%s): %s", place_url, e)
        return None
    m = OG_IMAGE.search(page)
    if not m:
        return None
    url = html.unescape(m.group(1))
    if url.startswith("//"):
        return "https:" + url
    return url.replace("http://", "https://", 1)


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def bounding_rect(lat, lng, radius_m):
    dlat = radius_m / 111320.0
    dlng = radius_m / (111320.0 * math.cos(math.radians(lat)))
    return (lng - dlng, lat - dlat, lng + dlng, lat + dlat)


def _rect_touches_circle(rect, lat, lng, radius_m) -> bool:
    x1, y1, x2, y2 = rect
    nearest_lng = min(max(lng, x1), x2)
    nearest_lat = min(max(lat, y1), y2)
    return haversine_m(lat, lng, nearest_lat, nearest_lng) <= radius_m


def http_fetch(api_key: str, params: dict) -> dict:
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {api_key}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return json.load(res)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise RuntimeError("카카오 API 재시도 한도 초과")


def _search_rect(api_key, rect, center, out, fetch, depth=0, delay=0.05):
    lat, lng, radius = center
    if not _rect_touches_circle(rect, lat, lng, radius):
        return
    x1, y1, x2, y2 = rect
    params = {
        "category_group_code": "FD6",
        "rect": f"{x1:.7f},{y1:.7f},{x2:.7f},{y2:.7f}",
        "page": 1,
        "size": PAGE_SIZE,
    }
    first = fetch(api_key, params)
    time.sleep(delay)
    if first["meta"]["total_count"] > MAX_PAGEABLE and depth < MAX_DEPTH:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        for sub in ((x1, y1, mx, my), (mx, y1, x2, my), (x1, my, mx, y2), (mx, my, x2, y2)):
            _search_rect(api_key, sub, center, out, fetch, depth + 1, delay)
        return

    docs = list(first["documents"])
    meta, page = first["meta"], 1
    while not meta["is_end"] and page < MAX_PAGEABLE // PAGE_SIZE:
        page += 1
        res = fetch(api_key, {**params, "page": page})
        time.sleep(delay)
        docs.extend(res["documents"])
        meta = res["meta"]
    for d in docs:
        out[d["id"]] = d


def normalize(doc: dict, lat: float, lng: float) -> dict:
    # category_name 예: "음식점 > 한식 > 해장국"
    parts = [p.strip() for p in doc.get("category_name", "").split(">")]
    category = parts[1] if len(parts) > 1 else "기타"
    detail = " > ".join(parts[1:]) if len(parts) > 1 else category
    plat, plng = float(doc["y"]), float(doc["x"])
    return {
        "id": doc["id"],
        "name": doc["place_name"],
        "category": category,
        "category_detail": detail,
        "address": doc.get("road_address_name") or doc.get("address_name", ""),
        "phone": doc.get("phone", ""),
        "lat": plat,
        "lng": plng,
        "distance_m": round(haversine_m(lat, lng, plat, plng)),
        "kakao_url": doc.get("place_url", ""),
    }


def collect_restaurants(api_key, lat, lng, radius_m, exclude=frozenset(), fetch=http_fetch, delay=0.05):
    raw = {}
    _search_rect(api_key, bounding_rect(lat, lng, radius_m), (lat, lng, radius_m), raw, fetch, delay=delay)
    result = []
    for doc in raw.values():
        # 반올림한 distance_m 으로 비교하면 1000.4m 도 1000m 가 되므로 실제 거리로 거릅니다.
        if haversine_m(lat, lng, float(doc["y"]), float(doc["x"])) > radius_m:
            continue
        r = normalize(doc, lat, lng)
        if r["category"] not in exclude:
            result.append(r)
    result.sort(key=lambda r: r["distance_m"])
    return result
