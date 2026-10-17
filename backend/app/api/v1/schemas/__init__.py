"""Request and response schemas for the v1 API."""

from app.api.v1.schemas.auth import (
    AuthConfigResponse,
    HealthResponse,
    LoginRequest,
    ReadyResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.api.v1.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from app.api.v1.schemas.connections import (
    AzureConnectionCreate,
    AzureConnectionResponse,
    AzureConnectionUpdate,
    AzureTestResult,
    GitConnectionCreate,
    GitConnectionResponse,
    GitConnectionUpdate,
    GitTestResult,
)
from app.api.v1.schemas.projects import (
    PatternSampleResult,
    PatternTestRequest,
    PatternTestResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
)

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "AuthConfigResponse",
    "AzureConnectionCreate",
    "AzureConnectionResponse",
    "AzureConnectionUpdate",
    "AzureTestResult",
    "GitConnectionCreate",
    "GitConnectionResponse",
    "GitConnectionUpdate",
    "GitTestResult",
    "HealthResponse",
    "LoginRequest",
    "Page",
    "PatternSampleResult",
    "PatternTestRequest",
    "PatternTestResponse",
    "ProjectCreate",
    "ProjectResponse",
    "ProjectUpdate",
    "ReadyResponse",
    "RegisterRequest",
    "TokenResponse",
    "UserResponse",
    "UserUpdateRequest",
]
