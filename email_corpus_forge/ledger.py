"""Append-only hash-linked events and atomic budget reservations."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
from .contracts import canonical, digest


class IntegrityError(ValueError):
    pass


@contextmanager
def exclusive_lock(path: Path, *, nonblocking: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        flag = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
        fcntl.flock(lock, flag)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class Ledger:
    def __init__(self, run_dir: Path, cap_micro: int = 10_000_000):
        if type(cap_micro) is not int or cap_micro < 0:
            raise ValueError("invalid budget cap")
        self.directory = Path(run_dir)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "ledger.jsonl"
        self.lock = self.directory / ".ledger.lock"
        self.cap_micro = cap_micro
        self._cached_events = None
        self._stamp = None
        self._attempts = {}
        self._reservations = {}
        self._settlements = {}

    def events(self) -> list[dict]:
        with exclusive_lock(self.lock):
            return json.loads(canonical(self._read()))

    def _read(self) -> list[dict]:
        stamp = self._file_stamp()
        if self._cached_events is not None and stamp == self._stamp:
            return self._cached_events
        events = []
        previous = "0" * 64
        if not self.path.exists():
            self._index(events, stamp)
            return events
        raw = self.path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise IntegrityError("truncated ledger; manual reconciliation required")
        for line in raw.splitlines():
            try:
                event = json.loads(line)
                stored_hash = event.pop("hash")
                if event["previous"] != previous or event["sequence"] != len(events) or digest(event) != stored_hash:
                    raise IntegrityError("ledger hash chain mismatch")
                event["hash"] = stored_hash
                events.append(event)
                previous = stored_hash
            except (ValueError, KeyError, TypeError) as exc:
                raise IntegrityError("invalid ledger event") from exc
        self._index(events, stamp)
        return events

    def _file_stamp(self):
        if not self.path.exists():
            return None
        st = self.path.stat()
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)

    def _index(self, events, stamp):
        self._cached_events, self._stamp = events, stamp
        self._attempts = {}
        self._reservations, self._settlements = self._accounts(events)
        for event in events:
            attempt = event['data'].get('attempt_id')
            if attempt is not None:
                self._attempts.setdefault(attempt, []).append(event)
        self._committed = sum(self._settlements.values()) + sum(v for k, v in self._reservations.items() if k not in self._settlements)

    def attempt_events(self, attempt_id):
        with exclusive_lock(self.lock):
            self._read()
            return json.loads(canonical(self._attempts.get(attempt_id, [])))

    def _append(self, events: list[dict], kind: str, **data) -> dict:
        data = json.loads(canonical(data))  # Detach caller-owned nested values before caching.
        event = {"sequence": len(events), "previous": events[-1]["hash"] if events else "0" * 64,
                 "kind": kind, "data": data}
        event["hash"] = digest(event)
        with self.path.open("ab") as out:
            out.write(canonical(event) + b"\n")
            out.flush()
            os.fsync(out.fileno())
        events.append(event)
        self._cached_events, self._stamp = events, self._file_stamp()
        attempt = data.get('attempt_id')
        if attempt is not None:
            self._attempts.setdefault(attempt, []).append(event)
        if kind == 'reserved':
            self._reservations[attempt] = data['amount_micro']
            self._committed += data['amount_micro']
        elif kind == 'settled':
            self._settlements[attempt] = data['actual_micro']
            self._committed += data['actual_micro'] - self._reservations[attempt]
        return json.loads(canonical(event))

    def append(self, kind: str, **data) -> dict:
        with exclusive_lock(self.lock):
            return self._append(self._read(), kind, **data)

    @staticmethod
    def _accounts(events: list[dict]) -> tuple[dict, dict]:
        reservations, settlements = {}, {}
        for event in events:
            d = event["data"]
            if event["kind"] == "reserved":
                reservations[d["attempt_id"]] = d["amount_micro"]
            elif event["kind"] == "settled":
                settlements[d["attempt_id"]] = d["actual_micro"]
        return reservations, settlements

    def reserve(self, attempt_id: str, amount_micro: int) -> bool:
        if not attempt_id or type(amount_micro) is not int or amount_micro < 0:
            raise ValueError("invalid reservation")
        with exclusive_lock(self.lock):
            events = self._read()
            reservations, settlements = self._reservations, self._settlements
            if attempt_id in reservations:
                if reservations[attempt_id] != amount_micro:
                    raise IntegrityError("reservation changed on resume")
                return True
            committed = self._committed
            if committed + amount_micro > self.cap_micro:
                self._append(events, "budget_blocked", attempt_id=attempt_id, amount_micro=amount_micro)
                return False
            self._append(events, "reserved", attempt_id=attempt_id, amount_micro=amount_micro)
            return True

    def settle(self, attempt_id: str, actual_micro: int) -> None:
        if type(actual_micro) is not int or actual_micro < 0:
            raise ValueError("invalid usage cost")
        with exclusive_lock(self.lock):
            events = self._read()
            reservations, settlements = self._reservations, self._settlements
            if attempt_id not in reservations:
                raise IntegrityError("settlement without reservation")
            if attempt_id in settlements:
                if settlements[attempt_id] != actual_micro:
                    raise IntegrityError("usage changed on resume")
                return
            if actual_micro > reservations[attempt_id]:
                raise IntegrityError("reported usage exceeds reservation; held for reconciliation")
            self._append(events, "settled", attempt_id=attempt_id, actual_micro=actual_micro)

    def balance(self) -> dict:
        with exclusive_lock(self.lock):
            self._read()
            spent = sum(self._settlements.values())
            return {"spent_micro": spent, "reserved_micro": self._committed - spent, "cap_micro": self.cap_micro}


def write_once(path: Path, value: object) -> str:
    """Publish fully flushed bytes once; existing evidence is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(value) + b"\n"
    temp = path.with_name(path.name + ".pending")
    try:
        with temp.open("xb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.link(temp, path)  # fails atomically if destination exists
    finally:
        if temp.exists():
            temp.unlink()
    return digest(value)
