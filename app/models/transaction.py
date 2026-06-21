import uuid
from sqlalchemy import Column, String, Numeric, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    txnid = Column(String(100), nullable=True)  # txn_id in CSV can be empty/null
    date = Column(String(50), nullable=False)  # Normalized to ISO 8601 (YYYY-MM-DD)
    merchant = Column(String(255), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), nullable=False)
    status = Column(String(50), nullable=False)  # Normalized status values (uppercase)
    category = Column(String(100), nullable=False)  # Normalized category values
    account_id = Column(String(100), nullable=False)
    notes = Column(Text, nullable=True)
    
    # Anomaly fields
    is_anomaly = Column(Boolean, default=False, nullable=False)
    anomaly_reason = Column(Text, nullable=True)
    
    # LLM category enrichment fields
    llm_category = Column(String(100), nullable=True)
    llm_raw_response = Column(Text, nullable=True)
    llm_failed = Column(Boolean, default=False, nullable=False)
