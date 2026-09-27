class AppError(Exception):
    status_code = 400

    def __init__(self, message: str, *, status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if status_code:
            self.status_code = status_code
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404


class UploadRejected(AppError):
    status_code = 422
