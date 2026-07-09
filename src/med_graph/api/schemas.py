"""API response envelope, mirroring the project's standard ApiResponse shape."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    error: str | None = None


def ok(data: T) -> ApiResponse[T]:
    return ApiResponse(success=True, data=data)
