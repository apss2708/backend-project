import csv
import os
from typing import List, Dict, Any

REQUIRED_COLUMNS = {"txn_id", "date", "merchant", "amount", "currency", "status", "category", "account_id", "notes"}

class CSVParserError(Exception):
    pass

def parse_and_validate_csv(file_path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(file_path):
        raise CSVParserError(f"File not found: {file_path}")
        
    try:
        with open(file_path, mode="r", encoding="utf-8-sig") as f:
            # Read first few bytes to sniff delimiter or check format
            sample = f.read(2048)
            f.seek(0)
            
            # Simple validation to ensure it looks like a CSV
            if not sample or ("," not in sample and ";" not in sample and "\t" not in sample):
                raise CSVParserError("File does not appear to be a valid CSV")
                
            try:
                dialect = csv.Sniffer().sniff(sample)
            except Exception:
                dialect = csv.excel
                
            reader = csv.DictReader(f, dialect=dialect)
            
            if not reader.fieldnames:
                raise CSVParserError("CSV file is empty or missing headers")
                
            # Normalize headers
            raw_headers = reader.fieldnames
            normalized_headers = [h.strip().lower().replace(" ", "_") for h in raw_headers]
            
            # Map normalized names to raw names
            header_mapping = dict(zip(normalized_headers, raw_headers))
            
            # Check if all required columns exist
            missing_columns = REQUIRED_COLUMNS - set(normalized_headers)
            if missing_columns:
                raise CSVParserError(f"Missing required columns: {', '.join(missing_columns)}")
                
            records = []
            for row in reader:
                # Build dict using normalized keys
                record = {}
                for key in REQUIRED_COLUMNS:
                    raw_key = header_mapping.get(key)
                    val = row.get(raw_key)
                    record[key] = val.strip() if val is not None else ""
                records.append(record)
                
            return records
            
    except csv.Error as e:
        raise CSVParserError(f"Malformed CSV syntax: {str(e)}")
    except Exception as e:
        if isinstance(e, CSVParserError):
            raise e
        raise CSVParserError(f"An unexpected error occurred during CSV parsing: {str(e)}")
