"""Short-term, in-memory conversation history keyed by browser session id."""

from __future__ import annotations

from collections import OrderedDict


class Conversations:
    """Keeps the last few turns per session so follow-up questions make sense.

    History lives only in RAM and is dropped when the server restarts.
    """

    def __init__(self, max_turns: int = 8, max_sessions: int = 100) -> None:
        self._max_messages = max_turns * 2
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, list[dict[str, str]]] = OrderedDict()

    def get(self, session_id: str) -> list[dict[str, str]]:
        return list(self._sessions.get(session_id, []))

    def add_turn(self, session_id: str, user: str, assistant: str) -> None:
        messages = self._sessions.pop(session_id, [])
        messages += [
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
        self._sessions[session_id] = messages[-self._max_messages :]
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
