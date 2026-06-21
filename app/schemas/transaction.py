from pydantic import BaseModel, ConfigDict
from typing import Optional
from decimal import Decimal
from uuid import UUID

class TransactionBase(BaseModel):
    txnid: Optional[str] = None
    date: str
    merchant: str
    amount: Decimal
    currency: str
    status: str
    category: str
    account_id: str
    notes: Optional[str] = None

class TransactionCreate(TransactionBase):
    pass

class TransactionResponse(TransactionBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    is_anomaly: bool
    anomaly_reason: Optional[str] = None
    llm_category: Optional[str] = None
    llm_raw_response: Optional[str] = None
    llm_failed: bool
