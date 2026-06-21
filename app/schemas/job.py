from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from app.schemas.transaction import TransactionResponse
from app.schemas.summary import JobSummaryBase

class JobUploadResponse(BaseModel):
    job_id: UUID
    status: str

class JobProgress(BaseModel):
    stage: str
    completed: int
    total: int

class JobStatusResponse(BaseModel):
    status: str
    filename: str
    created_at: datetime
    processing_started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: JobProgress
    error_message: Optional[str] = None

class JobResultsResponse(BaseModel):
    cleaned_transactions: List[TransactionResponse]
    anomalies: List[TransactionResponse]
    category_breakdown: Dict[str, Decimal]
    currency_totals: Dict[str, Decimal]
    summary: Optional[JobSummaryBase] = None

class JobListItem(BaseModel):
    job_id: UUID
    filename: str
    status: str
    row_count_raw: Optional[int] = None
    row_count_clean: Optional[int] = None
    llm_failed_batches: int = 0
    created_at: datetime
    processing_started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
