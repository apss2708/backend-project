from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from decimal import Decimal
from uuid import UUID

class JobSummaryBase(BaseModel):
    total_spend_inr: Decimal
    total_spend_usd: Decimal
    top_merchants: List[str] = Field(alias="top_merchants_json")
    anomaly_count: int
    narrative: Optional[str] = None
    risk_level: str

class JobSummaryResponse(JobSummaryBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    job_id: UUID
