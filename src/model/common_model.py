from dataclasses import dataclass
from typing import Optional, Any


@dataclass
class OperationResult:
    """Simple result wrapper for operations."""

    is_success: bool
    detail: Optional[Any] = None

    @classmethod
    def success(cls, detail: Any = None) -> 'OperationResult':
        return cls(is_success=True, detail=detail)

    @classmethod
    def fail(cls, detail: Any = None) -> 'OperationResult':
        return cls(is_success=False, detail=detail)
