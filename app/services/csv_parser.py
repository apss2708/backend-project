import pandas as pd
import os
from typing import List, Dict, Any

REQUIRED_COLUMNS = {"txn_id", "date", "merchant", "amount", "currency", "status", "category", "account_id", "notes"}

class CSVParserError(Exception):
    pass

def parse_and_validate_csv(file_path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(file_path):
        raise CSVParserError(f"File not found: {file_path}")
        
    try:
        # Load CSV using Pandas as required
        df = pd.read_csv(file_path)
        
        if df.empty:
            raise CSVParserError("CSV file is empty")
            
        # Normalize column headers: strip whitespace and lowercase
        df.columns = [str(col).strip().lower() for col in df.columns]
        
        # Check required columns
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise CSVParserError(f"Missing required columns: {', '.join(missing)}")
            
        # Replace NaN/null with empty strings for standard parsing behavior
        df = df.fillna("")
        
        # Convert to dictionary list matching records
        return df.to_dict(orient="records")
    except Exception as e:
        if isinstance(e, CSVParserError):
            raise e
        raise CSVParserError(f"CSV ingestion failed: {str(e)}")
