class ZhihuError(Exception):
    """Base exception for zhihu-api."""


class ZhihuAPIError(ZhihuError):
    """Zhihu returned an error response."""

    def __init__(self, message, *, status=None, code=None, url=None, payload=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.url = url
        self.payload = payload


class ZhihuNotFoundError(ZhihuAPIError):
    """The requested user, article or resource does not exist."""


class ZhihuRateLimitError(ZhihuAPIError):
    """Zhihu is rate limiting or temporarily blocking the request."""


class ZhihuReaderError(ZhihuError):
    """The public reader proxy failed or returned an unusable response."""

    def __init__(self, message, *, url=None, code=None, status=None, payload=None):
        super().__init__(message)
        self.message = message
        self.url = url
        self.code = code
        self.status = status
        self.payload = payload


class ZhihuResponseError(ZhihuError):
    """Zhihu returned a response that could not be parsed or lacked fields."""

    def __init__(self, message, *, url=None, payload=None):
        super().__init__(message)
        self.message = message
        self.url = url
        self.payload = payload


class ZhihuConnectionError(ZhihuError):
    """The request to Zhihu failed before a response was received."""

    def __init__(self, message, *, url=None):
        super().__init__(message)
        self.message = message
        self.url = url
