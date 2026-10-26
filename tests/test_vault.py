"""기억 암호화: 사람마다 다른 키로 잠그고, 파일 이름으로도 누구 것인지 드러나지 않게 한다."""
import base64
import json
import threading

import pytest

from lunchbot import vault


@pytest.fixture
def m(tmp_path):
    vault._cache.clear()
    return vault.master(str(tmp_path / "master.key"))


def test_each_person_has_own_key_and_name(m):
    assert vault.person_key(m, "g", "a") != vault.person_key(m, "g", "b")
    assert vault.person_key(m, "g", "a") != vault.person_key(m, "h", "a")  # 서버가 달라도 다름
    assert len(vault.person_key(m, "g", "a")) == 32
    name = vault.file_name(m, "g", "a")
    assert name != vault.file_name(m, "g", "b") and len(name) == 32 and int(name, 16) >= 0
    assert name == vault.file_name(m, "g", "a")  # 같은 사람은 늘 같은 이름


def test_sealed_record_hides_the_words_and_opens_back(m):
    key = vault.person_key(m, "g", "a")
    rec = vault.seal(key, {"likes": ["라멘"]})
    assert set(rec) == {"v", "box"} and rec["v"] == 1
    assert "라멘" not in json.dumps(rec, ensure_ascii=False)
    assert vault.unseal(key, rec) == {"likes": ["라멘"]}


def test_someone_elses_key_cannot_open_it(m):
    rec = vault.seal(vault.person_key(m, "g", "a"), {"x": 1})
    with pytest.raises(vault.Broken):
        vault.unseal(vault.person_key(m, "g", "b"), rec)


def test_tampered_or_odd_records_are_broken(m):
    key = vault.person_key(m, "g", "a")
    rec = vault.seal(key, {"x": 1})
    raw = bytearray(base64.b64decode(rec["box"]))
    raw[-1] ^= 1
    tampered = {"v": 1, "box": base64.b64encode(bytes(raw)).decode()}
    for bad in (tampered, {"v": 1}, {"v": 1, "box": "!!"}, {"v": 2, "box": rec["box"]}, None):
        with pytest.raises(vault.Broken):
            vault.unseal(key, bad)


def test_master_created_once_and_private(tmp_path):
    vault._cache.clear()
    p = tmp_path / "v" / "master.key"
    k1 = vault.master(str(p))
    vault._cache.clear()
    k2 = vault.master(str(p))
    assert k1 == k2 and len(k1) == 32
    assert (p.stat().st_mode & 0o777) == 0o600 and (p.parent.stat().st_mode & 0o777) == 0o700


def test_master_created_once_even_when_racing(tmp_path):
    # 두 컨테이너가 동시에 처음 떠도 같은 키를 써야 서로의 기록을 푼다
    p = str(tmp_path / "race" / "master.key")
    keys, start = [], threading.Barrier(8)

    def grab():
        start.wait()
        keys.append(vault._read_or_create(p))

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(keys) == 8 and len(set(keys)) == 1 and len(keys[0]) == 32


def test_tests_never_use_the_real_vault():
    # 어떤 테스트도 사용자 홈의 진짜 키 자리(~/.lunchbot-vault)를 만들거나 읽지 않는다
    from pathlib import Path

    from lunchbot import config

    assert not config.VAULT_PATH.startswith(str(Path.home() / ".lunchbot-vault"))
