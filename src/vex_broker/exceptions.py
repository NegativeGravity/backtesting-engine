class BrokerError(Exception):
    pass


class BrokerConfigurationError(BrokerError):
    pass


class OrderRejectedError(BrokerError):
    pass


class OrderNotFoundError(BrokerError):
    pass


class PositionNotFoundError(BrokerError):
    pass


class AmbiguousBarError(BrokerError):
    pass


class UnsupportedBrokerFeatureError(BrokerError):
    pass
