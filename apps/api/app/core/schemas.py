from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from contracts.v1.schemas import JobStatus, Role


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class UserCreate(Input):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=1024)
    role: Role
    tenant_id: UUID | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID | None
    email: EmailStr
    name: str
    role: Role


class SessionOut(BaseModel):
    user: UserOut
    expires_at: datetime


class OrganizationCreate(Input):
    name: str = Field(min_length=1, max_length=200)


class OrganizationOut(OrganizationCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class SchoolCreate(OrganizationCreate):
    organization_id: UUID


class SchoolOut(SchoolCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class Health(BaseModel):
    status: str


class Readiness(Health):
    database: bool
    redis: bool
    worker: bool


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    kind: str
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class Configuration(BaseModel):
    api_version: str
    runtime_ai_configured: bool
    document_types: list[str]
