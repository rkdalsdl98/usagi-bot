from lunchbot import kakao

URL = "http://place.map.kakao.com/2105479206"


def test_reads_og_image_from_kakao_place_page():
    seen = []

    def fetch(url):
        seen.append(url)
        return (
            '<meta property="og:title" content="차슈밍">'
            '<meta property="og:image" content="//img1.kakaocdn.net/cthumb/local/C800x400.q50/'
            '?fname=http%3A%2F%2Ft1.kakaocdn.net%2Fmystore%2FABC">'
        )

    photo = kakao.place_photo(URL, fetch=fetch)
    assert photo == "https://img1.kakaocdn.net/cthumb/local/C800x400.q50/?fname=http%3A%2F%2Ft1.kakaocdn.net%2Fmystore%2FABC"
    assert seen == ["https://place.map.kakao.com/2105479206"]


def test_place_without_photo_gets_map_image_over_https():
    # 사진이 없는 장소는 카카오가 지도 이미지를 og:image 로 준다 (http, &amp; 포함)
    html = '<meta property="og:image" content="http://staticmap.kakao.com/staticmap/og?type=place&amp;srs=wgs84">'
    assert kakao.place_photo(URL, fetch=lambda u: html) == "https://staticmap.kakao.com/staticmap/og?type=place&srs=wgs84"


def test_no_photo_when_missing_or_failing():
    def boom(url):
        raise OSError("timeout")

    def never(url):
        raise AssertionError("주소가 없으면 가져오지 않는다")

    assert kakao.place_photo("", fetch=never) is None
    assert kakao.place_photo(URL, fetch=lambda u: "<html></html>") is None
    assert kakao.place_photo(URL, fetch=boom) is None
