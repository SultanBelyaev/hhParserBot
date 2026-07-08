from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApplicationLog, Campaign
from app.schemas import (
    ApplicationLogResponse,
    CampaignCreate,
    CampaignResponse,
    CampaignStatsResponse,
    CampaignUpdate,
)
from app.services.stats_service import build_campaign_stats
from app.services.worker import campaign_worker

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=list[CampaignResponse])
def list_campaigns(db: Session = Depends(get_db)):
    return db.query(Campaign).order_by(Campaign.created_at.desc()).all()


@router.post("", response_model=CampaignResponse)
def create_campaign(body: CampaignCreate, db: Session = Depends(get_db)):
    campaign = Campaign(
        name=body.name,
        search_query=body.search_query,
        area_id=body.area_id,
        apply_limit=body.apply_limit,
        cover_letter=body.cover_letter,
        status="draft",
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.get("/meta/defaults")
def campaign_defaults():
    from app.config import settings
    return {"default_cover_letter": settings.default_cover_letter}


@router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    return campaign


@router.patch("/{campaign_id}", response_model=CampaignResponse)
def update_campaign(
    campaign_id: int,
    body: CampaignUpdate,
    db: Session = Depends(get_db),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    if campaign.status == "running":
        raise HTTPException(status_code=400, detail="Нельзя редактировать запущенную кампанию")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(campaign, field, value)

    db.commit()
    db.refresh(campaign)
    return campaign


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    if campaign.status == "running":
        raise HTTPException(status_code=400, detail="Сначала остановите кампанию")

    db.query(ApplicationLog).filter(ApplicationLog.campaign_id == campaign_id).delete()
    db.delete(campaign)
    db.commit()
    return {"status": "deleted"}


@router.post("/{campaign_id}/start", response_model=CampaignResponse)
def start_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    if campaign.status == "running":
        raise HTTPException(status_code=400, detail="Кампания уже запущена")

    try:
        campaign_worker.start(campaign_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    campaign.status = "running"
    campaign.started_at = datetime.now(timezone.utc)
    campaign.finished_at = None
    campaign.error_message = None
    campaign.sent_count = 0
    campaign.skipped_count = 0
    campaign.failed_count = 0
    campaign.processed_count = 0
    campaign.vacancies_found = None
    db.query(ApplicationLog).filter(ApplicationLog.campaign_id == campaign_id).delete()
    db.commit()
    db.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/stop", response_model=CampaignResponse)
def stop_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Кампания не найдена")

    campaign_worker.stop(campaign_id)
    if campaign.status == "running":
        campaign.status = "paused"
        campaign.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(campaign)

    return campaign


@router.get("/{campaign_id}/stats", response_model=CampaignStatsResponse)
def get_campaign_stats(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    return build_campaign_stats(campaign, db)


@router.get("/{campaign_id}/logs", response_model=list[ApplicationLogResponse])
def get_campaign_logs(
    campaign_id: int,
    status: Optional[str] = Query(default=None, pattern="^(success|skipped|error)$"),
    detail: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Кампания не найдена")

    query = db.query(ApplicationLog).filter(ApplicationLog.campaign_id == campaign_id)
    if status:
        query = query.filter(ApplicationLog.status == status)
    if detail:
        query = query.filter(ApplicationLog.detail == detail)

    return (
        query.order_by(ApplicationLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
