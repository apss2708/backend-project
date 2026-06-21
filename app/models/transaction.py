import uuid
from sqlalchemy import Column, String, Numeric, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    txn_id = Column(String(100), nullable=True)  # txn_id in CSV can be empty/null
    raw_date = Column(String(100), nullable=True)
    date = Column(String(50), nullable=True)  # Normalized to ISO 8601 (YYYY-MM-DD)
    merchant = Column(String(255), nullable=True)
    raw_amount = Column(String(100), nullable=True)
    amount = Column(Numeric(18, 2), nullable=True)  # Decimal-safe amount (Numeric(18,2))
    currency = Column(String(10), nullable=True)
    status = Column(String(50), nullable=True)
    category = Column(String(100), nullable=True)
    account_id = Column(String(100), nullable=True, index=True)  # account_id is indexed
    notes = Column(Text, nullable=True)
    
    # Anomaly fields
    is_anomaly = Column(Boolean, default=False, nullable=False)
    anomaly_reason = Column(Text, nullable=True)
    
    # LLM category enrichment fields
    llm_category = Column(String(100), nullable=True)
    llm_raw_response = Column(Text, nullable=True)
    llm_failed = Column(Boolean, default=False, nullable=False)
