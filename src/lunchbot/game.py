"""이미지 랜덤 주제 게임의 진행 상태 (디스코드와 상관없는 규칙). 디스코드 쪽은 commands.py 가 맡습니다.

  1. /게임 시작 [주제] 로 만들고(setup), 시작한 사람이 참가자를 고른 뒤(사람 선택 또는 서버 전체) 시작합니다
  2. 라운드마다 아직 술래가 안 된 사람 중 한 명이 술래(it), 술래를 뺀 사람 중 한 명이 사회자(host)가 됩니다
  3. 술래를 뺀 참가자가 주제에 맞춰 술래에 대한 생각을 냅니다 (다시 내면 바뀜, 다른 참가자에게는 안 보임)
  4. 사회자만 답과 쓴 사람을 짝지어 봅니다 (순서는 섞음). 사회자가 읽고 술래가 누가 썼는지 맞힙니다
  5. 사회자가 술래가 맞힌 수를 알려 주면 술래 점수에 더하고 다음 라운드로 갑니다
  6. 모두 한 번씩 술래가 되면 끝납니다

상태는 dict 라 그대로 JSON 으로 저장합니다 (games/{채널 id}.json). 할 수 없는 일은 GameError(까닭)로 알립니다.
"""
MIN_PLAYERS = 3  # 술래 + 사회자 + 답할 사람 한 명 이상


class GameError(Exception):
    """까닭: not_running, not_starter, too_few, not_player, is_it, not_host, bad_count"""


def new(topic: str, starter: str) -> dict:
    return {"topic": topic, "starter": starter, "status": "setup", "players": [], "names": {}, "round": 0,
            "it": None, "host": None, "done": [], "answers": {}, "scores": {}}


def set_players(g: dict, players: list, names: dict) -> None:
    if g["status"] != "setup":
        raise GameError("not_running")
    g["players"] = list(dict.fromkeys(players))  # 순서는 두고 겹친 사람만 뺌
    g["names"] = {p: names.get(p, p) for p in g["players"]}


def start(g: dict, user: str, rng) -> None:
    if g["status"] != "setup":
        raise GameError("not_running")
    if user != g["starter"]:
        raise GameError("not_starter")
    if len(g["players"]) < MIN_PLAYERS:
        raise GameError("too_few")
    g["status"] = "playing"
    g["scores"] = {p: 0 for p in g["players"]}
    _next_round(g, rng)


def _next_round(g: dict, rng) -> None:
    left = [p for p in g["players"] if p not in g["done"]]
    if not left:
        g["status"], g["it"], g["host"] = "done", None, None
        return
    g["round"] += 1
    g["it"] = rng.choice(left)
    g["host"] = rng.choice([p for p in g["players"] if p != g["it"]])
    g["answers"] = {}


def _playing(g: dict) -> None:
    if g["status"] != "playing":
        raise GameError("not_running")


def answer(g: dict, user: str, text: str) -> None:
    _playing(g)
    if user not in g["players"]:
        raise GameError("not_player")
    if user == g["it"]:
        raise GameError("is_it")
    g["answers"][user] = text


def answerers(g: dict) -> list:
    """이번 라운드에 답할 사람 (술래 빼고 모두, 사회자 포함)."""
    return [p for p in g["players"] if p != g["it"]]


def progress(g: dict) -> tuple[int, int]:
    """(답 낸 사람 수, 답할 사람 수)."""
    return len(g["answers"]), len(answerers(g))


def reveal(g: dict, user: str, rng) -> tuple[list, list]:
    """사회자만: ([(답, 쓴 사람), …] 섞은 순서, 아직 안 낸 사람)."""
    _playing(g)
    if user != g["host"]:
        raise GameError("not_host")
    shown = [(text, who) for who, text in g["answers"].items()]
    rng.shuffle(shown)
    return shown, [p for p in answerers(g) if p not in g["answers"]]


def result(g: dict, user: str, correct: int, rng) -> str:
    """사회자가 술래가 맞힌 수를 알려 줍니다. 그 라운드의 술래를 돌려주고 다음 라운드로 갑니다."""
    _playing(g)
    if user != g["host"]:
        raise GameError("not_host")
    if not 0 <= correct <= len(g["answers"]):
        raise GameError("bad_count")
    it = g["it"]
    g["scores"][it] += correct
    g["done"].append(it)
    _next_round(g, rng)
    return it


def scoreboard(g: dict) -> list:
    """[(참가자, 점수), …] 높은 점수부터 (같으면 참가자 순서)."""
    order = {p: i for i, p in enumerate(g["players"])}
    return sorted(g["scores"].items(), key=lambda s: (-s[1], order[s[0]]))


def end(g: dict, user: str, captain: bool) -> None:
    """시작한 사람이나 대장 갑옷씨가 게임을 멈춥니다."""
    if g["status"] == "done":
        raise GameError("not_running")
    if user != g["starter"] and not captain:
        raise GameError("not_starter")
    g["status"], g["it"], g["host"] = "done", None, None
