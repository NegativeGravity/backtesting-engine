class StrategyError(Exception):
    pass


class StrategyLoadError(StrategyError):
    pass


class StrategyExecutionError(StrategyError):
    pass


class StrategyTimeoutError(StrategyExecutionError):
    pass


class StrategyProcessError(StrategyExecutionError):
    pass


class StrategyOutputLimitError(StrategyExecutionError):
    pass


class StrategyActionError(StrategyExecutionError):
    pass


class StrategyFeedbackLimitError(StrategyExecutionError):
    pass


class StrategyMarketDataError(StrategyExecutionError):
    pass
