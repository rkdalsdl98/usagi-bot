import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from lunchbot import storage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import local_storage  # noqa: E402


@pytest.fixture
def s3():
    with mock_aws():
        boto3.client("s3").create_bucket(
            Bucket="lunch-test", CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"}
        )
        storage._s3 = None
        yield storage


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(local_storage, "LOCAL_DIR", tmp_path)
    return local_storage


@pytest.mark.parametrize("backend", ["s3", "local"])
def test_create_only_once_and_list_by_prefix(backend, request):
    st = request.getfixturevalue(backend)
    # 마감 결과는 처음 한 번만 써진다 (동시에 마감돼도 결과가 하나로 정해지게)
    assert st.put_json_if_absent("votes/m1/result.json", {"winner": "a"}) is True
    assert st.put_json_if_absent("votes/m1/result.json", {"winner": "b"}) is False
    assert st.get_json("votes/m1/result.json") == {"winner": "a"}
    # 표는 사람마다 따로 저장하고 접두어로 모아 읽는다
    st.put_json("votes/m1/ballots/u1.json", {"choice": "x"})
    st.put_json("votes/m1/ballots/u2.json", {"choice": "y"})
    st.put_json("votes/m2/ballots/u3.json", {"choice": "z"})
    assert sorted(b["choice"] for b in st.list_json("votes/m1/ballots/")) == ["x", "y"]
    assert st.list_json("votes/none/") == []


@pytest.mark.parametrize("backend", ["s3", "local"])
def test_delete_and_list_keys(backend, request):
    # 1:1 기억 파일을 지우고(나간 사람, /기억 지우기), 해시 이름 파일 목록을 본다(나간 사람 찾기)
    st = request.getfixturevalue(backend)
    st.put_json("memories/g/b.json", {})
    st.put_json("memories/g/a.json", {})
    st.put_json("memories/h/c.json", {})
    assert st.list_keys("memories/g/") == ["memories/g/a.json", "memories/g/b.json"]
    assert st.list_keys("memories/none/") == []
    assert st.delete("memories/g/a.json") is True and st.get_json("memories/g/a.json") is None
    assert st.delete("memories/g/a.json") is False
    assert st.list_keys("memories/g/") == ["memories/g/b.json"]


def test_install_swaps_delete_and_list_keys(monkeypatch):
    for name in ("get_json", "put_json", "put_json_if_absent", "list_json", "delete", "list_keys"):
        monkeypatch.setattr(storage, name, getattr(storage, name))  # 테스트가 끝나면 되돌림
    local_storage.install()
    assert storage.delete is local_storage.delete and storage.list_keys is local_storage.list_keys


def test_local_put_json_never_leaves_a_torn_file(local, monkeypatch):
    local.put_json("memories/g/a.json", {"ok": 1})
    write = Path.write_text

    def torn(self, text, *a, **k):  # 쓰다가 멈춤 (디스크가 참, 컨테이너가 멈춤)
        write(self, text[:3], *a, **k)
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", torn)
    with pytest.raises(OSError):
        local.put_json("memories/g/a.json", {"ok": 2})
    monkeypatch.setattr(Path, "write_text", write)
    assert local.get_json("memories/g/a.json") == {"ok": 1}  # 반쯤 쓴 파일이 남지 않음
    assert local.list_keys("memories/g/") == ["memories/g/a.json"]  # 임시 파일이 남거나 보이지 않음
