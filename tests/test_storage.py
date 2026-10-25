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
