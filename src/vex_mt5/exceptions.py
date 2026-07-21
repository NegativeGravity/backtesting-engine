class Mt5CompatibilityError(RuntimeError):
    pass


class Mt5ConnectionError(Mt5CompatibilityError):
    pass


class Mt5SnapshotError(Mt5CompatibilityError):
    pass
