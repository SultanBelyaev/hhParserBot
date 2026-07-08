from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AuthStatus(BaseModel):
    connected: bool
    session_file: str
    message: Optional[str] = None


class LoginPhoneRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)


class LoginCodeRequest(BaseModel):
    code: str = Field(min_length=4, max_length=8)


class LoginStartResponse(BaseModel):
    status: str
    message: str


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    search_query: str = Field(min_length=1, max_length=512)
    area_id: Optional[str] = None
    apply_limit: int = Field(default=10, ge=1, le=500)
    cover_letter: Optional[str] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=256)
    search_query: Optional[str] = Field(default=None, min_length=1, max_length=512)
    area_id: Optional[str] = None
    apply_limit: Optional[int] = Field(default=None, ge=1, le=500)
    cover_letter: Optional[str] = None


class CampaignResponse(BaseModel):
    id: int
    name: str
    search_query: str
    area_id: Optional[str]
    apply_limit: int
    cover_letter: Optional[str]
    status: str
    sent_count: int
    skipped_count: int
    failed_count: int
    processed_count: int
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ApplicationLogResponse(BaseModel):
    id: int
    campaign_id: int
    vacancy_id: str
    vacancy_title: Optional[str]
    status: str
    detail: Optional[str]
    cover_letter_sent: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DetailBreakdown(BaseModel):
    detail: str
    label: str
    count: int
    percent: float
    status: str


class CampaignStatsResponse(BaseModel):
    campaign_id: int
    campaign_name: str
    campaign_status: str
    search_query: str
    apply_limit: int
    vacancies_found: Optional[int]
    processed_count: int
    remaining: int
    totals: dict[str, int]
    rates: dict[str, float]
    timing: dict
    by_status: dict[str, int]
    by_detail: list[DetailBreakdown]
    timeline: list[dict]
