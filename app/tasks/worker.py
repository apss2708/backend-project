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
    log_ctx = {"job_id": job_id_str, "stage": "startup"}
    logger.info("Starting Celery task", extra=log_ctx)
    job_id = UUID(job_id_str)

    db: Session = SessionLocal()
    try:
        # Fetch job
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("Job not found in database", extra=log_ctx)
            return False

        # ── Idempotency guard ──────────────────────────────────────────────────
        # Protects against Celery retries re-processing an already running or
        # finished job. If the job is already completed or being processed, bail
        # out immediately without making any state changes.
        if job.status in ("completed", "processing"):
            logger.warning(
                "Task skipped – job already in terminal/active state",
                extra={"job_id": job_id_str, "stage": "idempotency_guard", "current_status": job.status},
            )
            return True
        # ──────────────────────────────────────────────────────────────────────

        job.status = "processing"
        job.processing_started_at = datetime.now(timezone.utc)
        db.commit()

        # --- Stage A: Ingestion and Validation ---
        log_ctx = {"job_id": job_id_str, "stage": "ingestion"}
        logger.info("Stage A: Ingesting and validating CSV", extra=log_ctx)
        update_progress(job_id_str, "Ingestion", 0, 100)
        try:
            raw_records = parse_and_validate_csv(file_path)
        except CSVParserError as e:
            logger.error("Stage A failed: CSV validation error", extra={**log_ctx, "error": str(e)})
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
        logger.info("Stage A complete", extra={**log_ctx, "raw_count": raw_count})
        
        # --- Stage B: Data Cleaning ---
        log_ctx = {"job_id": job_id_str, "stage": "cleaning"}
        logger.info("Stage B: Cleaning and normalizing transactions", extra=log_ctx)
        update_progress(job_id_str, "Cleaning", 0, 100)
        try:
            cleaned_records = clean_records(raw_records)
        except CleaningError as e:
            logger.error("Stage B failed: Data cleaning error", extra={**log_ctx, "error": str(e)})
            job.status = "failed"
            job.error_message = f"Data cleaning failed: {str(e)}"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            update_progress(job_id_str, "failed", 0, 0)
            return False

        clean_count = len(cleaned_records)
        update_progress(job_id_str, "Cleaning", 100, 100)
        logger.info("Stage B complete", extra={**log_ctx, "clean_count": clean_count})
        
        # --- Stage C: Anomaly Detection ---
        log_ctx = {"job_id": job_id_str, "stage": "anomaly_detection"}
        logger.info("Stage C: Running anomaly detection rules", extra=log_ctx)
        update_progress(job_id_str, "Anomaly Detection", 0, 100)
        try:
            # Calculated only within current job transactions as required
            detect_anomalies(cleaned_records)
        except Exception as e:
            logger.error("Stage C failed: Anomaly detection error", extra={**log_ctx, "error": str(e)})
            job.status = "failed"
            job.error_message = f"Anomaly detection failed: {str(e)}"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            update_progress(job_id_str, "failed", 0, 0)
            return False
        update_progress(job_id_str, "Anomaly Detection", 100, 100)
        logger.info("Stage C complete", extra=log_ctx)
        
        # --- Stage D: LLM Category Classification ---
        log_ctx = {"job_id": job_id_str, "stage": "llm_classification"}
        logger.info("Stage D: Running LLM category classification", extra=log_ctx)
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
            logger.info(
                "LLM batch classification starting",
                extra={**log_ctx, "rows_to_classify": total_classify, "batch_size": 15},
            )
            batch_size = 15
            for i in range(0, total_classify, batch_size):
                batch = rows_to_classify[i:i+batch_size]
                processed_batch, was_successful = classify_categories_batch(batch)

                # If the batch failed completely, increment failed batches counter in Job
                if not was_successful:
                    job.llm_failed_batches += 1
                    db.commit()
                    logger.warning(
                        "LLM batch failed – falling back to 'Other'",
                        extra={**log_ctx, "batch_start": i, "llm_failed_batches": job.llm_failed_batches},
                    )

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
            logger.info("No rows required LLM classification", extra=log_ctx)

        logger.info("Stage D complete", extra=log_ctx)
        
        # --- Stage E: LLM Narrative Summary ---
        log_ctx = {"job_id": job_id_str, "stage": "summary_generation"}
        logger.info("Stage E: Generating narrative summary", extra=log_ctx)
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
            logger.error(
                "Stage E failed – using fallback summary",
                extra={**log_ctx, "error": str(e)},
            )
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
        logger.info("Stage E complete", extra=log_ctx)
        
        # --- Stage F: Finalization ---
        log_ctx = {"job_id": job_id_str, "stage": "finalization"}
        logger.info("Stage F: Persisting transactions and finalizing job", extra=log_ctx)
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
        logger.info(
            "Processing task completed successfully",
            extra={**log_ctx, "clean_count": clean_count},
        )
        return True

    except Exception as e:
        logger.exception(
            "Unexpected error in background worker",
            extra={"job_id": job_id_str, "stage": "unhandled_exception", "error": str(e)},
        )
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
            logger.error(
                "Failed to save error status to database",
                extra={"job_id": job_id_str, "stage": "error_handler", "error": str(db_err)},
            )
        return False
    finally:
        db.close()
