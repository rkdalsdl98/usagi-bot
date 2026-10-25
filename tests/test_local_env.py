import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import local_env  # noqa: E402


def test_env_file_values_are_loaded(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# 주석과 빈 줄은 건너뛴다",
                "",
                "KAKAO_REST_API_KEY=abc123",
                'DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/1/tok?thread_id=9"',
                "export SEARCH_PREFIX='강남역'",
                "CENTER_LAT=",
                "DISCORD_PUBLIC_KEY abc",
            ]
        ),
        encoding="utf-8",
    )
    environ = {}
    local_env.load(env_file, environ)
    # 값이 빈 CENTER_LAT 과 '=' 가 없는 줄은 넣지 않는다 (빈 값이 들어가면 config 의 float("") 가 깨짐)
    assert environ == {
        "KAKAO_REST_API_KEY": "abc123",
        "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/tok?thread_id=9",
        "SEARCH_PREFIX": "강남역",
    }


def test_existing_environment_wins(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PICK_COUNT=3\n", encoding="utf-8")
    environ = {"PICK_COUNT": "5"}
    local_env.load(env_file, environ)
    assert environ == {"PICK_COUNT": "5"}


def test_missing_env_file_is_fine(tmp_path):
    environ = {}
    local_env.load(tmp_path / ".env", environ)
    assert environ == {}
