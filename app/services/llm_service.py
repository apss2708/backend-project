import time
import json
import logging
import re
from typing import List, Dict, Any, Tuple, Optional
from decimal import Decimal
from app.core.config import settings

logger = logging.getLogger("app.services.llm")

try:
    import google.generativeai as genai
    HAS_GEMINI_SDK = True
except ImportError:
    HAS_GEMINI_SDK = False

try:
    from openai import OpenAI
    HAS_OPENAI_SDK = True
except ImportError:
    HAS_OPENAI_SDK = False

ALLOWED_CATEGORIES = {"Food", "Shopping", "Travel", "Transport", "Utilities", "Cash Withdrawal", "Entertainment", "Other"}

def extract_json(text: str) -> str:
    match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
    if match:
        return match.group(0)
    return text

def call_llm(prompt: str, json_response: bool = True, gemini_fallback: bool = False) -> str:
    provider = settings.LLM_PROVIDER.lower()
    api_key = settings.LLM_API_KEY
    
    if not api_key:
        logger.warning("LLM API Key is missing. Graceful fallback mode active.")
        raise ValueError("LLM API Key not configured")
        
    if provider == "gemini":
        if not HAS_GEMINI_SDK:
            raise ValueError("google-generativeai SDK is not installed")
        
        genai.configure(api_key=api_key)
        
        # Determine model to use
        model_name = settings.LLM_MODEL
        if not model_name:
            model_name = "gemini-1.5-flash" if gemini_fallback else "gemini-2.5-flash"
            
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            # If default gemini-2.5-flash failed, fall back to gemini-1.5-flash
            if not gemini_fallback and not settings.LLM_MODEL:
                logger.warning(f"Gemini call to gemini-2.5-flash failed: {str(e)}. Retrying with fallback model gemini-1.5-flash.")
                return call_llm(prompt, json_response=json_response, gemini_fallback=True)
            raise e
            
    elif provider == "openai":
        if not HAS_OPENAI_SDK:
            raise ValueError("openai SDK is not installed")
            
        client = OpenAI(api_key=api_key)
        model_name = settings.LLM_MODEL or "gpt-4o-mini"
        
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"} if json_response else None
        )
        return response.choices[0].message.content
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")

def classify_categories_batch(batch: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
    # Returns (processed_batch, was_successful)
    if not settings.LLM_API_KEY:
        # Fallback category assignment
        for item in batch:
            item["llm_category"] = "Other"
            item["llm_raw_response"] = "Fallback: LLM API key not configured"
            item["llm_failed"] = True
        return batch, False
        
    tx_list = []
    for item in batch:
        tx_list.append({
            "index": item["temp_index"],
            "merchant": item["merchant"],
            "amount": float(item["amount"]),
            "currency": item["currency"],
            "notes": item["notes"] or ""
        })
        
    prompt = f"""You are a financial transaction classification assistant.
Classify the following batch of transactions into one of these allowed categories:
[Food, Shopping, Travel, Transport, Utilities, Cash Withdrawal, Entertainment, Other]

Input JSON:
{json.dumps(tx_list, indent=2)}

Return ONLY a valid JSON array of objects, containing:
[
  {{"index": <index>, "category": "<allowed_category>"}}
]
Do not include any explanation or markdown formatting other than the JSON block."""

    # Retry loop: max 3 retries, exponential backoff
    for attempt in range(1, 4):
        try:
            raw_response = call_llm(prompt, json_response=True)
            cleaned_json = extract_json(raw_response)
            classifications = json.loads(cleaned_json)
            
            class_map = {item["index"]: item["category"] for item in classifications if "index" in item}
            
            for item in batch:
                idx = item["temp_index"]
                cat = class_map.get(idx, "Other")
                normalized_cat = cat.strip().title() if cat else "Other"
                if normalized_cat not in ALLOWED_CATEGORIES:
                    normalized_cat = "Other"
                item["llm_category"] = normalized_cat
                item["llm_raw_response"] = raw_response
                item["llm_failed"] = False
                
            return batch, True
        except Exception as e:
            logger.error(f"LLM Classification batch attempt {attempt} failed: {str(e)}")
            if attempt < 3:
                time.sleep(2 ** attempt)
            else:
                # All 3 retries failed -> mark as failed
                for item in batch:
                    item["llm_category"] = "Other"
                    item["llm_raw_response"] = f"Error after 3 retries: {str(e)}"
                    item["llm_failed"] = True
                return batch, False

def validate_summary_json(data: Dict[str, Any]) -> bool:
    required_keys = {"total_spend_inr", "total_spend_usd", "top_merchants", "anomaly_count", "narrative", "risk_level"}
    if not required_keys.issubset(data.keys()):
        return False
    if not isinstance(data["top_merchants"], list):
        return False
    if data["risk_level"] not in {"low", "medium", "high"}:
        return False
    try:
        float(data["total_spend_inr"])
        float(data["total_spend_usd"])
        int(data["anomaly_count"])
    except (ValueError, TypeError):
        return False
    return True

def generate_narrative_summary(metrics: Dict[str, Any]) -> Dict[str, Any]:
    fallback_result = {
        "total_spend_inr": metrics["total_spend_inr"],
        "total_spend_usd": metrics["total_spend_usd"],
        "top_merchants": metrics["top_merchants"],
        "anomaly_count": metrics["anomaly_count"],
        "narrative": "LLM narrative summary fallback. Transactions processed successfully.",
        "risk_level": "medium" if metrics["anomaly_count"] > 0 else "low"
    }

    if not settings.LLM_API_KEY:
        return fallback_result
        
    prompt = f"""You are a financial analyst. Analyze this summary of a transaction processing job and generate a narrative summary and risk assessment.

Job Metrics:
- Total transactions: {metrics['total_count']}
- Cleaned transactions: {metrics['clean_count']}
- Total Spend INR: {metrics['total_spend_inr']}
- Total Spend USD: {metrics['total_spend_usd']}
- Spend by Category: {metrics['category_spend']}
- Top Merchants: {metrics['top_merchants']}
- Anomalies Count: {metrics['anomaly_count']}
- Anomaly Details: {metrics['anomaly_details']}

Return ONLY a strict JSON object with:
{{
  "total_spend_inr": <number>,
  "total_spend_usd": <number>,
  "top_merchants": [<merchant_names>],
  "anomaly_count": <number>,
  "narrative": "<2-3 sentence narrative summary of spending habits, trends, and anomalies>",
  "risk_level": "<low, medium, or high depending on anomalies and suspicious activity>"
}}
Do not include any explanation or markdown formatting other than the JSON block."""

    for attempt in range(1, 4):
        try:
            raw_response = call_llm(prompt, json_response=True)
            cleaned_json = extract_json(raw_response)
            data = json.loads(cleaned_json)
            
            # Strict validation
            if not validate_summary_json(data):
                raise ValueError("JSON response failed strict key/type validation check")
                
            return {
                "total_spend_inr": Decimal(str(data["total_spend_inr"])),
                "total_spend_usd": Decimal(str(data["total_spend_usd"])),
                "top_merchants": data["top_merchants"],
                "anomaly_count": int(data["anomaly_count"]),
                "narrative": str(data["narrative"]),
                "risk_level": str(data["risk_level"])
            }
        except Exception as e:
            logger.error(f"LLM Narrative Summary attempt {attempt} failed: {str(e)}")
            if attempt < 3:
                time.sleep(2 ** attempt)
            else:
                return fallback_result
