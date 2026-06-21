from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from app.schemas.transaction import TransactionResponse
from app.schemas.summary import JobSummaryBase

class JobUploadResponse(BaseModel):
    job_id: UUID
    status: str
    message: str

class JobStatusSummary(BaseModel):
    total_spend_inr: Decimal
    total_spend_usd: Decimal
    anomaly_count: int
    risk_level: str

class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    filename: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    summary: Optional[JobStatusSummary] = None
    error_message: Optional[str] = None

class JobResultsResponse(BaseModel):
    job_id: UUID
    status: str
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
    created_at: datetime
