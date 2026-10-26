import os
import sys
import tempfile

import pytest
from nacl.signing import SigningKey

SIGNING_KEY = SigningKey.generate()

os.environ.update(
    {
        "BUCKET_NAME": "lunch-test",
        "KAKAO_REST_API_KEY": "test",
        "DISCORD_BOT_TOKEN": "test-bot-token",
        "DISCORD_CHANNEL_ID": "42",
        "DISCORD_PUBLIC_KEY": SIGNING_KEY.verify_key.encode().hex(),
        "AWS_DEFAULT_REGION": "ap-northeast-2",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        # 1:1 기억 마스터 키: 사용자 홈의 진짜 자리(~/.lunchbot-vault) 대신 임시 폴더 (vault_tmp 가 테스트마다 또 바꿈)
        "VAULT_PATH": os.path.join(tempfile.mkdtemp(prefix="lunchbot-vault-"), "master.key"),
    }
)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(autouse=True)
def vault_tmp(tmp_path, monkeypatch):
    """1:1 기억의 마스터 키를 테스트마다 테스트 폴더에 둡니다 (모든 테스트, 사용자 홈의 진짜 키를 건드리지 않게)."""
    from lunchbot import config, vault

    monkeypatch.setattr(config, "VAULT_PATH", str(tmp_path / "vault" / "master.key"))
    vault._cache.clear()
    yield
    vault._cache.clear()
