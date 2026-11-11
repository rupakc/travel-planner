"""One error envelope for the account/game routes: {detail, error_code, **extra}."""


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        *,
        headers: dict | None = None,
        **extra,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.headers = headers
        self.extra = extra

    def body(self) -> dict:
        return {"detail": self.detail, "error_code": self.code, **self.extra}
