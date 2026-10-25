"""/게임 (이미지 랜덤 주제 게임)과 /생일 을 디스코드 상호작용으로 돌려 본다.

게임 안의 우사기 말은 번역 설정과 상관없이 하치와레가 늘 번역한다. 답 받기, 사회자 답 보기, 생일 저장 확인은
그 사람에게만 보인다. 생일 축하는 정해 둔 우사기 소리와 하치와레 번역을 한 세트로 보낸다.
"""
import json

import pytest

from lunchbot import birthdays, game, hachiware, members
import commands
import interaction
import recommend
from test_flow import aws, signed_event  # noqa: F401 (aws 는 fixture)

GUILD, HERE = "g1", "c-game"
HOOK = "https://hook/game"
NAMES = {"own": "주인", "a": "민지", "b": "현우", "c": "지호", "x": "손님"}
STRING, INTEGER = 3, 4


def cmd(path, actor, **opts):
    words = path.split()
    leaf = [{"type": INTEGER if isinstance(v, int) else STRING, "name": k, "value": v} for k, v in opts.items()]
    for w in reversed(words[1:]):
        leaf = [{"type": 1, "name": w, "options": leaf}]
    return {"type": 2, "id": "i", "token": "itok", "application_id": "app", "guild_id": GUILD, "channel_id": HERE,
            "member": {"user": {"id": actor, "username": actor, "global_name": NAMES[actor]}},
            "data": {"name": words[0], "type": 1, "options": leaf}}


def click(custom_id, actor, values=None, message_id="setup-msg"):
    data = {"custom_id": custom_id, "component_type": 5 if values is not None else 2}
    if values is not None:
        data["values"] = values
        data["resolved"] = {"users": {v: {"id": v, "username": v, "global_name": NAMES[v], "bot": False} for v in values},
                            "members": {v: {"nick": None} for v in values}}
    return {"type": 3, "id": "i", "token": "itok", "application_id": "app", "guild_id": GUILD, "channel_id": HERE,
            "member": {"user": {"id": actor, "username": actor, "global_name": NAMES[actor]}},
            "message": {"id": message_id}, "data": data}


@pytest.fixture
def table(aws, monkeypatch):
    t = {"hooked": [], "posted": [], "edited": [], "followed": []}
    monkeypatch.setattr(hachiware, "hooks", lambda: {HERE: HOOK})
    monkeypatch.setattr(commands.discord, "guild_owner", lambda token, guild_id: "own")
    monkeypatch.setattr(commands.discord, "execute_webhook", lambda url, text: t["hooked"].append((url, text)) or {})
    monkeypatch.setattr(commands.discord, "followup", lambda app, token, text, ephemeral=True:
                        t["followed"].append((text, ephemeral)) or {})

    def send(token, channel_id, payload):
        t["posted"].append((channel_id, payload))
        return {"id": f"m{len(t['posted'])}"}

    monkeypatch.setattr(recommend.discord, "send_message", send)
    monkeypatch.setattr(commands.discord, "edit_message",
                        lambda token, channel_id, message_id, payload: t["edited"].append((message_id, payload)))
    monkeypatch.setattr(commands.discord, "list_members", lambda token, guild_id: [
        {"user": {"id": u, "username": u, "global_name": NAMES[u]}, "nick": None} for u in ("own", "a", "b", "c")])
    hachiware.turn(False, "테스트")  # 번역은 꺼 둠: 게임에서는 그래도 하치와레가 말해야 함

    def run(event):
        return json.loads(interaction.handler(signed_event(event), None)["body"])

    t["run"] = run
    return t


def state():
    return commands.storage.get_json(commands.storage.game_key(HERE))


def components(payload):
    for row in payload.get("components", []):
        yield from row.get("components", [])


def test_setup_pick_players_and_start(table):
    run = table["run"]
    body = run(cmd("게임 시작", "own", 주제="첫인상"))
    assert body["type"] == 4 and "flags" not in body["data"] and "첫인상" in body["data"]["content"]
    ids = {c["custom_id"] for c in components(body["data"])}
    assert {"game:pick", "game:all", "game:start", "game:cancel"} <= ids
    assert any(c["type"] == 5 and c["max_values"] == 25 for c in components(body["data"]))  # 사람 선택칸
    assert table["hooked"] and table["hooked"][-1][0] == HOOK  # 번역이 꺼져 있어도 게임에선 하치와레가 말함

    refused = run(click("game:pick", "a", values=["a", "b"]))
    assert refused["data"]["flags"] == 64  # 시작한 사람만 고를 수 있음 (누른 사람에게만 안내)
    body = run(click("game:pick", "own", values=["own", "a", "b", "c"]))
    assert body["type"] == 7 and all(NAMES[p] in body["data"]["content"] for p in ("own", "a", "b", "c"))
    assert state()["players"] == ["own", "a", "b", "c"]

    body = run(click("game:start", "own"))
    assert body["type"] == 7 and state()["status"] == "playing" and state()["round"] == 1
    round_msg = table["posted"][-1][1]  # 응답 뒤에 1라운드 메시지
    g = state()
    assert f"<@{g['it']}>" in round_msg["content"] and f"<@{g['host']}>" in round_msg["content"]
    assert set(round_msg["allowed_mentions"]["users"]) == {g["it"], g["host"]}  # 술래와 사회자를 부름
    assert [c["custom_id"] for c in components(round_msg)] == ["game:reveal"]
    assert table["hooked"][-1][0] == HOOK and "1라운드" in table["hooked"][-1][1]


def test_server_wide_players(table):
    run = table["run"]
    run(cmd("게임 시작", "own", 주제="첫인상"))
    body = run(click("game:all", "own"))
    assert body["type"] == 7 and state()["players"] == ["own", "a", "b", "c"]


def play_round(table):
    g = state()
    run = table["run"]
    it, host = g["it"], g["host"]
    refused = run(cmd("게임 답", it, 내용="나는 술래"))
    assert refused["data"]["flags"] == 64 and it not in state()["answers"]
    for p in game.answerers(g):
        body = run(cmd("게임 답", p, 내용=f"{NAMES[p]}의 생각"))
        assert body["data"]["flags"] == 64 and "하치와레" in body["data"]["content"]  # 받았다는 말은 낸 사람에게만
    assert table["edited"][-1][1]["content"].count(f"답 {len(game.answerers(g))}/{len(game.answerers(g))}") == 1
    ping = table["posted"][-1][1]  # 다 모이면 사회자를 부름
    assert f"<@{host}>" in ping["content"] and ping["allowed_mentions"]["users"] == [host]

    other = run(click("game:reveal", it, message_id="round-msg"))
    assert other["data"]["flags"] == 64 and "생각" not in other["data"]["content"]  # 사회자가 아니면 못 봄
    shown = run(click("game:reveal", host, message_id="round-msg"))
    assert shown["data"]["flags"] == 64  # 사회자에게만
    for p in game.answerers(g):
        assert f"{NAMES[p]}의 생각" in shown["data"]["content"] and f"— {NAMES[p]}" in shown["data"]["content"]
    return it, host


def test_full_game_with_scores(table):
    run = table["run"]
    run(cmd("게임 시작", "own", 주제="첫인상"))
    run(click("game:pick", "own", values=["own", "a", "b", "c"]))
    run(click("game:start", "own"))
    its = []
    for n in range(4):
        it, host = play_round(table)
        its.append(it)
        refused = run(cmd("게임 결과", it, 맞힌수=2))
        assert "flags" in refused["data"] or "\n" in refused["data"]["content"]  # 사회자만 결과를 보냄
        body = run(cmd("게임 결과", host, 맞힌수=2))
        assert "점수" in body["data"]["content"] and f"{NAMES[it]} 2점" in body["data"]["content"]
    assert sorted(its) == ["a", "b", "c", "own"] and state()["status"] == "done"
    final = table["posted"][-1][1]["content"]
    assert "게임 끝" in final and all(f"{NAMES[p]} 2점" in final for p in its)


def test_scoreboard_and_end(table):
    run = table["run"]
    run(cmd("게임 시작", "a", 주제="첫인상"))
    run(click("game:pick", "a", values=["own", "a", "b", "c"]))
    run(click("game:start", "a"))
    body = run(cmd("게임 점수", "x"))
    assert "점수" in body["data"]["content"]
    refused = run(cmd("게임 끝", "b"))  # 시작한 사람도 대장도 아님
    assert state()["status"] == "playing"
    run(cmd("게임 끝", "own"))  # 서버 주인은 대장
    assert state()["status"] == "done"
    body = run(cmd("게임 시작", "b", 주제="두번째"))  # 끝났으면 새로 시작할 수 있음
    assert state()["topic"] == "두번째"


def test_birthday_button_and_modal(table):
    run = table["run"]
    modal = run(click("bday:open", "a", message_id="welcome"))
    assert modal["type"] == 9 and modal["data"]["custom_id"] == "bday:save"
    inputs = [c for row in modal["data"]["components"] for c in row["components"]]
    assert [i["custom_id"] for i in inputs] == ["month", "day"]
    assert any("축하" in (i.get("placeholder") or "") for i in inputs)  # 입력하면 알림이 간다고 미리 알림
    submit = {"type": 5, "id": "i", "token": "itok", "application_id": "app", "guild_id": GUILD, "channel_id": HERE,
              "member": {"user": {"id": "a", "username": "a", "global_name": "민지"}},
              "data": {"custom_id": "bday:save", "components": [
                  {"type": 1, "components": [{"type": 4, "custom_id": "month", "value": "3"}]},
                  {"type": 1, "components": [{"type": 4, "custom_id": "day", "value": "05"}]}]}}
    body = run(submit)
    assert body["data"]["flags"] == 64 and "3월 5일" in body["data"]["content"]  # 넣은 사람에게만
    assert birthdays.get(GUILD, "a") == (3, 5)
    submit["data"]["components"][1]["components"][0]["value"] = "31"
    submit["data"]["components"][0]["components"][0]["value"] = "2"
    body = run(submit)
    assert body["data"]["flags"] == 64 and birthdays.get(GUILD, "a") == (3, 5)  # 2월 31일은 안 됨


def test_birthday_commands(table):
    run = table["run"]
    body = run(cmd("생일 등록", "b", 월=12, 일=24))
    assert body["data"]["flags"] == 64 and "12월 24일" in body["data"]["content"]
    assert birthdays.get(GUILD, "b") == (12, 24)
    body = run(cmd("생일 지우기", "b"))
    assert body["data"]["flags"] == 64 and birthdays.get(GUILD, "b") is None


def test_birthday_greeting_is_a_fixed_pair():
    s1, s2 = hachiware.birthday_script(), hachiware.birthday_script()
    assert s1 == s2 and len(s1.sound.split()) == len(s1.parts) >= 2 and "생일" in s1.text
    assert members.NEEDS["생일 등록"] == members.NEEDS["게임 시작"] == 0


def answer_all(table):
    for p in game.answerers(state()):
        table["run"](cmd("게임 답", p, 내용="생각"))


def respond(event):
    """로컬 버튼 서버처럼 응답만 먼저 하고, 응답 뒤 할 일은 돌려받음 (그 사이에 다른 입력이 올 수 있음)."""
    response, later = interaction.respond(signed_event(event))
    return json.loads(response["body"]), later


def test_next_round_is_not_posted_when_the_game_ended_in_between(table):
    run = table["run"]
    run(cmd("게임 시작", "own", 주제="첫인상"))
    run(click("game:pick", "own", values=["own", "a", "b", "c"]))
    run(click("game:start", "own"))
    answer_all(table)
    _, later = respond(cmd("게임 결과", state()["host"], 맞힌수=1))
    run(cmd("게임 끝", "own"))  # 다음 라운드 메시지가 올라가기 전에 끝냄
    posted = len(table["posted"])
    interaction.run_later(later)
    assert len(table["posted"]) == posted  # 끝난 게임의 라운드는 올리지 않음


def test_final_board_is_of_the_finished_game_even_if_a_new_one_started(table):
    run = table["run"]
    run(cmd("게임 시작", "own", 주제="첫인상"))
    run(click("game:pick", "own", values=["own", "a", "b"]))
    run(click("game:start", "own"))
    for _ in range(2):
        answer_all(table)
        run(cmd("게임 결과", state()["host"], 맞힌수=1))
    answer_all(table)
    _, later = respond(cmd("게임 결과", state()["host"], 맞힌수=1))  # 마지막 라운드
    run(cmd("게임 시작", "a", 주제="두번째"))  # 최종 점수판이 올라가기 전에 새 게임
    interaction.run_later(later)
    final = table["posted"][-1][1]["content"]
    assert "게임 끝" in final and "첫인상" in final and "두번째" not in final
