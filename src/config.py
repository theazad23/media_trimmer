# config.py
import logging
import os
from typing import Optional
from pathlib import Path

class ColorFormatter(logging.Formatter):
    """Custom formatter with colors and structured output."""
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_white = "\x1b[1;37m"
    reset = "\x1b[0m"
    
    FORMATS = {
        logging.DEBUG: grey,
        logging.INFO: grey,
        logging.WARNING: yellow,
        logging.ERROR: red,
        logging.CRITICAL: red
    }
    
    def format(self, record):
        # Add color to level names
        color = self.FORMATS.get(record.levelno)
        if record.levelno == logging.INFO and getattr(record, 'highlight', False):
            color = self.bold_white
            
        record.levelname = f"{color}{record.levelname}{self.reset}"
        
        # Add visual separators for different message types
        if getattr(record, 'separator', False):
            record.msg = f"\n{'='*80}\n{record.msg}\n{'='*80}"
        elif getattr(record, 'subseparator', False):
            record.msg = f"\n{'-'*50}\n{record.msg}"
            
        return super().format(record)

def setup_logging():
    """Configure logging for the application."""
    level = logging.DEBUG if os.environ.get('DEBUG') else logging.INFO
    
    # Configure root logger
    logging.basicConfig(
        level=level,
        format='%(message)s' if level == logging.INFO else '%(levelname)s: %(message)s'
    )
    
    # Add a debug handler if DEBUG is set
    if level == logging.DEBUG:
        debug_handler = logging.FileHandler('debug.log')
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        logging.getLogger().addHandler(debug_handler)