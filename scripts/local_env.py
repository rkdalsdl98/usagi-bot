"""로컬 스크립트가 프로젝트 루트의 .env 를 읽어 환경 변수로 넣습니다. 넣을 값은 .env.example 을 보세요.

- 한 줄에 KEY=값. 빈 줄과 # 로 시작하는 줄은 건너뜁니다. 줄 끝 주석은 지원하지 않습니다.
- 값 양끝의 따옴표("..." 또는 '...')와 앞의 export 는 벗깁니다.
- 값이 비어 있으면 넣지 않습니다 (코드 기본값을 씁니다).
- 이미 설정된 환경 변수는 덮어쓰지 않습니다. 명령줄에서 준 값이 .env 보다 우선합니다.
"""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load(path=ENV_FILE, environ=os.environ):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            environ.setdefault(key, value)
