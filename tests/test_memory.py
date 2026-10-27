"""1:1 대화 기억: 원문 없이 뽑은 것만, 사람마다 다른 키로 잠가 해시 이름 파일에 둔다."""
import json
from datetime import date, timedelta

from lunchbot import chat, config, memory, storage, vault
from test_flow import aws  # noqa: F401 (aws 는 fixture)

DAY = date(2026, 10, 26)


def seen(mem, text, day=DAY):
    memory.observe(mem, text, chat.read(text), day)


def test_saved_memory_is_sealed_and_named_by_hash(aws, vault_tmp):
    mem = memory.new()
    seen(mem, "라멘 좋아")
    memory.save("g", "a", mem)
    [key] = storage.list_keys("memories/g/")
    assert key == memory.key("g", "a") and key.split("/")[-1] != "a.json"
    assert "a" != key.split("/")[-1][:-5] and len(key.split("/")[-1]) == 32 + 5
    stored = storage.get_json(key)
    assert set(stored) == {"v", "box"} and "라멘" not in json.dumps(stored, ensure_ascii=False)
    assert memory.load("g", "a")["likes"] == ["라멘"]
    assert memory.load("g", "b") == memory.new()  # 다른 사람은 빈 기억


def test_observe_keeps_no_sentence():
    mem = memory.new()
    seen(mem, "오늘 야근이라 힘들다 라멘 먹고 싶어")
    assert mem["last_seen"] == "2026-10-26"
    assert mem["moods"] == [["2026-10-26", "sad"]] and mem["foods"] == [["2026-10-26", "라멘"]]
    assert mem["topics"] == {"sad": 1}
    assert "야근이라" not in json.dumps(mem, ensure_ascii=False)


def test_likes_and_dislikes():
    mem = memory.new()
    for text in ("치킨 좋아", "떡볶이가 좋아!", "국밥 최고", "오이 싫어", "너 좋아", "우사기 최고", "이거 좋아"):
        seen(mem, text)
    assert mem["likes"] == ["치킨", "떡볶이", "국밥"] and mem["dislikes"] == ["오이"]
    seen(mem, "치킨 좋아")  # 다시 말하면 가장 최근으로
    assert mem["likes"] == ["떡볶이", "국밥", "치킨"]


def test_lists_keep_only_the_newest(aws, vault_tmp):
    mem = memory.new()
    mem["moods"] = [[(DAY + timedelta(days=i)).isoformat(), "sad"] for i in range(12)]
    mem["likes"] = [f"음식{i}" for i in range(25)]
    mem["dislikes"] = [f"싫은것{i}" for i in range(22)]
    mem["foods"] = [[(DAY + timedelta(days=i)).isoformat(), "라멘"] for i in range(7)]
    mem["taught"] = [{"words": [f"말{i}"], "kind": "answer", "answer": "응", "at": "2026-10-26"} for i in range(55)]
    memory.save("g", "a", mem)
    got = memory.load("g", "a")
    assert got["moods"] == mem["moods"][-10:] and got["likes"] == mem["likes"][-20:]
    assert got["dislikes"] == mem["dislikes"][-20:] and got["foods"] == mem["foods"][-5:]
    assert got["taught"] == mem["taught"][-50:]


def test_forget_and_forget_taught(aws, vault_tmp):
    mem = memory.new()
    mem["taught"] = [{"words": ["점메추"], "kind": "meaning", "topic": "lunch", "ask": "what", "at": "2026-10-26"},
                     {"words": ["힘내"], "kind": "answer", "answer": "오늘도 화이팅", "at": "2026-10-26"}]
    memory.save("g", "a", mem)
    assert memory.forget_taught("g", "a", 1) is True
    assert [t["words"] for t in memory.load("g", "a")["taught"]] == [["힘내"]]
    assert memory.forget_taught("g", "a", 9) is False and memory.forget_taught("g", "a", 0) is False
    assert memory.forget("g", "a") is True and memory.load("g", "a") == memory.new()
    assert memory.forget("g", "a") is False and storage.list_keys("memories/g/") == []
    assert memory.forget_taught("g", "nobody", 1) is False


def test_broken_file_reads_as_empty(aws, vault_tmp, tmp_path, monkeypatch):
    mem = memory.new()
    seen(mem, "라멘 좋아")
    memory.save("g", "a", mem)
    storage.put_json(memory.key("g", "a"), {"v": 1, "box": "망가짐"})
    assert memory.load("g", "a") == memory.new()
    memory.save("g", "b", mem)
    key_b = memory.key("g", "b")
    monkeypatch.setattr(config, "VAULT_PATH", str(tmp_path / "other" / "master.key"))  # 키를 잃음
    vault._cache.clear()
    storage.put_json(memory.key("g", "b"), storage.get_json(key_b))  # 같은 사람의 새 이름 자리에 옛 암호문
    assert memory.load("g", "b") == memory.new()


def test_strays_are_files_of_people_not_here(aws, vault_tmp):
    memory.save("g", "a", memory.new())
    memory.save("g", "gone", memory.new())
    memory.save("h", "x", memory.new())
    assert memory.strays("g", {"a"}) == [memory.key("g", "gone")]
    assert memory.strays("g", {"a", "gone"}) == []


def test_food_words_match_whole_words_only():
    mem = memory.new()
    seen(mem, "회의 끝나고 회사 앞에서 치킨이랑 햄버거")
    assert [f for _, f in mem["foods"]] == ["치킨", "햄버거"]  # 회의·회사의 '회', 햄버거 속 '버거' 는 아님


def switch_key(tmp_path, monkeypatch, content=None):
    """마스터 키를 다른 것으로 (잃어버렸거나 다른 곳의 키를 씀). content 를 주면 그 내용의 망가진 키."""
    path = tmp_path / "other-vault" / "master.key"
    if content is not None:
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
    monkeypatch.setattr(config, "VAULT_PATH", str(path))
    vault._cache.clear()


def test_key_mismatch_locks_memory(aws, tmp_path, monkeypatch):
    memory.save("g", "a", memory.new())
    assert memory.usable() is True
    switch_key(tmp_path, monkeypatch)  # 버튼 서버와 우사기 봇이 서로 다른 키를 씀
    assert memory.usable() is False and memory.load("g", "a") == memory.new()


def test_broken_master_key_locks_memory(aws, tmp_path, monkeypatch):
    switch_key(tmp_path, monkeypatch, content=b"short")
    assert memory.usable() is False and memory.load("g", "a") == memory.new()  # 예외 없음


def test_truncated_file_reads_as_empty(aws):
    import boto3

    memory.save("g", "a", memory.new())
    boto3.client("s3").put_object(Bucket="lunch-test", Key=memory.key("g", "a"), Body=b'{"v": 1, "bo')
    assert memory.load("g", "a") == memory.new()


def test_known_words_are_kept_newest(aws):
    mem = memory.new()
    mem["known"] = [f"낱말{i}" for i in range(305)]
    memory.save("g", "a", mem)
    assert memory.load("g", "a")["known"] == mem["known"][-300:]


def test_worry_and_done_are_remembered_as_moods():
    mem = memory.new()
    seen(mem, "내일 출장이라 걱정돼")
    seen(mem, "드디어 끝이다")
    assert [k for _, k in mem["moods"]] == ["worry", "done"]
