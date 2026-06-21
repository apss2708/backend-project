import os
import uuid
import logging
import redis
import json
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from decimal import Decimal

from app.core.database import get_db
from app.models.job import Job
from app.models.transaction import Transaction
from app.models.summary import JobSummary
from app.schemas.job import (
    JobUploadResponse,
    JobStatusResponse,
    JobProgress,
    JobResultsResponse,
    JobListItem
)
from app.schemas.transaction import TransactionResponse
from app.schemas.summary import JobSummaryBase
from app.core.config import settings

# Celery task import
from app.tasks.worker import process_transaction_csv

logger = logging.getLogger("app.api.routes.jobs")

router = APIRouter(prefix="/jobs", tags=["Jobs"])

# Redis client for progress polling
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

@router.post("/upload", response_model=JobUploadResponse, status_code=202)
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Invalid file format. Only CSV files are accepted."
        )
        
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    
    job_id = uuid.uuid4()
    unique_filename = f"{job_id}_{file.filename}"
    file_path = os.path.join(settings.UPLOAD_DIR, unique_filename)
    
    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save upload file: {str(e)}"
        )
        
    db_job = Job(
        id=job_id,
        filename=file.filename,
        status="pending"
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    
    # Initialize progress in Redis
    try:
        redis_client.set(
            f"job:{job_id}:progress",
            json.dumps({"stage": "pending", "completed": 0, "total": 0}),
            ex=86400
        )
    except Exception as re_err:
        logger.error(f"Redis initialization failed: {str(re_err)}")
    
    try:
        process_transaction_csv.delay(str(job_id), file_path)
    except Exception as e:
        logger.error(f"Failed to queue celery task for job {job_id}: {str(e)}")
        db_job.status = "failed"
        db_job.error_message = f"Queue worker trigger failed: {str(e)}"
        db.commit()
        raise HTTPException(
            status_code=500,
            detail="Failed to queue job for background processing"
        )
        
    return JobUploadResponse(
        job_id=db_job.id,
        status=db_job.status
    )

@router.get("/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: UUID, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    # Poll progress from Redis
    progress_stage = "pending"
    progress_completed = 0
    progress_total = 0
    
    try:
        progress_data = redis_client.get(f"job:{job_id}:progress")
        if progress_data:
            p_dict = json.loads(progress_data)
            progress_stage = p_dict.get("stage", "pending")
            progress_completed = int(p_dict.get("completed", 0))
            progress_total = int(p_dict.get("total", 0))
        else:
            # Fallback static states if Redis has expired
            if job.status == "completed":
                progress_stage = "completed"
                progress_completed = job.row_count_clean or 0
                progress_total = job.row_count_clean or 0
            elif job.status == "failed":
                progress_stage = "failed"
            elif job.status == "processing":
                progress_stage = "processing"
    except Exception as re_err:
        logger.error(f"Failed to fetch progress from Redis: {str(re_err)}")
        if job.status == "completed":
            progress_stage = "completed"
            progress_completed = job.row_count_clean or 0
            progress_total = job.row_count_clean or 0
            
    return JobStatusResponse(
        status=job.status,
        filename=job.filename,
        created_at=job.created_at,
        processing_started_at=job.processing_started_at,
        completed_at=job.completed_at,
        progress=JobProgress(
            stage=progress_stage,
            completed=progress_completed,
            total=progress_total
        ),
        error_message=job.error_message
    )

@router.get("/{job_id}/results", response_model=JobResultsResponse)
def get_job_results(job_id: UUID, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if job.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is in state '{job.status}'. Results are only available for 'completed' jobs."
        )
        
    transactions = db.query(Transaction).filter(Transaction.job_id == job_id).all()
    anomalies = [t for t in transactions if t.is_anomaly]
    
    # Calculate aggregates
    category_breakdown = {}
    currency_totals = {"INR": Decimal("0.00"), "USD": Decimal("0.00")}
    
    for t in transactions:
        # Sum category amounts
        category_breakdown[t.category] = category_breakdown.get(t.category, Decimal("0.00")) + t.amount
        
        # Sum totals per currency
        currency_totals[t.currency] = currency_totals.get(t.currency, Decimal("0.00")) + t.amount
        
    # Fetch job summary
    summary_record = db.query(JobSummary).filter(JobSummary.job_id == job_id).first()
    summary_response = None
    if summary_record:
        summary_response = JobSummaryBase(
            total_spend_inr=summary_record.total_spend_inr,
            total_spend_usd=summary_record.total_spend_usd,
            top_merchants_json=summary_record.top_merchants_json,
            anomaly_count=summary_record.anomaly_count,
            narrative=summary_record.narrative,
            risk_level=summary_record.risk_level
        )
        
    txn_responses = [TransactionResponse.model_validate(t) for t in transactions]
    anomaly_responses = [TransactionResponse.model_validate(a) for a in anomalies]
    
    return JobResultsResponse(
        cleaned_transactions=txn_responses,
        anomalies=anomaly_responses,
        category_breakdown=category_breakdown,
        currency_totals=currency_totals,
        summary=summary_response
    )

@router.get("", response_model=List[JobListItem])
def list_jobs(
    status: Optional[str] = Query(None, description="Filter jobs by status"),
    db: Session = Depends(get_db)
):
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status.strip().lower())
    query = query.order_by(desc(Job.created_at))
    jobs = query.all()
    
    return [
        JobListItem(
            job_id=job.id,
            filename=job.filename,
            status=job.status,
            row_count_raw=job.row_count_raw,
            row_count_clean=job.row_count_clean,
            llm_failed_batches=job.llm_failed_batches,
            created_at=job.created_at,
            processing_started_at=job.processing_started_at,
            completed_at=job.completed_at
        )
        for job in jobs
    ]
