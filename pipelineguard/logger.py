import logging
import json
import os
from datetime import datetime, timezone

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "message": record.getMessage(),
            "name": record.name
        }
        
        # Merge extra attributes
        if hasattr(record, "variant"):
            log_record["variant"] = record.variant
        if hasattr(record, "event_type"):
            log_record["event_type"] = record.event_type
        if hasattr(record, "latency_ms"):
            log_record["latency_ms"] = record.latency_ms
        if hasattr(record, "outcome"):
            log_record["outcome"] = record.outcome
        if hasattr(record, "error"):
            log_record["error"] = record.error
            
        return json.dumps(log_record)

def setup_logger(name="pipelineguard"):
    logger = logging.getLogger(name)
    
    # Don't add handlers if they already exist
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = JsonFormatter()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)
    logger.setLevel(level)
    
    return logger

# Create the default logger
logger = setup_logger()
