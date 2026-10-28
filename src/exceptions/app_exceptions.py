"""Application exceptions for Parichay."""

from typing import Any, Dict, Optional


class BaseAppException(Exception):
    """Base exception for all application exceptions."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(BaseAppException):
    """Exception raised when a resource is not found."""

    def __init__(
        self,
        resource_type: str,
        resource_id: Any,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        error_message = message or f"{resource_type} with ID {resource_id} not found"
        error_details = details or {}
        error_details.update({"resource_type": resource_type, "resource_id": str(resource_id)})
        super().__init__(
            code="RESOURCE_NOT_FOUND",
            message=error_message,
            status_code=404,
            details=error_details,
        )


class ValidationError(BaseAppException):
    """Exception raised for validation errors."""

    def __init__(
        self,
        message: str,
        field_errors: Optional[Dict[str, str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        error_details = details or {}
        if field_errors:
            error_details["field_errors"] = field_errors
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            status_code=400,
            details=error_details,
        )


class UnauthorizedError(BaseAppException):
    """Exception raised when API credentials are invalid or missing."""

    def __init__(
        self,
        message: str = "Invalid or missing API credentials",
        details: Optional[Dict[str, Any]] = None,
    ):
        error_details = details or {}
        super().__init__(
            code="UNAUTHORIZED",
            message=message,
            status_code=401,
            details=error_details,
        )


class ServiceUnavailableError(BaseAppException):
    """Exception raised when a service is unavailable."""

    def __init__(
        self,
        service_name: str,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        error_message = message or f"Service {service_name} is unavailable"
        error_details = details or {}
        error_details["service_name"] = service_name
        super().__init__(
            code="SERVICE_UNAVAILABLE",
            message=error_message,
            status_code=503,
            details=error_details,
        )
