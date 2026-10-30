class BusinessError(Exception):
    """A rule of the product was broken; shown to the caller as a clean error."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
