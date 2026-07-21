class DataEngineError(RuntimeError):
    pass


class DataDiscoveryError(DataEngineError):
    pass


class DataSchemaError(DataEngineError):
    pass


class DataValidationError(DataEngineError):
    pass


class CacheMissError(DataEngineError):
    pass
