import uuid
from sqlalchemy import Column, String, Integer, Numeric, Text, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class JobSummary(Base):
    __tablename__ = "job_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    total_spend_inr = Column(Numeric(18, 2), default=0.00, nullable=False)
    total_spend_usd = Column(Numeric(18, 2), default=0.00, nullable=False)
    top_merchants_json = Column(JSON, default=list, nullable=False)  # JSON list of top merchants
    anomaly_count = Column(Integer, default=0, nullable=False)
    narrative = Column(Text, nullable=True)
    risk_level = Column(String(50), default="low", nullable=False)  # low, medium, high
