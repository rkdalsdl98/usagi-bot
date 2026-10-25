import os
import sys

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
    }
)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
