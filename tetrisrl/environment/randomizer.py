"""Deterministic seven-bag randomizer.

Each :class:`SevenBag` owns its own :class:`random.Random` instance so piece
generation is independent of garbage RNGs and reproducible from a seed.  The
generator state is serialisable, which is what makes deterministic replays and
checkpoint-resumed training possible.
"""

from __future__ import annotations

import random
from typing import List, Optional, Sequence, Tuple

PIECES: Tuple[str, ...] = ("I", "J", "L", "O", "S", "T", "Z")


class SevenBag:
    def __init__(self, seed: int = 0, preview: int = 5) -> None:
        self.seed = seed
        self._rng = random.Random(seed)
        self.preview = preview
        self._queue: List[str] = []
        self._fill()

    def _fill(self) -> None:
        while len(self._queue) <= self.preview + 1:
            bag = list(PIECES)
            self._rng.shuffle(bag)
            self._queue.extend(bag)

    def peek(self, n: int) -> List[str]:
        self._fill()
        return self._queue[:n]

    def next(self) -> str:
        self._fill()
        return self._queue.pop(0)

    def reset(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.seed = seed
        self._rng = random.Random(self.seed)
        self._queue = []
        self._fill()

    def state_dict(self) -> dict:
        return {
            "seed": self.seed,
            "preview": self.preview,
            "queue": list(self._queue),
            "rng_state": self._rng.getstate(),
        }

    def load_state_dict(self, state: dict) -> None:
        self.seed = int(state["seed"])
        self.preview = int(state.get("preview", self.preview))
        self._queue = list(state["queue"])
        # random.Random state has to be rebuilt through setstate; the tuple
        # form is JSON-unfriendly, so callers persist it via pickle instead.
        self._rng.setstate(state["rng_state"])


class FixedSequence:
    """Deterministic piece source used by tests / scripted replays."""

    def __init__(self, pieces: Sequence[str], repeat: bool = True) -> None:
        self._pieces = list(pieces)
        self._index = 0
        self.repeat = repeat

    def peek(self, n: int) -> List[str]:
        out = []
        for i in range(n):
            idx = self._index + i
            if idx < len(self._pieces):
                out.append(self._pieces[idx])
            elif self.repeat:
                out.append(self._pieces[idx % len(self._pieces)])
            else:
                out.append("I")
        return out

    def next(self) -> str:
        if self._index >= len(self._pieces):
            if not self.repeat:
                raise IndexError("fixed sequence exhausted")
            self._index = 0
        piece = self._pieces[self._index]
        self._index += 1
        return piece
