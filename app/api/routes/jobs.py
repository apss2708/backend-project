import os
import uuid
import logging
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
    JobStatusSummary,
    JobResultsResponse,
    JobListItem
)
from app.schemas.transaction import TransactionResponse
from app.schemas.summary import JobSummaryBase
from app.core.config import settings

# Celery task import inside worker to avoid circular dependency
from app.tasks.worker import process_transaction_csv

logger = logging.getLogger("app.api.routes.jobs")

router = APIRouter(prefix="/jobs", tags=["Jobs"])

@router.post("/upload", response_model=JobUploadResponse, status_code=202)
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    # 1. Validate file extension
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Invalid file format. Only CSV files are accepted."
        )
        
    # Create upload directory if it doesn't exist
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    
    # 2. Persist initial Job record
    job_id = uuid.uuid4()
    unique_filename = f"{job_id}_{file.filename}"
    file_path = os.path.join(settings.UPLOAD_DIR, unique_filename)
    
    # Save file to host directory
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
    
    # 3. Enqueue background task
    try:
        process_transaction_csv.delay(str(job_id), file_path)
    except Exception as e:
        logger.error(f"Failed to queue celery task for job {job_id}: {str(e)}")
        # Fail the job record immediately in DB
        db_job.status = "failed"
        db_job.error_message = f"Queue worker trigger failed: {str(e)}"
        db.commit()
        raise HTTPException(
            status_code=500,
            detail="Failed to queue job for background processing"
        )
        
    return JobUploadResponse(
        job_id=db_job.id,
        status=db_job.status,
        message="Job created and queued for processing"
    )

@router.get("/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: UUID, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    # Check if there is an associated JobSummary
    summary_data = None
    if job.status == "completed":
        summary = db.query(JobSummary).filter(JobSummary.job_id == job_id).first()
        if summary:
            summary_data = JobStatusSummary(
                total_spend_inr=summary.total_spend_inr,
                total_spend_usd=summary.total_spend_usd,
                anomaly_count=summary.anomaly_count,
                risk_level=summary.risk_level
            )
            
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        filename=job.filename,
        created_at=job.created_at,
        completed_at=job.completed_at,
        summary=summary_data,
        error_message=job.error_message
    )

@router.get("/{job_id}/results", response_model=JobResultsResponse)
def get_job_results(job_id: UUID, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    # Results are only fully computed for completed jobs
    if job.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is in state '{job.status}'. Results are only available for 'completed' jobs."
        )
        
    # Fetch transactions
    transactions = db.query(Transaction).filter(Transaction.job_id == job_id).all()
    anomalies = [t for t in transactions if t.is_anomaly]
    
    # Calculate category spend breakdown
    category_breakdown = {}
    currency_totals = {"INR": Decimal("0.00"), "USD": Decimal("0.00")}
    llm_failed_rows_count = 0
    
    for t in transactions:
        category_breakdown[t.category] = category_breakdown.get(t.category, Decimal("0.00")) + t.amount
        
        # Calculate totals per currency (INR, USD, etc.)
        currency_totals[t.currency] = currency_totals.get(t.currency, Decimal("0.00")) + t.amount
        
        if t.llm_failed:
            llm_failed_rows_count += 1
            
    # Fetch JobSummary record
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
        
    # Serialize lists using Pydantic conversion
    txn_responses = [TransactionResponse.model_validate(t) for t in transactions]
    anomaly_responses = [TransactionResponse.model_validate(a) for a in anomalies]
    
    return JobResultsResponse(
        job_id=job.id,
        status=job.status,
        cleaned_transactions=txn_responses,
        anomalies=anomaly_responses,
        category_breakdown=category_breakdown,
        currency_totals=currency_totals,
        summary=summary_response,
        llm_failed_rows_count=llm_failed_rows_count
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
            created_at=job.created_at
        )
        for job in jobs
    ]
