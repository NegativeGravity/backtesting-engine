from collections import defaultdict
from hashlib import blake2s


class DeterministicIdGenerator:
    def __init__(self, run_id: str) -> None:
        self._scope = blake2s(run_id.encode("utf-8"), digest_size=6).hexdigest()
        self._counters: defaultdict[str, int] = defaultdict(int)

    def next(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}_{self._scope}_{self._counters[prefix]:012d}"
