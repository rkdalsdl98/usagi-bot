"""갑옷씨 멤버 등급 규칙: 행인 갑옷씨 → 직장인 갑옷씨 → 대장 갑옷씨.

자기 등급과 그 아래 등급의 명령을 쓸 수 있다. 승급은 자기보다 낮은 멤버를 자기 등급까지,
강등·삭제·추방은 자기보다 낮은 사람에게만. 서버 주인은 항상 대장이고 다른 대장보다도 높다.
"""
from lunchbot import members
from lunchbot.members import CAPTAIN, WALKER, WORKER, Person

OWNER = Person("own", "주인", CAPTAIN, owner=True)
CAP = Person("cap", "대장", CAPTAIN)
CAP2 = Person("cap2", "대장2", CAPTAIN)
WORK = Person("work", "직장인", WORKER)
WORK2 = Person("work2", "직장인2", WORKER)
WALK = Person("walk", "행인", WALKER)
NOBODY = Person("x", "손님")
BOT = Person("b", "봇", bot=True)


def test_rank_names_in_order():
    assert [members.RANKS[r] for r in (WALKER, WORKER, CAPTAIN)] == ["행인 갑옷씨", "직장인 갑옷씨", "대장 갑옷씨"]


def test_who_can_use_which_command():
    everyone = ["도움", "점심 추천", "저녁 추천", "하치와레 번역 켜기", "하치와레 번역 끄기", "생일 등록", "생일 지우기",
                "게임 시작", "게임 답", "게임 결과", "게임 점수", "게임 끝"]
    assert members.allowed(0) == everyone
    assert members.allowed(WALKER) == everyone + ["멤버추가"]
    # /우사기(1:1 스레드)와 /기억 은 직장인 갑옷씨부터
    assert members.allowed(WORKER) == members.allowed(CAPTAIN) == ["도움", "우사기", "기억 보기", "기억 지우기"] + everyone[1:] + [
        "멤버추가", "멤버승급", "멤버강등", "멤버삭제", "추방", "전체번역 켜기", "전체번역 끄기"]
    assert members.check("우사기", WALK) == members.check("기억 보기", NOBODY) == "rank_low"
    assert members.check("전체번역 켜기", WALK) == "rank_low"  # 서버 전체 번역은 직장인 갑옷씨부터
    for command in everyone:
        assert members.check(command, NOBODY) is None
    assert members.check("멤버추가", NOBODY, Person("y")) == "rank_low"
    assert members.check("추방", WALK, NOBODY) == "rank_low"


def test_server_owner_outranks_other_captains():
    assert members.outranks(OWNER, CAP) and not members.outranks(CAP, OWNER)
    assert not members.outranks(CAP, CAP2) and members.outranks(CAP, WORK) and members.outranks(WALK, NOBODY)


def test_add_member():
    assert members.check("멤버추가", WALK, NOBODY) is None
    assert members.check("멤버추가", WALK, WORK) == "already"
    assert members.check("멤버추가", WORK, OWNER) == "already"  # 주인은 이미 대장
    assert members.check("멤버추가", WALK, BOT) == "bot"
    assert members.check("멤버추가", WALK, WALK) == "self"


def test_promote_up_to_own_rank():
    assert members.check("멤버승급", WORK, WALK, WORKER) is None  # 직장인은 행인을 직장인까지
    assert members.check("멤버승급", WORK, WALK, CAPTAIN) == "rank_too_high"
    assert members.check("멤버승급", WORK, WORK2, WORKER) == "not_lower"
    assert members.check("멤버승급", CAP, WORK, CAPTAIN) is None  # 대장은 대장까지
    assert members.check("멤버승급", CAP, WALK, WALKER) == "not_up"
    assert members.check("멤버승급", CAP, NOBODY, WALKER) == "not_member"
    assert members.check("멤버승급", CAP, OWNER, CAPTAIN) == "not_lower"
    assert members.check("멤버승급", WALK, NOBODY, WALKER) == "rank_low"
    assert members.check("멤버승급", CAP, WALK, 9) == "bad_rank"


def test_demote_only_lower_members():
    assert members.check("멤버강등", CAP, WORK, WALKER) is None
    assert members.check("멤버강등", WORK, WALK, WALKER) == "not_down"  # 행인 아래 등급은 없음
    assert members.check("멤버강등", CAP, CAP2, WORKER) == "not_lower"
    assert members.check("멤버강등", OWNER, CAP, WORKER) is None  # 주인은 다른 대장도 내릴 수 있음
    assert members.check("멤버강등", CAP, OWNER, WORKER) == "owner"
    assert members.check("멤버강등", CAP, WORK, CAPTAIN) == "not_down"


def test_remove_member():
    assert members.check("멤버삭제", WORK, WALK) is None
    assert members.check("멤버삭제", WORK, WORK2) == "not_lower"
    assert members.check("멤버삭제", WORK, NOBODY) == "not_member"
    assert members.check("멤버삭제", CAP, OWNER) == "owner"
    assert members.check("멤버삭제", WORK, WORK) == "self"


def test_kick():
    assert members.check("추방", WORK, NOBODY) is None  # 멤버가 아닌 사람도 내보낼 수 있음
    assert members.check("추방", WORK, WALK) is None
    assert members.check("추방", WORK, WORK2) == "not_lower"
    assert members.check("추방", OWNER, CAP) is None
    assert members.check("추방", CAP, OWNER) == "owner"
    assert members.check("추방", CAP, BOT) == "bot"
    assert members.check("추방", WORK, WORK) == "self"


def test_person_reads_the_roster():
    roster = {"walk": {"rank": WALKER}, "cap": {"rank": CAPTAIN}}
    assert members.person("walk", "행인", roster, owner_id="own").level == WALKER
    assert members.person("x", "손님", roster, owner_id="own").level == 0
    boss = members.person("own", "주인", roster, owner_id="own")
    assert boss.level == CAPTAIN and boss.owner
    assert members.person("b", "봇", roster, owner_id="own", bot=True).bot
