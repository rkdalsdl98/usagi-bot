"""로컬 실행 스크립트(run_local.py, serve_local.py)가 S3 대신 로컬 폴더를 쓰게 합니다.

기본 폴더는 .local-s3/ 이고, LOCAL_S3_DIR 환경 변수로 바꿀 수 있습니다.
두 스크립트가 같은 폴더를 쓰므로, run_local.py 로 보낸 메시지의 버튼을 serve_local.py 가 처리할 수 있습니다.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = Path(os.environ.get("LOCAL_S3_DIR", ROOT / ".local-s3"))


def _text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def get_json(key):
    path = LOCAL_DIR / key
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def put_json(key, data):
    path = LOCAL_DIR / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_text(data), encoding="utf-8")


def put_json_if_absent(key, data) -> bool:
    path = LOCAL_DIR / key
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)  # 이미 있으면 실패
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_text(data))
    return True


def list_json(prefix) -> list:
    base = LOCAL_DIR / prefix
    if not base.is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(base.glob("*.json"))]


def list_keys(prefix) -> list:
    return sorted(p.relative_to(LOCAL_DIR).as_posix() for p in LOCAL_DIR.glob(f"{prefix}*") if p.is_file())


def delete(key) -> bool:
    path = LOCAL_DIR / key
    if not path.is_file():
        return False
    path.unlink()
    return True


def install():
    """src 를 import 경로에 넣고 lunchbot.storage 가 로컬 폴더를 읽고 쓰게 바꿉니다.

    lunchbot.config 는 import 할 때 환경 변수를 읽으므로, 필요한 환경 변수를 먼저 설정한 뒤 부릅니다.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from lunchbot import storage

    storage.get_json = get_json
    storage.put_json = put_json
    storage.put_json_if_absent = put_json_if_absent
    storage.list_json = list_json
    storage.list_keys = list_keys
    storage.delete = delete
