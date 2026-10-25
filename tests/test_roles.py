"""갑옷씨 등급을 디스코드 역할로: 행인·직장인·대장 갑옷씨 역할을 만들어 두고, 한 사람은 자기 등급 역할 하나만 갖는다.

역할이 있으면 서버 설정 → 연동에서 명령마다 보일 역할을 정할 수 있다 (슬래시 명령 창이 등급에 맞게 보임).
"""
import pytest

from lunchbot import members, roles, storage
from test_flow import aws  # noqa: F401 (aws 는 fixture)


@pytest.fixture
def guild(aws, monkeypatch):
    state = {"roles": [{"id": "g1", "name": "@everyone", "position": 0}, {"id": "r-bot", "name": "daggle", "position": 1}],
             "made": [], "added": [], "removed": [], "moved": []}

    def create(token, guild_id, name, color):  # 디스코드처럼 새 역할은 맨 아래(1)에 들어가고 나머지가 한 칸씩 올라감
        rid = f"r{len(state['made']) + 1}"
        state["made"].append((name, color))
        for r in state["roles"]:
            if r["position"] >= 1:
                r["position"] += 1
        state["roles"].append({"id": rid, "name": name, "position": 1})
        return {"id": rid, "name": name}

    def move(token, guild_id, positions):
        state["moved"].append(dict(positions))
        for r in state["roles"]:
            r["position"] = positions.get(r["id"], r["position"])

    monkeypatch.setattr(roles.discord, "set_role_positions", move)

    monkeypatch.setattr(roles.discord, "guild_roles", lambda token, guild_id: [dict(r) for r in state["roles"]])
    monkeypatch.setattr(roles.discord, "create_role", create)
    monkeypatch.setattr(roles.discord, "add_role",
                        lambda token, guild_id, user_id, role_id, reason: state["added"].append((user_id, role_id)))
    monkeypatch.setattr(roles.discord, "remove_role",
                        lambda token, guild_id, user_id, role_id, reason: state["removed"].append((user_id, role_id)))
    return state


def test_ensure_makes_the_three_rank_roles_once(guild):
    made = roles.ensure("g1")
    # 대장부터 만든다: 자리 값이 같으면 디스코드는 먼저 만든 역할을 위에 보여 줌
    assert [name for name, _ in guild["made"]] == ["대장 갑옷씨", "직장인 갑옷씨", "행인 갑옷씨"]
    assert set(made) == {members.WALKER, members.WORKER, members.CAPTAIN}
    assert storage.get_json(storage.roles_key("g1"))["roles"] == {str(k): v for k, v in made.items()}
    assert roles.ensure("g1") == made and len(guild["made"]) == 3  # 다시 불러도 새로 만들지 않음
    pos = {r["id"]: r["position"] for r in guild["roles"]}
    # 대장 > 직장인 > 행인 순서이고, 셋 다 봇 역할보다 아래
    assert pos["r-bot"] > pos[made[members.CAPTAIN]] > pos[made[members.WORKER]] > pos[made[members.WALKER]] > 0
    assert len(guild["moved"]) <= 1  # 순서가 맞으면 다시 옮기지 않음


def test_roles_on_the_same_position_are_not_moved(guild):
    # 봇 역할이 낮으면 디스코드가 새 역할을 모두 같은 자리에 둔다. 그때는 옮길 자리가 없어서 건드리지 않음
    guild["roles"] += [{"id": i, "name": n, "position": 1} for i, n in
                       (("c", "대장 갑옷씨"), ("w", "직장인 갑옷씨"), ("p", "행인 갑옷씨"))]
    roles.ensure("g1")
    assert guild["moved"] == []


def test_ensure_reuses_roles_by_name_or_remakes_deleted_ones(guild):
    guild["roles"][1]["position"] = 2
    guild["roles"].append({"id": "old-walker", "name": "행인 갑옷씨", "position": 1})  # 이미 같은 이름의 역할이 있음
    made = roles.ensure("g1")
    assert made[members.WALKER] == "old-walker" and len(guild["made"]) == 2
    guild["roles"] = [r for r in guild["roles"] if r["id"] != made[members.CAPTAIN]]  # 누가 대장 역할을 지움
    again = roles.ensure("g1")
    assert again[members.CAPTAIN] != made[members.CAPTAIN] and len(guild["made"]) == 3


def test_sync_gives_only_your_rank_role(guild):
    made = roles.ensure("g1")
    roles.sync("g1", "u1", members.WORKER)
    assert guild["added"] == [("u1", made[members.WORKER])]
    assert set(guild["removed"]) == {("u1", made[members.WALKER]), ("u1", made[members.CAPTAIN])}
    guild["added"].clear(), guild["removed"].clear()
    roles.sync("g1", "u1", 0)  # 멤버에서 빠짐 → 갑옷씨 역할을 모두 뗌
    assert guild["added"] == [] and len(guild["removed"]) == 3
