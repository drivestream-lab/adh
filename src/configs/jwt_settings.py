"""JWT settings for adh."""

from typing import ClassVar, Optional

from pydantic import Field

from src.configs.base_settings import BaseSettings


class JWTSettings(BaseSettings):
    """Settings for JWT verification (RS256 in production)."""

    PREFIX: ClassVar[str] = "JWT"

    secret_key: str = Field(
        default="change-me-in-production",
        description="Secret key for HS256; ignored when using RS256",
    )
    algorithm: str = Field(default="RS256", description="JWT algorithm (HS256 or RS256)")
    issuer: str = Field(default="adh", description="JWT issuer claim")
    audience: str = Field(default="drivestream", description="JWT audience claim")
    expiry_seconds: int = Field(default=3600, description="JWT expiry in seconds")
    private_key_path: Optional[str] = Field(default=None, description="RS256 private key path")
    public_key_path: Optional[str] = Field(default=None, description="RS256 public key path")
