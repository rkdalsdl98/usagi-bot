"""추천 메시지를 보냅니다 (EventBridge Scheduler). 점심은 매일 11:30, 저녁은 평일 18:00.

이벤트로 {"meal": "dinner"} 를 넘기면 저녁(오저뭐), 없으면 점심(오점뭐)입니다.
수동 실행 시 {"refresh": true} 를 넘기면 식당 목록을 새로 수집합니다.
"""
import logging
import random
from datetime import datetime, timedelta

from lunchbot import config, discord, hachiware, kakao, meals, messages, storage

log = logging.getLogger()
log.setLevel(logging.INFO)


def _cache_usable(cache) -> bool:
    """캐시가 지금 설정을 감당하는지: 7일 안, 같은 중심, 지금 반경 이상, 분류를 빼지 않고 전부 모음."""
    if not cache or not cache.get("restaurants"):
        return False
    fresh = config.now_kst() - datetime.fromisoformat(cache["collected_at"]) < timedelta(days=config.CACHE_DAYS)
    same_center = cache.get("center") == [config.CENTER_LAT, config.CENTER_LNG]
    covers = cache.get("radius_m", 0) >= config.RADIUS_M
    # 점심과 저녁이 빼는 분류가 달라서, 캐시는 아무것도 빼지 않고 모읍니다 (예전 캐시는 다시 모음)
    complete = cache.get("exclude") == []
    return fresh and same_center and covers and complete


def _within_radius(r) -> bool:
    """반올림한 distance_m 이 아니라 좌표로 잰 실제 거리로 반경 안인지 봅니다."""
    return kakao.haversine_m(config.CENTER_LAT, config.CENTER_LNG, r["lat"], r["lng"]) <= config.RADIUS_M


def load_restaurants(force_refresh: bool = False, exclude=None) -> list:
    """반경 안에서 exclude 분류를 뺀 식당 목록 (기본은 점심 제외 분류). 캐시를 쓸 수 없으면 새로 모읍니다."""
    exclude = config.EXCLUDE_CATEGORIES if exclude is None else exclude
    cache = None if force_refresh else storage.get_json(storage.CACHE_KEY)
    if _cache_usable(cache):
        restaurants = cache["restaurants"]
    else:
        log.info("식당 목록 수집 시작")
        restaurants = kakao.collect_restaurants(
            config.KAKAO_REST_API_KEY, config.CENTER_LAT, config.CENTER_LNG, config.RADIUS_M, exclude=frozenset()
        )
        storage.put_json(
            storage.CACHE_KEY,
            {
                "collected_at": config.now_kst().isoformat(),
                "center": [config.CENTER_LAT, config.CENTER_LNG],
                "radius_m": config.RADIUS_M,
                "exclude": [],
                "count": len(restaurants),
                "restaurants": restaurants,
            },
        )
        log.info("식당 %d곳 수집 완료", len(restaurants))
    return [r for r in restaurants if r["category"] not in exclude and _within_radius(r)]


def choose_picks(restaurants, meal: meals.Meal, avoid_ids=frozenset(), rng=None) -> list:
    """식사 자리는 끼니의 제외 분류를 빼고, 술집 자리(저녁 마지막 한 곳)는 술집에서 고릅니다.

    avoid_ids 는 고르지 않을 식당 (저녁에서는 오늘 점심으로 정해진 식당). 술집이 없으면 그 자리도 식사로 채웁니다.
    """
    rng = rng or random
    food = [r for r in restaurants if r["category"] not in meal.exclude and r["id"] not in avoid_ids]
    drinks = []
    if meal.drink_slots:
        drinks = [r for r in restaurants if r["category"] == config.DRINK_CATEGORY and r["id"] not in avoid_ids]
    n_drink = min(meal.drink_slots, len(drinks))
    picks = rng.sample(food, min(config.PICK_COUNT - n_drink, len(food)))
    if n_drink:
        picks += rng.sample(drinks, n_drink)
    return picks


def handler(event, context):
    event = event or {}
    meal = meals.get(event.get("meal", meals.LUNCH))
    if not meal.channel_id:
        raise RuntimeError(f"{meal.channel_setting} 가 설정되지 않아 {meal.name} 추천을 보낼 채널을 모릅니다.")
    date = config.today_kst()

    # 저녁은 오늘 점심으로 정해진 식당을 빼고, 정보 줄에 오늘 점심을 보여 줍니다
    today_lunch = None
    if meal.name == meals.DINNER:
        lunch = storage.get_json(storage.latest_key(meals.LUNCH))
        today_lunch = lunch if lunch and lunch.get("date") == date else None
    avoid = {today_lunch["id"]} if today_lunch else set()

    restaurants = load_restaurants(bool(event.get("refresh")), exclude=frozenset())
    chosen = choose_picks(restaurants, meal, avoid)
    if not chosen:
        raise RuntimeError("추천할 식당이 없습니다. 카카오 API 키와 좌표를 확인하세요.")

    # 고른 곳만 카카오 장소 페이지에서 대표 사진을 가져와 추천 기록에도 남깁니다 (버튼을 누른 뒤에도 씀)
    picks = [{**r, "photo_url": kakao.place_photo(r.get("kakao_url", ""))} for r in chosen]
    storage.put_json(
        storage.recommendation_key(date, meal.name),
        {"date": date, "created_at": config.now_kst().isoformat(), "picks": picks},
    )

    latest = storage.get_json(storage.latest_key(meal.name))
    lunch_name = today_lunch["name"] if today_lunch else None
    # 투표 정원: 설정값이 있으면 그 값, 없으면 채널을 볼 수 있는 사람 수 (셀 수 없으면 None = 투표 종료 버튼으로만 끝)
    expected = meal.voter_count or discord.channel_viewer_count(config.DISCORD_BOT_TOKEN, meal.channel_id)
    # 우사기 소리와 하치와레 번역을 한 토막씩 짝지어 함께 만듭니다 (번역은 켜져 있을 때만 보냄)
    script = hachiware.recommend_script(meal.name, picks, latest.get("name") if latest else None, lunch_name)
    sound = script.sound
    payload = discord.build_recommendation(
        date, picks, latest, expected=expected, sound=sound, meal=meal.name, today_lunch=lunch_name
    )
    sent = discord.send_message(config.DISCORD_BOT_TOKEN, meal.channel_id, payload)

    # 투표는 메시지마다 따로 셉니다. 메시지를 다시 그릴 때 필요한 것을 함께 남깁니다 (--preview 는 보내지 않아 id 가 없음)
    message_id = (sent or {}).get("id")
    if message_id:
        storage.put_json(
            storage.vote_meta_key(message_id),
            {
                "meal": meal.name,
                "date": date,
                "picks": picks,
                "latest": latest,
                "today_lunch": lunch_name,
                "expected": expected,
                "sound": sound,
            },
        )

        _hachiware(meal.channel_id, hachiware.retell(script.text, meal.name))

    names = [p["name"] for p in picks]
    log.info("%s 추천 전송: %s", meal.name, names)
    return {"meal": meal.name, "date": date, "picks": names}


def _hachiware(channel_id: str, text: str) -> None:
    try:
        hachiware.say(channel_id, text)
    except OSError as e:  # 번역이 안 나가도 추천은 이미 나갔으므로 기록만 (오류 문구에 웹훅 주소는 없음)
        log.warning("하치와레 번역을 못 보냄: %s", e)
