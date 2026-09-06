class AppError(Exception):
    def __init__(self, message, status=400, code="invalid_request"):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def clean_text(value, label, limit=40):
    if not isinstance(value, str):
        raise AppError(f"请填写{label}")
    value = value.strip()
    if not value or len(value) > limit or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in (0xFFFE, 0xFFFF) for c in value):
        raise AppError(f"{label}须为 1—{limit} 个字符，不能包含换行或控制字符")
    return value
