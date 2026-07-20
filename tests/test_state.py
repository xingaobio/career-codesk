from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from loop_engine.errors import LoopError
from loop_engine.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_atomic_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            store = StateStore(Path(raw) / "state.json")
            state = store.load()
            state["tasks"] = {"T1": {"status": "pending"}}
            store.save(state)
            self.assertEqual("pending", store.load()["tasks"]["T1"]["status"])

    def test_second_nonblocking_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            first = StateStore(Path(raw) / "state.json")
            second = StateStore(Path(raw) / "state.json")
            with first.lock():
                with self.assertRaises(LoopError) as caught:
                    with second.lock():
                        pass
            self.assertEqual("E_LOCK_HELD", caught.exception.code)


if __name__ == "__main__":
    unittest.main()

