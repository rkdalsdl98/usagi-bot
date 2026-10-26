"""우사기 1:1 기억을 잠그는 열쇠와 자물쇠.

마스터 키 하나에서 사람마다 다른 키를 만들어(blake2b) 그 사람의 기억만 잠급니다(PyNaCl SecretBox).
A 의 키로는 B 의 기록을 풀 수 없어서 두 사람의 기억이 섞이지 않습니다. 파일 이름도 마스터 키로 만든 해시라
파일 목록만 보고는 누가 우사기와 대화했는지 알 수 없습니다.

마스터 키는 프로젝트 폴더·.local-s3/·.env 밖(config.VAULT_PATH, 도커에서는 usagi-vault 볼륨)에 두고
어디에도 출력하지 않습니다. 이 파일을 잃으면 기억도 모두 못 풉니다.
"""
import base64
import hashlib
import json
import os
from pathlib import Path

import nacl.exceptions
import nacl.secret
import nacl.utils

from . import config

KEY_BYTES = 32
_cache: dict[str, bytes] = {}


class Broken(Exception):
    """못 푸는 기록 (다른 사람의 키, 위조, 모양이 틀림)."""


def master(path: str | None = None) -> bytes:
    """마스터 키. 없으면 만듭니다. path 마다 한 번만 읽습니다."""
    path = path or config.VAULT_PATH
    if path not in _cache:
        _cache[path] = _read_or_create(path)
    return _cache[path]


def _read_or_create(path: str) -> bytes:
    """두 프로세스가 동시에 처음 떠도 같은 키를 쓰도록, 다 쓴 임시 파일을 제자리에 '링크'합니다 (이미 있으면 실패)."""
    target = Path(path)
    if target.exists():
        return _read(target)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.{os.urandom(4).hex()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(nacl.utils.random(KEY_BYTES))
    try:
        os.link(tmp, target)
    except FileExistsError:  # 다른 쪽이 먼저 만들었으면 그 키를 씀
        pass
    finally:
        tmp.unlink()
    return _read(target)


def _read(target: Path) -> bytes:
    key = target.read_bytes()
    if len(key) != KEY_BYTES:
        raise Broken("master key")
    return key


def _derive(master_key: bytes, label: str, guild_id: str, user_id: str, size: int) -> bytes:
    data = f"{label}:{guild_id}:{user_id}".encode()
    return hashlib.blake2b(data, key=master_key, digest_size=size).digest()


def person_key(master_key: bytes, guild_id: str, user_id: str) -> bytes:
    return _derive(master_key, "memory", str(guild_id), str(user_id), KEY_BYTES)


def guild_key(master_key: bytes, guild_id: str, label: str) -> bytes:
    """서버 하나의 파일을 잠그는 키 (/리마인드 처럼 사람을 모른 채 시각만 보고 꺼내야 하는 것)."""
    return _derive(master_key, label, str(guild_id), "", KEY_BYTES)


def file_name(master_key: bytes, guild_id: str, user_id: str) -> str:
    return _derive(master_key, "name", str(guild_id), str(user_id), 16).hex()


def key_id(master_key: bytes) -> str:
    """키를 드러내지 않고 '같은 키인지'만 견주는 지문."""
    return hashlib.blake2b(b"id", key=master_key, digest_size=8).hexdigest()


def seal(key: bytes, data: dict) -> dict:
    raw = json.dumps(data, ensure_ascii=False).encode()
    return {"v": 1, "box": base64.b64encode(nacl.secret.SecretBox(key).encrypt(raw)).decode()}


def unseal(key: bytes, record) -> dict:
    try:
        if record.get("v") != 1:
            raise Broken("version")
        raw = nacl.secret.SecretBox(key).decrypt(base64.b64decode(record["box"], validate=True))
        return json.loads(raw)
    except Broken:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, nacl.exceptions.CryptoError) as e:
        raise Broken(type(e).__name__) from None
