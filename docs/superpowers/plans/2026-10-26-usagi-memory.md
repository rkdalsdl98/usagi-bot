# 우사기 1:1 대화 기억 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/우사기` 1:1 비공개 스레드에서 우사기가 물음의 의도에 가깝게 답하고, 문맥을 잇고, 사람마다 암호화한 기억과 가르친 것을 써서 대화한다.

**Architecture:** 디스코드와 상관없는 순수 모듈 다섯 개를 만든다: `vault`(키·암호화), `memory`(사람별 기억 저장), `talk`(채팅 읽기·문맥·가르치기 알아보기), `answers`(봇이 아는 정보로 답 만들기), `dialog`(이들을 엮는 1:1 대화 한 턴). 우사기 봇(`scripts/usagi_bot.py`)은 스레드 채팅을 `dialog`에 넘기고 받은 것을 보내기만 한다. 등급·명령·나간 사람 정리는 버튼 서버(`src/commands.py`, `scripts/serve_local.py`)가 처리 줄(`lunchbot/inbox.py`) 안에서 한다.

**Tech Stack:** Python 3.12, PyNaCl 1.5.0 (`nacl.secret.SecretBox`), `hashlib.blake2b`, discord.py 2.4.0 (우사기 봇만), pytest + moto, 로컬 도커 compose.

**Spec:** `docs/superpowers/specs/2026-10-26-usagi-memory-design.md`

## Global Constraints

- 규칙 기반만. AI·언어 모델·외부 정보 API를 쓰지 않는다. 새 패키지를 더하지 않는다 (PyNaCl, 표준 라이브러리만)
- 로컬 도커에서만 동작하면 된다 (Lambda 배포 경로는 바꾸지 않아도 됨)
- 화면 글은 모두 한국어. 우사기는 소리만 내고, 우사기 소리 한 토막 = 하치와레 번역 한 토막이다 (`hachiware.speak(beats)`로 만든다)
- 1:1 스레드 대화 원문을 어디에도 쓰지 않는다: 파일, 로그(이름·우사기 소리·하치와레 번역 줄 포함), 오류 로그. 모든 1:1 스레드에 적용하고, 공개 우사기 채널 로그는 그대로 둔다
- 기억 파일: `memories/{서버 id}/{해시}.json` = `{"v": 1, "box": "<base64 암호문>"}`. 사람 키 `blake2b(key=마스터, data="memory:" + 서버 id + ":" + 사용자 id)`, 파일 이름 `blake2b(key=마스터, data="name:" + 서버 id + ":" + 사용자 id)` 16진수
- 마스터 키는 프로젝트 폴더·`.local-s3/`·`.env` 밖에 둔다 (도커 named volume `usagi-vault`, 컨테이너 안 `/vault/master.key`). 어디에도 출력하지 않는다
- 숫자: 짧은 문맥 10분, 가르치기 기다림 5분, 비슷함 기준 0.5, 알려 준 답 100자, 최근 기분 10개, 좋아함·싫어함 각 20개, 최근 음식 5개, 가르친 것 50개, 기억을 꺼내는 기분·음식은 7일 안의 것만
- 정해진 문장: 모르는 물음 → 우사기 `[("puzzled", "음…?"), ("sulky", "잘 모르겠어…")]` + 하치와레 따옴표 밖 "무슨 뜻인지 알려 줄래?" (가르칠 수 있는 사람만). 기억함 → `[("excited", "알았어!"), ("happy", "다음엔 그렇게 말할게~")]`
- 등급: `/우사기`, `/기억 보기`, `/기억 지우기`는 직장인 갑옷씨(`members.WORKER`) 이상
- 기록을 자동으로 지우는 경우는 서버를 나가거나 추방됐을 때뿐이다 (시간 지남·강등으로는 안 지움)
- 커밋 메시지는 한국어, **`Co-Authored-By`·`Generated with` 같은 AI 표시 줄을 넣지 않는다**. push 하지 않는다
- 테스트: `PYTHONDONTWRITEBYTECODE=1 /private/tmp/claude-501/-Users-kangmin-project-lunchbot/8b187e5a-8b2c-43b8-ab0a-2421451e6d41/scratchpad/venv/bin/python -m pytest -q` (아래에서 `PYTEST`). 우사기 봇 테스트만 `uv run --quiet --python 3.12 --with discord.py==2.4.0 --with boto3 --with moto --with pytest --with pynacl==1.5.0 pytest -q tests/test_usagi_threads.py` (아래에서 `PYTEST_BOT`)

## Review Focus

- **남의 스레드에 다른 사람이 채팅** (스레드를 볼 수 있는 관리자): 스레드 주인의 기억·짧은 문맥·가르친 것이 그 사람 답에 나오면 안 되고, 아무것도 기록하지 않는다 → Task 5 `test_other_person_in_my_thread_sees_nothing_of_mine`
- **번역이 꺼져 있거나 하치와레 웹훅이 없음:** 기억 파일을 읽지도 쓰지도 않고, 되묻기·가르치기도 하지 않는다 → Task 5 `test_translation_off_touches_no_memory`
- **키를 잃었거나 기억 파일이 망가짐:** 봇이 죽지 않고 빈 기억으로 대화를 이어 간다 → Task 2 `test_broken_file_reads_as_empty`
- **알려 준 답에 멘션·링크·아주 긴 글:** 알림이 가지 않고(`allowed_mentions` 막음, 웹훅도 마찬가지) 100자에서 자른다 → Task 4 `test_taught_answer_is_cut_and_quiet`, Task 6 `test_thread_messages_never_ping`
- **두 컨테이너가 동시에 처음 뜸:** 마스터 키를 둘이 따로 만들면 서로 못 푼다. 같은 키를 써야 한다 → Task 1 `test_master_created_once_even_when_racing`

---

### Task 1: 키와 암호화 (`vault`)

**Files:**
- Create: `src/lunchbot/vault.py`
- Modify: `src/lunchbot/config.py` (`VAULT_PATH` 추가)
- Test: `tests/test_vault.py`

**Interfaces:**
- Produces:
  - `config.VAULT_PATH: str` = 환경 변수 `VAULT_PATH`, 없으면 `str(Path.home() / ".lunchbot-vault" / "master.key")`
  - `vault.Broken(Exception)`: 못 푸는 기록 (다른 키, 위조, 모양이 틀림)
  - `vault.master(path: str | None = None) -> bytes`: 32바이트. 없으면 `nacl.utils.random(32)`로 만들어 `os.open(O_WRONLY|O_CREAT|O_EXCL, 0o600)`으로 쓰고(폴더는 0o700), `FileExistsError`면 이미 있는 것을 읽는다. path 마다 한 번 읽고 기억해 둔다
  - `vault.person_key(master: bytes, guild_id: str, user_id: str) -> bytes` (32바이트)
  - `vault.file_name(master: bytes, guild_id: str, user_id: str) -> str` (digest_size=16, 32자 16진수)
  - `vault.seal(key: bytes, data: dict) -> dict` → `{"v": 1, "box": base64}`
  - `vault.unseal(key: bytes, record: dict) -> dict` (못 풀면 `Broken`)

- [ ] **Step 1: Write the failing tests** (`tests/test_vault.py`)

```python
def test_each_person_has_own_key_and_name():
    m = vault.master(str(tmp / "k"))
    assert vault.person_key(m, "g", "a") != vault.person_key(m, "g", "b")
    assert vault.file_name(m, "g", "a") != vault.file_name(m, "g", "b")
    assert len(vault.file_name(m, "g", "a")) == 32 and "a" != vault.file_name(m, "g", "a")

def test_sealed_record_hides_the_words_and_opens_back():
    key = vault.person_key(m, "g", "a")
    rec = vault.seal(key, {"likes": ["라멘"]})
    assert set(rec) == {"v", "box"} and "라멘" not in json.dumps(rec, ensure_ascii=False)
    assert vault.unseal(key, rec) == {"likes": ["라멘"]}

def test_someone_elses_key_cannot_open_it():
    rec = vault.seal(vault.person_key(m, "g", "a"), {"x": 1})
    with pytest.raises(vault.Broken):
        vault.unseal(vault.person_key(m, "g", "b"), rec)

def test_tampered_or_odd_records_are_broken():  # box 한 글자 바꿈, {"v": 1}, {"box": "!!"}
    ...각각 pytest.raises(vault.Broken)

def test_master_created_once_and_private(tmp_path):
    p = tmp_path / "v" / "master.key"
    k1 = vault.master(str(p)); vault._cache.clear(); k2 = vault.master(str(p))
    assert k1 == k2 and len(k1) == 32 and (p.stat().st_mode & 0o777) == 0o600

def test_master_created_once_even_when_racing(tmp_path):  # 스레드 8개가 동시에 master(같은 path) (캐시 없이)
    assert len(set(keys)) == 1
```

- [ ] **Step 2: Run to verify they fail**: `PYTEST tests/test_vault.py` → FAIL (`No module named 'lunchbot.vault'`)
- [ ] **Step 3: Implement `vault.py`과 `config.VAULT_PATH`** (위 Interfaces 그대로. 캐시는 `_cache: dict[str, bytes]`. 경쟁 테스트가 캐시를 거치지 않게 `_read_or_create(path)`를 따로 두고 `master`가 그것을 캐시)
- [ ] **Step 4: Run**: `PYTEST tests/test_vault.py` → PASS, `PYTEST` → 전체 PASS
- [ ] **Step 5: Commit**: `git add src/lunchbot/vault.py src/lunchbot/config.py tests/test_vault.py && git commit -m "기억 암호화: 사람마다 다른 키와 숨긴 파일 이름"`

---

### Task 2: 사람별 기억 저장 (`memory`) + 저장소 지우기·목록

**Files:**
- Create: `src/lunchbot/memory.py`
- Modify: `src/lunchbot/storage.py` (`delete`, `list_keys`), `scripts/local_storage.py` (같은 두 함수 + `install()`에서 바꿔 끼움)
- Test: `tests/test_memory.py`, `tests/test_storage.py` (지우기·목록)

**Interfaces:**
- Consumes: Task 1 `vault.master`, `vault.person_key`, `vault.file_name`, `vault.seal`, `vault.unseal`, `vault.Broken`
- Produces:
  - `storage.delete(key: str) -> bool` (없으면 False), `storage.list_keys(prefix: str) -> list[str]` (정렬). 로컬판은 `LOCAL_DIR / key` 기준
  - `memory.new() -> dict` = `{"v": 1, "last_seen": None, "moods": [], "topics": {}, "likes": [], "dislikes": [], "foods": [], "taught": [], "noticed": None}`
    - `moods`: `[["2026-10-26", "sad"], …]`, `foods`: `[["2026-10-26", "라멘"], …]`, 날짜는 ISO 글자
    - `taught`: `[{"words": ["점메추"], "kind": "meaning", "topic": "lunch", "ask": "what", "at": "2026-10-26"}, {"words": [...], "kind": "answer", "answer": "오늘도 화이팅", "at": …}]`
  - `memory.key(guild_id: str, user_id: str) -> str` = `f"memories/{guild_id}/{vault.file_name(...)}.json"`
  - `memory.load(guild_id, user_id) -> dict` (없거나 `Broken`이면 `new()`. 로그에 id·이름을 넣지 않음)
  - `memory.save(guild_id, user_id, mem: dict) -> None` (넣기 전에 최신 것만 남김: moods 10, likes 20, dislikes 20, foods 5, taught 50)
  - `memory.forget(guild_id, user_id) -> bool`, `memory.forget_taught(guild_id, user_id, number: int) -> bool` (1부터)
  - `memory.observe(mem: dict, text: str, reading: chat.Reading, today: date) -> None` (원문은 넣지 않음)
    - `last_seen` = 오늘
    - `topics[reading.kind] += 1` (`chat.KINDS`의 종류만)
    - 기분 종류 `MOOD_KINDS = ("sad", "angry", "laugh", "praise", "surprise")`면 moods에 더함
    - `"X 좋아"`/`"X가 좋아"`/`"X 최고"` → likes, `"X 싫어"` → dislikes. X는 `talk.words`와 같은 규칙으로 다듬은 낱말이고, `너`·`나`·`우사기`·`그거`·`이거`는 뺌
    - `FOOD_WORDS`에 있는 음식 낱말 → foods
  - `memory.strays(guild_id: str, user_ids: set[str]) -> list[str]`: `memories/{서버}/` 아래 키 중 지금 사람 누구의 `key()`와도 안 맞는 것

- [ ] **Step 1: Write the failing tests**

```python
def test_storage_delete_and_list(aws):            # tests/test_storage.py
    storage.put_json("memories/g/a.json", {}); storage.put_json("memories/g/b.json", {})
    assert storage.list_keys("memories/g/") == ["memories/g/a.json", "memories/g/b.json"]
    assert storage.delete("memories/g/a.json") is True and storage.delete("memories/g/a.json") is False

def test_saved_memory_is_sealed_and_named_by_hash(aws, vault_tmp):   # tests/test_memory.py
    mem = memory.new(); memory.observe(mem, "라멘 좋아", chat.read("라멘 좋아"), date(2026, 10, 26))
    memory.save("g", "a", mem)
    [k] = storage.list_keys("memories/g/")
    assert "a" not in k.split("/")[-1] and "라멘" not in json.dumps(storage.get_json(k), ensure_ascii=False)
    assert memory.load("g", "a")["likes"] == ["라멘"] and memory.load("g", "b") == memory.new()

def test_observe_keeps_no_sentence():
    mem = memory.new(); memory.observe(mem, "오늘 야근이라 힘들다 라멘 먹고 싶어", chat.read(...), date(2026, 10, 26))
    assert mem["moods"] == [["2026-10-26", "sad"]] and mem["foods"] == [["2026-10-26", "라멘"]]
    assert "야근이라" not in json.dumps(mem, ensure_ascii=False)

def test_lists_keep_only_the_newest(aws, vault_tmp):   # moods 12개 넣고 save → load 하면 10개, 가장 오래된 2개 빠짐 (foods 5, likes 20, taught 50 도)

def test_forget_and_forget_taught(aws, vault_tmp):
    # taught 두 개 저장 → forget_taught(..., 1) True, 남은 것은 둘째 / forget_taught(..., 9) False / forget True → load == new()

def test_broken_file_reads_as_empty(aws, vault_tmp):   # 저장 뒤 box 를 망가뜨리거나 마스터 키를 바꾸면 load == new() (예외 없음)

def test_strays_are_files_of_people_not_here(aws, vault_tmp):
    memory.save("g", "a", memory.new()); memory.save("g", "gone", memory.new())
    assert memory.strays("g", {"a"}) == [memory.key("g", "gone")]
```

`vault_tmp` fixture는 `tests/conftest.py`에 둔다: `monkeypatch.setattr(config, "VAULT_PATH", str(tmp_path / "master.key")); vault._cache.clear()`.

- [ ] **Step 2: Run**: `PYTEST tests/test_memory.py tests/test_storage.py` → FAIL
- [ ] **Step 3: Implement** `storage.delete/list_keys`(S3: `delete_object` 전에 `head_object`로 있는지 확인, `list_objects_v2` 페이지), 로컬판, `memory.py`
- [ ] **Step 4: Run**: 위 테스트 PASS, `PYTEST` 전체 PASS
- [ ] **Step 5: Commit**: `git commit -m "사람별 기억 저장: 원문 없이 뽑은 것만, 암호화해서"`

---

### Task 3: 채팅 읽기와 문맥 (`talk`)

**Files:**
- Create: `src/lunchbot/talk.py`
- Test: `tests/test_talk.py`

**Interfaces:**
- Consumes: `chat._clean`, `chat._word`, `chat._asking`
- Produces:
  - `talk.words(text: str) -> frozenset[str]`: `chat._clean` → 띄어쓰기로 나눔 → `chat._word` → 끝의 조사 `PARTICLES = ("에서", "이야", "은", "는", "이", "가", "을", "를", "에", "도", "야", "요")`를 떼되 남는 글자가 2자 이상일 때만
  - `talk.TOPICS: dict[str, tuple[str, ...]]`, `talk.ASKS: dict[str, tuple[str, ...]]` — 채팅 안에 들어 있으면 그 화제·물음. 키는 아래 표에 나온 것을 모두 갖는다 (낱말 목록은 구현자가 채우되 표의 예문은 모두 맞아야 함)
  - `talk.Context` (dataclass): `topic: str | None, ask: str | None, target: str | None, asked: str | None, unknown: frozenset | None, at: datetime` — 설계의 "마지막 3마디" 대신 바로 앞 상태 하나를 둔다 (이어 묻기·"거기"·되물음·가르치기에 필요한 것은 이것뿐)
  - `talk.Turn` (dataclass): `kind: str` (`"question"`, `"taught"`, `"unknown"`, `"teach"`, `"reply"`, `"chat"`), `topic: str | None = None`, `ask: str | None = None`, `words: frozenset = frozenset()`, `follow: bool = False`, `teach: dict | None = None`, `answer: str | None = None`
  - `talk.CONTEXT_S = 600`, `talk.TEACH_S = 300`, `talk.SIMILAR = 0.5`
  - `talk.similar(a: frozenset, b: frozenset) -> float` (자카드)
  - `talk.understand(text: str, ctx: Context | None, now: datetime, taught: list, supported: Callable[[str, str], bool]) -> Turn`
  - `talk.teaching(text: str, supported) -> dict | None` → `{"kind": "answer", "answer": "…"}` 또는 `{"kind": "meaning", "topic": …, "ask": …}`

`understand` 규칙 (이 순서):
1. `ctx`가 `CONTEXT_S`보다 오래됐으면 없는 것으로 본다
2. `ctx.unknown`이 있고 `TEACH_S` 안이며 `teaching(text)`가 무엇을 돌려주면 → `Turn("teach", words=ctx.unknown, teach=…)`
3. `ctx.asked`가 있고, 채팅이 물음이 아니며 낱말 3개 이하 → `Turn("reply", topic=ctx.asked, words=…)`
4. 가르친 `meaning` 중 그 `words`가 모두 채팅 낱말에 들어 있으면 그 `topic`·`ask`를 쓴다
5. 화제·물음을 고른다 (가장 먼저 나온 것). `chat._asking(text)`가 거짓이고 가르친 `answer`와도 안 맞으면 `Turn("chat")`
6. 물음인데 화제가 없으면 `ctx.topic`, 물음말이 없으면 `ctx.ask`를 이어받고 `follow=True`. "거기"·"그 집"·"그거"는 화제 `place`(대상은 `ctx.target`)
7. 가르친 `answer` 중 `similar ≥ SIMILAR`인 것이 있으면 가장 높은 것 → `Turn("taught", answer=…)`
8. `supported(topic, ask)`면 `Turn("question", …)`, 아니면 `Turn("unknown", words=…)`

`teaching` 규칙: 따옴표(`'`, `"`, `‘’`, `“”`) 안의 글 + 뒤에 "라고" → answer(100자에서 자름). "라는 뜻", "란 뜻", "뜻이야", "말하는 거", "의미" 가 있거나 "야"/"이야"로 끝나면 → 그 설명을 `understand`처럼 읽어 `supported`인 화제·물음이 나오면 meaning, 아니면 None

- [ ] **Step 1: Write the failing tests** (`supported`는 테스트에서 `lambda t, a: (t, a) in {("lunch","what"), ("dinner","what"), ("dinner","when"), ("place","how"), ("place","where"), ("usagi","like")}`)

```python
@pytest.mark.parametrize("text, topic, ask", [
    ("오늘 점심 뭐야?", "lunch", "what"), ("점심 정해졌어?", "lunch", "what"), ("저녁 추천 언제 와?", "dinner", "when"),
    ("지난번에 뭐 먹었지?", "last", "what"), ("내 생일 언제로 돼 있어?", "birthday", "when"), ("게임 점수 몇 점이야?", "game", "what"),
    ("내 등급 뭐야?", "rank", "what"), ("지금 몇 시야?", "time", "what"), ("퇴근까지 얼마나 남았어?", "off", "when"),
    ("너 누구야?", "usagi", "who"), ("우사기는 뭐 좋아해?", "usagi", "like"), ("밥 먹었어?", "usagi", "eat"),
    ("하치와레는 누구야?", "hachiware", "who"), ("나 기억해?", "me", "remember"), ("내가 뭐 좋아한다고 했지?", "me", "like"),
    ("우리 마지막으로 언제 얘기했지?", "talk", "when"), ("심심해 뭐 하지?", "bored", "what"), ("힘든데 어떡해?", "tired", "how"),
    ("뭐 먹을까?", "food", "what")])
def test_reads_topic_and_ask(text, topic, ask): ...   # understand(..., ctx=None) 의 topic, ask (supported 는 모두 True 로)

def test_follow_up_keeps_the_ask_and_switches_topic():   # "오늘 점심 뭐야?" 뒤 ctx → "그럼 저녁은?" == ("dinner", "what", follow=True)
def test_there_means_the_last_place():                    # ctx.target="농민백암순대" → "거기 맛있어?" == ("place", "how"), "거기 어디야?" == ("place", "where")
def test_new_topic_is_not_a_follow_up():                  # ctx lunch → "우사기는 뭐 좋아해?" == ("usagi","like"), follow False
def test_old_context_is_dropped():                        # ctx.at 11분 전 → "그럼 저녁은?" 은 follow False
def test_unknown_question():                              # "점메추 해줘?" → kind "unknown", words ⊇ {"점메추"}
def test_teaching_meaning_and_answer():
    assert talk.teaching("점메추는 점심 메뉴 추천이야", sup) == {"kind": "meaning", "topic": "lunch", "ask": "what"}
    assert talk.teaching("그럴 땐 '오늘도 화이팅'이라고 해 줘", sup) == {"kind": "answer", "answer": "오늘도 화이팅"}
    assert talk.teaching("배고프다", sup) is None
def test_teach_only_right_after_unknown():                # ctx.unknown + 4분 → "teach", 6분 → teach 아님
def test_taught_meaning_and_answer_are_used():            # taught meaning 점메추 → "점메추 뭐야?" == question lunch/what; taught answer → kind "taught"
def test_reply_to_usagis_question():                      # ctx.asked="food" → "라멘" == Turn("reply", topic="food")
def test_plain_chat_is_chat():                            # "ㅋㅋㅋ 웃겨" → kind "chat"
```

- [ ] **Step 2: Run**: `PYTEST tests/test_talk.py` → FAIL
- [ ] **Step 3: Implement `talk.py`** (위 규칙 그대로)
- [ ] **Step 4: Run**: PASS, `PYTEST` 전체 PASS
- [ ] **Step 5: Commit**: `git commit -m "1:1 대화 읽기: 물음의 화제·의도, 이어지는 물음, 가르치기 알아보기"`

---

### Task 4: 답 만들기 (`answers`)

**Files:**
- Create: `src/lunchbot/answers.py`
- Test: `tests/test_answers.py`

**Interfaces:**
- Consumes: Task 3 `talk.Turn`, `talk.Context`; `hachiware.speak`, `hachiware.Script`; `storage`(추천·최근 선택·생일·게임·멤버), `members`
- Produces:
  - `answers.SUPPORTED: set[tuple[str, str]]` = Task 3 표의 (topic, ask) 모두 + `("place", "how")`, `("place", "where")`. `answers.supported(topic, ask) -> bool`은 이것 또는 `ask in ("why", "really")`(어느 화제든 짧게 받음)
  - `answers.Facts` (dataclass): `picks: list[dict]` (오늘 추천 5곳), `winner: dict | None` (`latest/selection.json`의 날짜가 오늘일 때), `dinner_picks: list[dict]`, `latest: dict | None`, `birthday: tuple | None`, `score: int | None` (우사기 채널 게임에서 이 사람 점수), `rank: int`, `now: datetime`
  - `answers.gather(guild_id: str, user_id: str, owner_id: str | None, now: datetime) -> Facts`
  - `answers.Reply` (dataclass): `script: hachiware.Script`, `own: str = ""` (하치와레 따옴표 밖 말), `target: str | None = None` (방금 말한 식당 이름), `asked: str | None = None` (우사기가 되물은 화제)
  - `answers.answer(turn: talk.Turn, facts: Facts, mem: dict | None, ctx: talk.Context | None, rng) -> Reply`: 화제·물음마다 비트 틀 여럿 중 하나. 정보가 없으면 "아직 몰라"류로 답함 (예: 오늘 추천이 없으면 "아직 추천 전이래"). `("food","what")`은 `facts.picks` 중 하나를 골라 `target`으로. `("bored","what")`·`("tired","how")`는 가끔 `asked="food"`처럼 되묻는다. mem 이 None 이면 `me`·`talk` 화제는 "기억 기능은 직장인 갑옷씨부터래"가 아니라 그냥 "음… 잘 모르겠어"류로 답함
  - `answers.unknown(teachable: bool, rng) -> Reply` (Global Constraints의 정해진 문장)
  - `answers.learned(rng) -> Reply` (정해진 문장)
  - `answers.reply_to(turn: talk.Turn, rng) -> Reply`: 되물음에 대한 답 ("라멘" → "라멘 좋다!"), 음식 낱말이면 `target`
  - `answers.taught_answer(text: str, rng) -> Reply`: 100자에서 자르고, 띄어쓰기·문장부호로 1~4 토막, 기분 "happy"
  - `answers.recall(mem: dict, reading: chat.Reading, today: date, rng) -> str | None`: 인사(`greet`)일 때 하치와레 따옴표 밖 한마디. 마지막 대화가 2일 이상 전이면 "N일 만이네!", 7일 안 음식이 있으면 "어제 라멘 먹었어?"("어제"/"N일 전"), 7일 안 sad/angry 기분이 있으면 "오늘은 좀 괜찮아?". 없으면 None
  - `answers.MEMORY_GUIDE: str`: 처음 안내. 다음을 모두 담는다 — 기억하는 것(마지막으로 이야기한 날, 기분, 자주 하는 이야기, 좋아하거나 싫어한다고 한 것, 최근 이야기한 음식, 가르쳐 준 것), 대화 원문은 남기지 않음, 그 사람만의 열쇠로 잠가(암호화) 저장, 서버를 나가거나 추방되면 지움, `/기억 보기`·`/기억 지우기`

- [ ] **Step 1: Write the failing tests**

```python
def test_every_answer_pairs_sound_and_words(aws):        # SUPPORTED 모두에 대해 answer(...) → len(script.sound.split()) == len(script.parts) >= 1
def test_lunch_answer_uses_todays_vote(aws):             # latest 날짜 오늘 "농민백암순대" → "농민백암순대" in script.text and reply.target == "농민백암순대"
def test_lunch_answer_before_any_recommendation(aws):     # 저장소 비어 있음 → 식당 이름 없이 답 (예외 없음)
def test_what_to_eat_picks_one_of_todays_five(aws):      # target in {p["name"] for p in picks}
def test_time_and_off_work(aws):                         # now 17:20 평일 → ("time","what") 에 "5시 20분", ("off","when") 에 "40분"
def test_my_birthday_and_rank(aws):                      # 생일 3/5 → "3월 5일", 서버 주인 → "대장 갑옷씨"
def test_unknown_and_learned_fixed_words():
    r = answers.unknown(True, rng)
    assert [w for _, w in r.script.parts] == ["음…?", "잘 모르겠어…"] and r.own == "무슨 뜻인지 알려 줄래?"
    assert answers.unknown(False, rng).own == ""
    assert [w for _, w in answers.learned(rng).script.parts] == ["알았어!", "다음엔 그렇게 말할게~"]
def test_taught_answer_is_cut_and_quiet():               # 150자 + "<@123> https://x.y" → script.text 는 100자 이내, 토막 1~4개
def test_recall_only_recent_things():                    # foods 어제 라멘 → "어제 라멘 먹었어?" ; 10일 전 라멘 → None ; 3일 전 last_seen → "3일 만이네!"
def test_memory_guide_tells_everything():
    for w in ("기분", "좋아", "음식", "가르쳐", "원문", "열쇠", "추방", "/기억 보기", "/기억 지우기"): assert w in answers.MEMORY_GUIDE
```

- [ ] **Step 2: Run**: `PYTEST tests/test_answers.py` → FAIL
- [ ] **Step 3: Implement `answers.py`** (답 틀은 `hachiware.NOTICES`처럼 `{(topic, ask): [[(기분, 토막), …], …]}`에 `{place}`, `{time}` 같은 자리를 둔다)
- [ ] **Step 4: Run**: PASS, `PYTEST` 전체 PASS
- [ ] **Step 5: Commit**: `git commit -m "1:1 대화 답: 봇이 아는 정보로 채우고, 모르면 되묻기"`

---

### Task 5: 1:1 대화 한 턴 (`dialog`)

**Files:**
- Create: `src/lunchbot/dialog.py`
- Test: `tests/test_dialog.py`

**Interfaces:**
- Consumes: Task 2 `memory.*`, Task 3 `talk.*`, Task 4 `answers.*`, `members.load/person/WORKER`, `storage.threads_key`, `chat.read`, `hachiware.relay`
- Produces:
  - `dialog.Out` (dataclass): `sound: str`, `hachiware: str | None` (번역이 꺼져 있으면 None)
  - `dialog.Talk` (dataclass): `outs: list[Out]`, `plain: bool` (True 면 "평범한 채팅: 우사기 봇이 지금 방식(`chat.plan` + `hachiware.translate`)대로 답함"), `remark: str | None` (plain 일 때 하치와레 번역 뒤에 붙일 기억 한마디)
  - `dialog.owner_of(guild_id: str, thread_id: str) -> str | None` (`threads/{서버}.json`의 `usagi`를 거꾸로 찾음)
  - `dialog.Dialog()` — 짧은 문맥을 `(스레드 id, 채팅한 사람 id)`마다 메모리에만 둔다
    - `respond(self, *, guild_id: str, thread_id: str, author_id: str, owner_id: str | None, text: str, now: datetime, translating: bool, rng) -> Talk`
    - `drop(self, thread_id: str, user_id: str | None = None) -> None`

`respond` 규칙:
1. `remember` = 채팅한 사람이 `owner_of(스레드)`이고, 등급(`members.person(..., owner_id)`)이 `WORKER` 이상이고, `translating`이 참. 거짓이면 기억 파일을 **열지도 쓰지도 않는다**
2. `remember`이고 `mem["noticed"]`가 없으면 → `outs`의 맨 앞에 안내 한 줄(우사기 `[("happy", "잠깐!")]` 류 + 하치와레 `answers.MEMORY_GUIDE`), `noticed`=오늘로 저장, **이번 채팅은 기록하지 않음**
3. `talk.understand(text, ctx, now, taught=mem["taught"] if remember else [], supported=answers.supported)`
4. 종류별: `teach`(remember 일 때만) → taught 에 더하고 `answers.learned` / `question` → `answers.answer(turn, gather(...), mem if remember else None, ctx)` / `taught` → `answers.taught_answer` / `unknown` → `answers.unknown(teachable=remember)`, remember 면 ctx.unknown = turn.words / `reply` → `answers.reply_to` / `chat` → `Talk([], plain=True, remark=answers.recall(mem, …) if remember else None)`
5. `remember`이고 2번이 아니었으면 `memory.observe` 후 `memory.save`
6. 짧은 문맥을 고친다 (topic·ask·target·asked·unknown·at). `translating`이 거짓이면 하치와레 말(`Out.hachiware`)은 None

- [ ] **Step 1: Write the failing tests** (fixture: aws, vault_tmp, `threads/g.json` = `{"usagi": {"a": "ta", "b": "tb"}}`, members: a·b 직장인, w 행인, 서버 주인 own)

```python
def test_first_chat_shows_guide_and_records_nothing():   # a 첫 채팅 → outs[0].hachiware 에 MEMORY_GUIDE, 저장된 기억은 noticed 만 (moods·likes 비어 있음)
def test_remembers_after_the_guide():                    # 둘째 채팅 "라멘 좋아" → memory.load("g","a")["likes"] == ["라멘"]
def test_follow_up_in_conversation():                    # "오늘 점심 뭐야?" → 식당 이름, 이어서 "거기 어디야?" → 같은 식당 주소/거리
def test_teach_then_use():                               # "점메추?" → unknown(own 있음) → "점심 메뉴 추천이라는 뜻이야" → learned → "점메추 뭐야?" → 점심 답
def test_one_persons_teaching_is_not_anothers():         # a 가 가르친 점메추 → b 가 자기 스레드에서 "점메추?" → unknown
def test_other_person_in_my_thread_sees_nothing_of_mine():
    # a 의 스레드(ta)에 b 가 채팅: a 가 가르친 것·a 의 짧은 문맥(직전 식당)을 안 쓰고, a·b 기억 파일 모두 그대로 (저장 키 목록·내용이 전과 같음)
def test_translation_off_touches_no_memory(monkeypatch): # memory.load/save 를 터지는 함수로 바꿔도 respond 가 끝남, outs 의 hachiware 는 None, unknown 의 own == ""
def test_below_worker_is_not_remembered():               # w 의 스레드(있다고 치고) → 기억 파일 안 생김
def test_short_context_is_per_person_and_expires():      # (ta, a) 문맥이 (ta, b) 에 안 보임; 11분 뒤 follow 안 됨
def test_plain_chat_brings_back_a_memory():              # 3일 전 last_seen 저장 → "안녕" → plain True, remark == "3일 만이네!"
```

- [ ] **Step 2: Run**: `PYTEST tests/test_dialog.py` → FAIL
- [ ] **Step 3: Implement `dialog.py`**
- [ ] **Step 4: Run**: PASS, `PYTEST` 전체 PASS
- [ ] **Step 5: Commit**: `git commit -m "1:1 대화 한 턴: 사람마다 따로, 안내 뒤에만 기억"`

---

### Task 6: 우사기 봇에 붙이기 + 스레드 로그 끄기

**Files:**
- Modify: `scripts/usagi_bot.py` (`answer`, `translate`, 새 `answer_in_thread`)
- Test: `tests/test_usagi_threads.py` (맨 위 `pytest.importorskip("discord")`)

**Interfaces:**
- Consumes: Task 5 `dialog.Dialog`, `dialog.Talk`, `dialog.Out`; `translating(user_id)`, `hachiware_url`
- Produces: `usagi_bot.talks = dialog.Dialog()`; `async def answer_in_thread(batch) -> None`

규칙:
- `answer(batch)`: 채널이 스레드(`parent_id` 있음)면 `answer_in_thread(batch)`로 보내고 끝. 공개 채널은 지금 그대로 (로그 포함)
- `answer_in_thread`: `talks.respond(...)`를 `asyncio.to_thread`로 부름 (`owner_id=channel.guild.owner_id`, `translating=bool(hachiware_url) and translating(author)`, `now=config.now_kst()`). `outs`마다 '입력 중…'(`chat._typing(text, out.sound, random)`초) 뒤 우사기 소리를 보내고, 하치와레 말이 있으면 `HACHIWARE_DELAY_S` 뒤 `?thread_id=` 웹훅으로. `plain`이면 지금 방식(`chat.plan` + `hachiware.translate`, remark 를 번역 뒤에 한 칸 띄어 붙임)
- 스레드에서는 `log.info`를 하나도 남기지 않는다. 실패는 `log.warning("1:1 스레드 답을 못 보냄: %s", type(e).__name__)`처럼 종류만
- 스레드 메시지와 웹훅 모두 멘션 알림을 막는다 (`allowed_mentions=discord.AllowedMentions.none()`, 웹훅은 `execute_webhook`이 이미 `parse: []`인지 확인)

- [ ] **Step 1: Write the failing tests** (가짜 채널·메시지 객체로 `answer`를 부름. `caplog`로 로그 확인)

```python
def test_thread_answers_go_through_dialog_and_log_nothing(caplog):
    # 스레드 채팅 "오늘 점심 뭐야?" → 보낸 우사기 소리 1개 이상, 웹훅 URL 에 thread_id, caplog 에 "usagi" 로거 INFO 없음, 채팅 글·이름 없음
def test_public_channel_is_unchanged(caplog):            # 공개 채널 채팅 → 지금처럼 "답함:" 로그가 남음
def test_thread_messages_never_ping():                   # 보낸 메시지의 allowed_mentions 가 none
def test_thread_failure_logs_only_the_kind(caplog):      # respond 가 예외 → warning 한 줄, 글·이름 없음
```

- [ ] **Step 2: Run**: `PYTEST_BOT` → FAIL
- [ ] **Step 3: Implement** (위 규칙)
- [ ] **Step 4: Run**: `PYTEST_BOT` PASS, `PYTEST` 전체 PASS
- [ ] **Step 5: Commit**: `git commit -m "우사기 봇: 1:1 스레드는 대화 기억으로 답하고 로그를 남기지 않음"`

---

### Task 7: 등급 — `/우사기`·`/기억`은 직장인 이상, 강등되면 스레드에서 내보내기

**Files:**
- Modify: `src/lunchbot/members.py` (`NEEDS`), `src/commands.py` (`_int`, `DEFINITIONS`, `USAGE`, `RUN`, `_set_rank`, `_remove`, 새 `_memory_show`, `_memory_forget`, `_leave_thread_job`), `src/lunchbot/discord.py` (`remove_thread_member`), `src/lunchbot/hachiware.py` (`NOTICES`에 `memory_*` 키)
- Test: `tests/test_commands.py`, `tests/test_memory_commands.py`

**Interfaces:**
- Consumes: Task 2 `memory.load/forget/forget_taught`
- Produces:
  - `members.NEEDS["우사기"] = WORKER`, `NEEDS["기억 보기"] = WORKER`, `NEEDS["기억 지우기"] = WORKER`
  - `commands._int(name, description, low, high, required: bool = True) -> dict`
  - `DEFINITIONS`에 `{"name": "기억", …, "options": [_sub("보기", …), _sub("지우기", …, _int("번호", "지울 가르친 것 번호 (비우면 전부 지워요)", 1, 50, required=False))]}`
  - `discord.remove_thread_member(bot_token: str, thread_id: str, user_id: str) -> None` (`DELETE /channels/{thread}/thread-members/{user}`)
  - `hachiware.NOTICES`: `memory_shown`, `memory_none`, `memory_forgot`, `memory_forgot_one`, `memory_bad_number` (모두 비트 틀)
  - `/기억 보기` = 나만 보기(`private=True`, `always=True`). info 에 기억하는 것(마지막 대화 날, 최근 기분, 자주 하는 이야기, 좋아함·싫어함, 최근 음식)과 가르친 것(번호. 낱말 → 뜻/답) 목록
  - `/기억 지우기` = 나만 보기. 번호가 없으면 `memory.forget`, 있으면 `memory.forget_taught`, 없는 번호면 `memory_bad_number`
  - `_set_rank`/`_remove`: 새 등급이 `WORKER` 아래면 `later`에 `_leave_thread_job(guild_id, target.id)` 더함 — `threads/{서버}.json`에 그 사람 스레드가 있으면 `remove_thread_member`, 404 는 넘어감, 다른 실패는 `log.warning`(id 없이). 공개 답에는 스레드 이야기를 하지 않음. 기억·스레드 기록은 그대로

- [ ] **Step 1: Write the failing tests**

```python
def test_usagi_and_memory_need_worker(bot):              # 행인 walk 의 /우사기, /기억 보기 → 거절(rank_low), 직장인 work 는 됨
def test_commands_split_by_rank_still_holds():           # 기존 "맨 앞 명령 하나 아래 같은 등급" 테스트가 /기억 포함해 통과
def test_help_lists_memory_for_workers(bot):             # 직장인 /도움 에 "/기억 보기", 행인 /도움 에 "/우사기" 없음
def test_memory_show_is_private_and_lists(bot, vault_tmp):   # 기억 저장 뒤 /기억 보기 → flags 64, "라멘" 과 가르친 것 "1." 이 보임, 웹훅으로는 안 감
def test_memory_forget_all_and_one(bot, vault_tmp):      # /기억 지우기 번호 1 → 첫째만 지움 / 번호 9 → memory_bad_number / 번호 없음 → 파일 없음
def test_demotion_removes_from_thread_but_keeps_records(bot, vault_tmp):
    # work 의 스레드 기록 + 기억 → /멤버강등 work 행인 → 응답 뒤 remove_thread_member(token, 그 스레드, work), 기억·threads 기록 그대로, 공개 답에 "스레드" 없음
def test_member_removed_also_leaves_thread(bot):         # /멤버삭제 → remove_thread_member 호출
def test_promotion_does_not_remove(bot):                 # 행인→직장인 승급 → remove_thread_member 안 부름
```

- [ ] **Step 2: Run**: `PYTEST tests/test_commands.py tests/test_memory_commands.py` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run**: PASS, `PYTEST` 전체 PASS
- [ ] **Step 5: Commit**: `git commit -m "/우사기·/기억은 직장인 갑옷씨부터, 강등되면 1:1 스레드에서 내보냄"`

---

### Task 8: 나간 사람 기록 지우기

**Files:**
- Create: `src/lunchbot/departed.py`
- Modify: `src/lunchbot/discord.py` (`delete_channel`), `src/lunchbot/hachiware.py` (`forget(user_id) -> bool`: 개인 번역 설정에서 그 사람 빼기), `src/commands.py` (`_kick` 뒤 `departed.forget_person`), `scripts/serve_local.py` (정리 반복)
- Test: `tests/test_departed.py`

**Interfaces:**
- Consumes: Task 2 `memory.forget`, `memory.strays`, `storage.delete`; `birthdays.remove`; `members.load/save`; `storage.threads_key`
- Produces:
  - `discord.delete_channel(bot_token: str, channel_id: str, reason: str) -> None` (`DELETE /channels/{id}`, 감사 로그 까닭)
  - `departed.forget_person(guild_id: str, user_id: str) -> None`: 기억 파일, 생일, 개인 번역 설정, 갑옷씨 등급(`members`), 스레드 기록을 지우고 그 1:1 스레드를 디스코드에서 지운다 (404 넘어감, 403 은 `log.warning("1:1 스레드를 못 지움: 스레드 관리 권한을 확인해 주세요")` 뒤 나머지는 계속)
  - `departed.sweep(guild_id: str, member_ids: set[str], owner_id: str | None) -> int`: 생일·개인 번역 설정·등급·스레드 기록에 있는데 `member_ids`에 없는 사람마다 `forget_person`, `memory.strays`는 `storage.delete`. 지금 서버에 있지만 등급이 `WORKER` 아래인데 스레드 기록이 있는 사람은 `remove_thread_member`(404 넘어감). 지운 사람 수를 돌려줌
  - `departed.SWEEP_S = 600`
  - `serve_local.py`: 시작 30초 뒤부터 `SWEEP_S`마다 데몬 스레드에서 `line.ask(sweep_now)` — `sweep_now`는 `discord.get_channel(USAGI_CHANNEL_ID)["guild_id"]`, `discord.list_members`, `commands._owner`로 `departed.sweep`를 부르고 `log.info("나간 사람 %d명의 기록을 지웠어요", n)` (n>0 일 때만, id·이름 없이). 실패는 `log.warning`(종류만)
  - `/추방` 성공 뒤 같은 처리 안에서 `departed.forget_person` (줄 안이라 다른 입력과 겹치지 않음)
  - 지우는 쪽은 모두 버튼 서버의 줄 안이다. 우사기 봇은 기억 파일만 쓴다 (나간 사람은 채팅할 수 없으므로 겹치지 않음)
  - **설계와 다른 점 (의도함):** 설계 §10은 우사기 봇의 `on_member_remove` + 하루 한 번 확인이었다. 그러면 우사기 봇이 생일·등급·스레드·번역 설정 파일을 지우다가 버튼 서버의 쓰기와 겹칠 수 있다 (설계가 빌더에게 맡긴 문제). 그래서 지우기를 모두 버튼 서버의 처리 줄 안에서 10분마다 확인으로 한다. 나간 뒤 길어야 10분 안에 지워지고, `/추방`은 바로 지운다

- [ ] **Step 1: Write the failing tests**

```python
def test_forget_person_removes_every_per_person_record(aws, vault_tmp, monkeypatch):
    # gone 의 기억·생일·개인 번역·등급·스레드 기록 + stay 의 같은 것들 → forget_person("g","gone")
    # gone 것은 모두 없음, stay 것은 그대로, delete_channel(그 스레드) 한 번
def test_votes_and_games_are_kept(aws):                  # 투표 결과·게임 점수에 gone 이 있어도 그대로
def test_missing_thread_and_no_permission(aws, monkeypatch):   # delete_channel 404 → 넘어감, 403 → warning 뒤 나머지 기록은 지워짐
def test_sweep_finds_people_who_already_left(aws, vault_tmp):  # member_ids={"stay"} → gone 정리, 돌려준 수 1, 해시 이름 기억 파일도 지움
def test_sweep_removes_low_ranks_from_threads(aws, monkeypatch):   # 행인 walk 의 스레드 기록 → remove_thread_member 한 번, 기록은 그대로
def test_kick_forgets_right_away(bot, vault_tmp):        # /추방 성공 → gone 기록 없음, 실패(403) → 그대로
def test_sweep_logs_no_ids(aws, caplog):                 # 로그에 사용자 id 가 없음
```

- [ ] **Step 2: Run**: `PYTEST tests/test_departed.py` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run**: PASS, `PYTEST` 전체 PASS, `scripts/serve_local.py`가 뜨는지 `check_serve_commands.py`(스크래치 검증)로 확인
- [ ] **Step 5: Commit**: `git commit -m "서버를 나가거나 추방된 사람의 사람별 기록과 1:1 스레드 지우기"`

---

### Task 9: 도커 볼륨, 명령 등록, 문서, 마무리 확인

**Files:**
- Modify: `compose.yaml`, `README.md`, `DESIGN.md`
- Test: 전체

- [ ] **Step 1: compose** — 맨 아래 `volumes: {usagi-vault: {}}`, `interaction`·`usagi`에 `- usagi-vault:/vault` 와 `VAULT_PATH: /vault/master.key`. 확인: `docker compose config | grep -n "usagi-vault\|VAULT_PATH"` 에 두 서비스가 보임
- [ ] **Step 2: 띄우기** — `docker compose up -d --build interaction usagi` 뒤 `docker compose logs --since 1m interaction usagi`에 오류 없음, `docker compose exec usagi ls -l /vault` 에 `master.key`(권한 `-rw-------`) 하나, 두 컨테이너의 `sha256sum /vault/master.key` 가 같음 (키 내용은 출력하지 않음)
- [ ] **Step 3: 명령 등록** — `uv run --python 3.12 --with boto3 scripts/register_commands.py` → `/기억` 포함 14개
- [ ] **Step 4: 문서** — README: 1:1 대화(직장인 이상, 물음 답하기·이어 묻기·기억·가르치기, 처음 안내, 번역이 꺼지면 기억 안 함), `/기억` 명령 표, 서버 설정 권한 표(`/우사기`를 직장인 줄로, `/기억` 직장인), 유출 방지(원문 없음, 사람별 암호화, 키는 도커 볼륨 `usagi-vault` — 잃으면 기억 복구 불가, 스레드 로그 없음, 서버 주인·스레드 관리 권한자는 디스코드에서 스레드를 볼 수 있음), 나간 사람 정리(10분마다, 1:1 스레드도 지움, 스레드 관리 권한), S3 구조 표에 `memories/{서버 id}/{해시}.json`. DESIGN.md: R24 요구사항, §7에 1:1 대화 기억, 파일 구성(vault·memory·talk·answers·dialog·departed), 알려진 문제 K8(기억 파일을 우사기 봇과 버튼 서버가 함께 쓰므로 `/기억 지우기`와 그 사람의 채팅이 같은 순간이면 지운 기억이 되살아날 수 있음, 드묾), 테스트 수
- [ ] **Step 5: 전체 확인** — `PYTEST`, `PYTEST_BOT`, 스크래치 검증 두 개(`check_serve_commands.py`, `check_usagi_bot.py`) 모두 PASS
- [ ] **Step 6: Commit**: `git commit -m "1:1 대화 기억: 도커 볼륨, 명령 등록, 문서"` (push 안 함). 사용자에게 알릴 것: 서버 설정 → 연동에서 `/기억`을 직장인 이상으로
