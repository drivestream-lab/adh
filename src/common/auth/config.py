"""Auth configuration for shared JWT (user tokens). App passes this from env/settings."""

from typing import List, Optional


class AuthConfig:
    """Configuration for user JWT issuance and verification. No env reads here; app provides values."""

    def __init__(
        self,
        secret_key: str,
        issuer: str,
        audience: str,
        public_paths: List[str],
        algorithm: str = "HS256",
        private_key_path: Optional[str] = None,
        public_key_path: Optional[str] = None,
    ) -> None:
        self.secret_key = secret_key
        self.issuer = issuer
        self.audience = audience
        self.public_paths = list(public_paths)
        self.algorithm = algorithm
        self.private_key_path = private_key_path
        self.public_key_path = public_key_path
