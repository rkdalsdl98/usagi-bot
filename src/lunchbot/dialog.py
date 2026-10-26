"""우사기 1:1 대화 한 턴: 채팅을 읽고(talk), 답을 만들고(answers), 그 사람의 기억(memory)을 쓰고 고칩니다.

기억은 그 1:1 스레드의 주인이 직장인 갑옷씨 이상이고, 하치와레 번역이 켜져 있을 때만 씁니다 (remember).
그 밖에는(남의 스레드에 쓴 사람, 번역이 꺼져 있어 안내·되물음을 못 보는 사람) 기억 파일을 열지도 쓰지도 않고,
기억이 필요 없는 물음 답하기와 짧은 문맥까지만 합니다. 처음에는 무엇을 기억하는지 안내하고, 그 채팅은 기록하지 않습니다.
짧은 문맥은 (스레드, 채팅한 사람)마다 메모리에만 둡니다. 디스코드로 보내는 일은 scripts/usagi_bot.py 가 합니다.
"""
import logging
import random
from dataclasses import dataclass
from datetime import datetime

from . import answers, chat, hachiware, members, memory, storage, talk, vault

log = logging.getLogger(__name__)


@dataclass
class Out:
    sound: str  # 우사기 소리
    hachiware: str | None  # 하치와레 말 (번역이 꺼져 있으면 None)


@dataclass
class Talk:
    outs: list  # 먼저 보낼 것들 (안내, 물음의 답)
    plain: bool  # True 면 평범한 채팅: 우사기 봇이 지금 방식(chat.plan + hachiware.translate)으로 답함
    remark: str | None = None  # plain 일 때 하치와레 번역 뒤에 붙일 기억 한마디


def owner_of(guild_id: str, thread_id: str) -> str | None:
    """그 1:1 스레드의 주인 (/우사기 로 만든 사람)."""
    mine = (storage.get_json(storage.threads_key(guild_id)) or {}).get("usagi", {})
    return next((user for user, thread in mine.items() if str(thread) == str(thread_id)), None)


class Dialog:
    def __init__(self):
        self._contexts: dict[tuple[str, str], talk.Context] = {}

    def drop(self, thread_id: str, user_id: str | None = None) -> None:
        """그 스레드(그 사람)의 짧은 문맥을 버립니다."""
        for k in [k for k in self._contexts if k[0] == str(thread_id) and user_id in (None, k[1])]:
            del self._contexts[k]

    def respond(self, *, guild_id: str, thread_id: str, author_id: str, owner_id: str | None, text: str,
                now: datetime, translating: bool, rng=None) -> Talk:
        rng = rng or random
        guild_id, thread_id, author_id = str(guild_id), str(thread_id), str(author_id)
        where = (thread_id, author_id)
        ctx = self._contexts.get(where)
        if ctx and (now - ctx.at).total_seconds() > talk.CONTEXT_S:  # 오래된 문맥은 버림 (답에도 쓰지 않게)
            ctx = None
        remember = (translating and owner_of(guild_id, thread_id) == author_id
                    and members.person(author_id, "", members.load(guild_id), owner_id).level >= members.WORKER
                    and memory.usable())
        mem = memory.load(guild_id, author_id) if remember else None
        outs, first = [], False

        def out(reply: answers.Reply) -> Out:
            if not translating:
                return Out(reply.script.sound, None)
            line = hachiware.relay(reply.script.text, rng)
            return Out(reply.script.sound, f"{line} {reply.own}" if reply.own else line)

        if remember and not mem["noticed"]:
            outs.append(out(answers.guide(rng)))
            mem["noticed"], first = now.date().isoformat(), True

        turn = talk.understand(text, ctx, now, mem["taught"] if remember else [], answers.supported)
        if turn.kind == "teach" and not remember:  # 가르치기는 기억을 쓰는 사람만
            turn = talk.Turn("chat", words=turn.words)
        reply, talked = None, None
        if turn.kind == "teach":
            lesson = {k: v for k, v in turn.teach.items() if k != "kind"}
            mem["taught"].append({"words": sorted(turn.words), "kind": turn.teach["kind"], **lesson,
                                  "at": now.date().isoformat()})
            reply = answers.learned(rng)
        elif turn.kind == "question":
            facts = answers.gather(guild_id, author_id, owner_id, now)
            reply = answers.answer(turn, facts, mem, ctx, rng)
        elif turn.kind == "taught":
            reply = answers.taught_answer(turn.answer, rng)
        elif turn.kind == "unknown":
            reply = answers.unknown(remember, rng)
        elif turn.kind == "reply":
            reply = answers.reply_to(turn, rng)
        else:
            talked = Talk(outs, plain=True, remark=answers.recall(mem, chat.read(text), now.date()) if remember else None)
        if reply:
            outs.append(out(reply))

        if remember:
            if not first:
                memory.observe(mem, text, chat.read(text), now.date())
            _save(guild_id, author_id, mem)
        self._contexts[where] = _next(ctx, turn, reply, remember, now)
        return talked or Talk(outs, plain=False)


def _save(guild_id: str, user_id: str, mem: dict) -> None:
    try:
        memory.save(guild_id, user_id, mem)
    except (vault.Broken, OSError, ValueError) as e:  # 못 저장해도 답은 보냄 (누구 것인지는 남기지 않음)
        log.warning("1:1 기억을 못 저장함: %s", type(e).__name__)


def _next(keep: talk.Context | None, turn: talk.Turn, reply, remember: bool, now: datetime) -> talk.Context:
    """다음 채팅을 읽을 때 쓸 짧은 문맥 (keep 은 아직 살아 있는 앞 문맥)."""
    topic, ask = (turn.topic, turn.ask) if turn.kind in ("question", "unknown") else (
        (keep.topic, keep.ask) if keep else (None, None))
    target = (reply.target if reply and reply.target else None) or (keep.target if keep else None)
    unknown = talk.key_words(turn.words) if turn.kind == "unknown" and remember else None
    asked = reply.asked if reply else None
    return talk.Context(topic, ask, target, asked, unknown, now)
