import logging
import redis
import json
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.logging import setup_logging
from app.core.celery import celery_app
from app.models.job import Job
from app.models.transaction import Transaction
from app.models.summary import JobSummary

from app.services.csv_parser import parse_and_validate_csv, CSVParserError
from app.services.cleaner import clean_records, CleaningError
from app.services.anomaly_detector import detect_anomalies
from app.services.llm_service import classify_categories_batch, generate_narrative_summary
from app.services.summary_builder import compile_job_metrics

# Initialize logging
setup_logging()
logger = logging.getLogger("app.tasks.worker")

# Setup Redis client for progress tracking
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

def update_progress(job_id_str: str, stage: str, completed: int, total: int):
    try:
        redis_client.set(
            f"job:{job_id_str}:progress",
            json.dumps({"stage": stage, "completed": completed, "total": total}),
            ex=86400  # expire in 24 hours
        )
    except Exception as e:
        logger.error(f"Failed to update progress in Redis: {str(e)}")

@celery_app.task(name="app.tasks.worker.process_transaction_csv")
def process_transaction_csv(job_id_str: str, file_path: str):
    logger.info(f"Starting Celery task for job: {job_id_str}")
    job_id = UUID(job_id_str)
    
    db: Session = SessionLocal()
    try:
        # Fetch job and update status to processing
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id_str} not found in database.")
            return False
            
        job.status = "processing"
        job.processing_started_at = datetime.now(timezone.utc)
        db.commit()
        
        # --- Stage A: Ingestion and Validation ---
        logger.info(f"[Job {job_id_str}] Stage A: Ingesting and validating CSV")
        update_progress(job_id_str, "Ingestion", 0, 100)
        try:
            raw_records = parse_and_validate_csv(file_path)
        except CSVParserError as e:
            logger.error(f"[Job {job_id_str}] Stage A failed: {str(e)}")
            job.status = "failed"
            job.error_message = f"CSV validation failed: {str(e)}"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            update_progress(job_id_str, "failed", 0, 0)
            return False
            
        raw_count = len(raw_records)
        job.row_count_raw = raw_count
        db.commit()
        update_progress(job_id_str, "Ingestion", 100, 100)
        logger.info(f"[Job {job_id_str}] Stage A complete. Raw count: {raw_count}")
        
        # --- Stage B: Data Cleaning ---
        logger.info(f"[Job {job_id_str}] Stage B: Cleaning and normalizing transactions")
        update_progress(job_id_str, "Cleaning", 0, 100)
        try:
            cleaned_records = clean_records(raw_records)
        except CleaningError as e:
            logger.error(f"[Job {job_id_str}] Stage B failed: {str(e)}")
            job.status = "failed"
            job.error_message = f"Data cleaning failed: {str(e)}"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            update_progress(job_id_str, "failed", 0, 0)
            return False
            
        clean_count = len(cleaned_records)
        update_progress(job_id_str, "Cleaning", 100, 100)
        logger.info(f"[Job {job_id_str}] Stage B complete. Clean count: {clean_count}")
        
        # --- Stage C: Anomaly Detection ---
        logger.info(f"[Job {job_id_str}] Stage C: Running anomaly detection rules")
        update_progress(job_id_str, "Anomaly Detection", 0, 100)
        try:
            # Calculated only within current job transactions as required
            detect_anomalies(cleaned_records)
        except Exception as e:
            logger.error(f"[Job {job_id_str}] Stage C failed: {str(e)}")
            job.status = "failed"
            job.error_message = f"Anomaly detection failed: {str(e)}"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            update_progress(job_id_str, "failed", 0, 0)
            return False
        update_progress(job_id_str, "Anomaly Detection", 100, 100)
        logger.info(f"[Job {job_id_str}] Stage C complete")
        
        # --- Stage D: LLM Category Classification ---
        logger.info(f"[Job {job_id_str}] Stage D: Running LLM Category classification")
        update_progress(job_id_str, "LLM Classification", 0, 100)
        
        ALLOWED_CATEGORIES = {"Food", "Shopping", "Travel", "Transport", "Utilities", "Cash Withdrawal", "Entertainment", "Other"}
        
        # Filter rows needing classification
        rows_to_classify = []
        for idx, r in enumerate(cleaned_records):
            if r["category"] not in ALLOWED_CATEGORIES:
                r["temp_index"] = idx
                rows_to_classify.append(r)
                
        if rows_to_classify:
            total_classify = len(rows_to_classify)
            logger.info(f"[Job {job_id_str}] Classified row count: {total_classify}. Processing in batches of 15.")
            batch_size = 15
            for i in range(0, total_classify, batch_size):
                batch = rows_to_classify[i:i+batch_size]
                processed_batch, was_successful = classify_categories_batch(batch)
                
                # If the batch failed completely, increment failed batches counter in Job
                if not was_successful:
                    job.llm_failed_batches += 1
                    db.commit()
                
                # Update Redis stage-by-stage progress count
                completed = min(i + batch_size, total_classify)
                update_progress(job_id_str, "LLM Classification", completed, total_classify)
                
            # Re-integrate classified categories
            for item in rows_to_classify:
                idx = item["temp_index"]
                cleaned_records[idx]["category"] = item["llm_category"]
                cleaned_records[idx]["llm_category"] = item["llm_category"]
                cleaned_records[idx]["llm_raw_response"] = item["llm_raw_response"]
                cleaned_records[idx]["llm_failed"] = item["llm_failed"]
        else:
            update_progress(job_id_str, "LLM Classification", 100, 100)
            logger.info(f"[Job {job_id_str}] No rows required classification.")
            
        logger.info(f"[Job {job_id_str}] Stage D complete")
        
        # --- Stage E: LLM Narrative Summary ---
        logger.info(f"[Job {job_id_str}] Stage E: Generating narrative summary")
        update_progress(job_id_str, "Summary Generation", 0, 100)
        try:
            metrics = compile_job_metrics(cleaned_records)
            summary_data = generate_narrative_summary(metrics)
            
            job_summary = JobSummary(
                job_id=job_id,
                total_spend_inr=summary_data["total_spend_inr"],
                total_spend_usd=summary_data["total_spend_usd"],
                top_merchants_json=summary_data["top_merchants"],
                anomaly_count=summary_data["anomaly_count"],
                narrative=summary_data["narrative"],
                risk_level=summary_data["risk_level"]
            )
            db.add(job_summary)
        except Exception as e:
            logger.error(f"[Job {job_id_str}] Stage E failed: {str(e)}")
            # Fallback non-fatal summary
            fallback_metrics = compile_job_metrics(cleaned_records)
            job_summary = JobSummary(
                job_id=job_id,
                total_spend_inr=fallback_metrics["total_spend_inr"],
                total_spend_usd=fallback_metrics["total_spend_usd"],
                top_merchants_json=fallback_metrics["top_merchants"],
                anomaly_count=fallback_metrics["anomaly_count"],
                narrative=f"Partial pipeline completion. Narrative summary generation failed: {str(e)}",
                risk_level="medium" if fallback_metrics["anomaly_count"] > 0 else "low"
            )
            db.add(job_summary)
            
        update_progress(job_id_str, "Summary Generation", 100, 100)
        logger.info(f"[Job {job_id_str}] Stage E complete")
        
        # --- Stage F: Finalization ---
        logger.info(f"[Job {job_id_str}] Stage F: Finalizing job metrics")
        update_progress(job_id_str, "Finalizing", 0, 100)
        
        # Persist transactions
        for r in cleaned_records:
            tx = Transaction(
                job_id=job_id,
                txn_id=r.get("txn_id"),
                raw_date=r.get("raw_date"),
                date=r["date"],
                merchant=r["merchant"],
                raw_amount=r.get("raw_amount"),
                amount=r["amount"],
                currency=r["currency"],
                status=r["status"],
                category=r["category"],
                account_id=r["account_id"],
                notes=r.get("notes"),
                is_anomaly=r.get("is_anomaly", False),
                anomaly_reason=r.get("anomaly_reason"),
                llm_category=r.get("llm_category"),
                llm_raw_response=r.get("llm_raw_response"),
                llm_failed=r.get("llm_failed", False)
            )
            db.add(tx)
        
        job.row_count_clean = clean_count
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        
        db.commit()
        update_progress(job_id_str, "completed", clean_count, clean_count)
        logger.info(f"[Job {job_id_str}] Processing task completed successfully!")
        return True
        
    except Exception as e:
        logger.exception(f"Unexpected error in background worker for job {job_id_str}")
        db.rollback()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_message = f"Internal processing error: {str(e)}"
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
            update_progress(job_id_str, "failed", 0, 0)
        except Exception as db_err:
            logger.error(f"Failed to save error status to database: {str(db_err)}")
        return False
    finally:
        db.close()
