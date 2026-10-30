"""Product-tenant identity loaded from factory tenants.yaml + programme meta."""

from pydantic import ConfigDict, Field, model_validator

from src.models.base_models import BaseCreateModel

GLOBAL_MEMORY_ROOM = "adh-memory"
GLOBAL_REPO = "adh"
MEMORY_SCOPE_GLOBAL = "global"
MEMORY_SCOPE_REPO = "repo"


def memory_room_for_repo(repo: str) -> str:
    """Buzz memory room for one GitHub repo. Global ADH memory stays adh-memory."""
    name = (repo or "").strip()
    if not name or name == GLOBAL_REPO:
        return "adh-repo-memory"
    return f"{name}-memory"


def knowledge_scope_key(*, scope: str, repo: str, kind: str, initiative: str) -> str:
    return f"{scope}:{repo}:{kind}:{initiative}"


class TenantEntry(BaseCreateModel):
    model_config = ConfigDict(
        validate_assignment=True,
        str_strip_whitespace=True,
        extra="ignore",
    )

    slug: str = Field(..., min_length=2, max_length=64)
    meta_repo: str = Field(..., min_length=2, max_length=128)
    active: bool = False


class TenantsDocument(BaseCreateModel):
    model_config = ConfigDict(
        validate_assignment=True,
        str_strip_whitespace=True,
        extra="ignore",
    )

    max_active: int = Field(default=5, ge=1, le=5)
    tenants: list[TenantEntry] = Field(default_factory=list)


class TenantContext(BaseCreateModel):
    """One active product programme. Topology comes from that programme's meta."""

    model_config = ConfigDict(
        validate_assignment=True,
        str_strip_whitespace=True,
        extra="ignore",
    )

    slug: str = Field(..., min_length=2, max_length=64)
    org: str = Field(..., min_length=2, max_length=128)
    meta_repo: str = Field(..., min_length=2, max_length=128)
    meta_root: str = Field(..., min_length=1, max_length=512)
    integration_branch: str = Field(default="develop", min_length=1, max_length=128)
    ops_room: str = Field(default="", max_length=128)
    memory_room: str = Field(default="", max_length=128)
    repos: dict[str, str] = Field(default_factory=dict)
    init_prefix: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def _fill_derived(self) -> "TenantContext":
        if not self.ops_room:
            self.ops_room = f"{self.slug}-ops"
        if not self.memory_room:
            self.memory_room = memory_room_for_repo(self.meta_repo)
        if not self.init_prefix:
            self.init_prefix = f"INIT-{self.slug.upper()}-"
        return self
