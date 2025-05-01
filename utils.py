# c:\Users\Christian\OneDrive - Arctaris Michigan Partners, LLC\Desktop\Bank Automation\Codes\Bank Statements\utils.py
import os
import sys
import logging
import argparse
import hashlib
import PyPDF2 # Keep for repair attempt
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Set, Any
import json

# Import ConfigManager for type hinting in ErrorRecovery if needed later
# from config_manager import ConfigManager # Not strictly needed now

# --- Logging Setup ---

def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None) -> str:
    """Set up logging configuration with rotation and proper formatting."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    if not log_file:
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"pdf_processor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    else:
        log_dir = os.path.dirname(log_file)
        if log_dir: os.makedirs(log_dir, exist_ok=True)

    log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Setup root logger
    root_logger = logging.getLogger()
    # Clear existing handlers if necessary (prevent duplicate logs in interactive sessions)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding='utf-8') # Specify encoding
        ]
    )

    logging.info(f"Logging initialized (Level: {log_level}, File: '{os.path.abspath(log_file)}')")
    return os.path.abspath(log_file)


# --- Argument Parsing ---

def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Process bank statement PDFs")

    parser.add_argument("--input", type=str, help="Input folder path (overrides config)")
    parser.add_argument("--output", type=str, help="Output folder path (overrides config)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without executing file operations")
    parser.add_argument("--show-preview", action="store_true",
                       help="Show detailed preview of changes by bank (only relevant with --dry-run)")
    parser.add_argument("--log-level", type=str,
                       choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                       help="Set logging level (overrides config)")
    parser.add_argument("--config", type=str, default="config.json",
                       help="Path to configuration file")
    parser.add_argument("--log-file", type=str,
                       help="Path to log file (defaults to logs/pdf_processor_TIMESTAMP.log)")
    parser.add_argument("--process-duplicates", action="store_true", default=False,
                       help="Process duplicate files instead of skipping them (first one encountered is kept by default)")
    parser.add_argument("--checklist-dir", type=str, default="checklists",
                       help="Directory to save checklist CSV files")
    parser.add_argument("--auto-confirm", action="store_true", default=False,
                       help="Skip the confirmation prompt and automatically process files (use with caution!)")
    # Add specific bank processing flags? Maybe later if needed.
    # parser.add_argument("--process-only", type=str, choices=["pnc", "berkshire", ...], help="Only process specific bank types")

    return parser.parse_args()


# --- PDF Verification ---

class PDFVerifier:
    """Verifies and validates PDF files before processing."""

    def __init__(self):
        """Initialize the PDF verifier."""
        self.verified_files: Set[str] = set()
        self.corrupt_files: Set[str] = set()

    def verify_pdf(self, file_path: str) -> Tuple[bool, str]:
        """
        Verify a PDF file is valid and readable.

        Args:
            file_path: Path to the PDF file.

        Returns:
            Tuple of (is_valid, message)
        """
        abs_path = os.path.abspath(file_path)
        if abs_path in self.verified_files: return True, "Already verified"
        if abs_path in self.corrupt_files: return False, "Known corrupt file"

        if not os.path.exists(file_path): return False, "File does not exist"
        if not os.path.isfile(file_path): return False, "Not a file"

        try:
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                self.corrupt_files.add(abs_path)
                return False, "Empty file"
            if file_size > 150 * 1024 * 1024:  # Increased limit slightly
                return False, "File potentially too large (>150MB)"

            with open(file_path, 'rb') as f:
                # Basic signature check
                signature = f.read(5)
                if signature != b'%PDF-':
                    # Allow common variations like whitespace before %PDF
                     f.seek(0)
                     start_bytes = f.read(20)
                     if b'%PDF-' not in start_bytes:
                        self.corrupt_files.add(abs_path)
                        return False, "Not a valid PDF (missing or misplaced signature)"

                # Reset pointer and try reading with PyPDF2
                f.seek(0)
                try:
                    # strict=False allows more tolerance for minor errors
                    pdf = PyPDF2.PdfReader(f, strict=False)
                    if not pdf.pages:
                        # Empty pages list might indicate corruption
                        logging.warning(f"PDF '{os.path.basename(file_path)}' reported 0 pages by PyPDF2.")
                        # Allow processing if it has size, maybe text extraction works
                        # self.corrupt_files.add(abs_path)
                        # return False, "PDF has no pages according to reader"

                except PyPDF2.errors.PdfReadError as e:
                     # Specific read errors often indicate corruption
                     logging.warning(f"PyPDF2 read error for {os.path.basename(file_path)}: {e}")
                     self.corrupt_files.add(abs_path)
                     return False, f"Invalid PDF structure: {e}"
                except Exception as e: # Catch other potential PyPDF2 init errors
                    logging.warning(f"Error initializing PyPDF2 reader for {os.path.basename(file_path)}: {e}")
                    self.corrupt_files.add(abs_path)
                    return False, f"Error reading PDF: {e}"

            # If basic checks passed
            self.verified_files.add(abs_path)
            return True, "PDF verified"

        except Exception as e:
            logging.error(f"Unexpected error verifying PDF {file_path}: {e}", exc_info=True)
            self.corrupt_files.add(abs_path)
            return False, f"Error during verification: {e}"

    def get_file_hash(self, file_path: str) -> Optional[str]:
        """Calculate MD5 hash of file to detect duplicates."""
        if not os.path.exists(file_path): return None
        try:
            hasher = hashlib.md5()
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk: break
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            logging.warning(f"Could not calculate hash for {file_path}: {e}")
            return None

    def find_duplicate_files(self, file_paths: List[str]) -> Dict[str, List[str]]:
        """Find duplicate files based on hash."""
        file_hashes: Dict[str, List[str]] = defaultdict(list)
        for file_path in file_paths:
            if not os.path.isfile(file_path): continue # Skip non-files
            file_hash = self.get_file_hash(file_path)
            if file_hash:
                file_hashes[file_hash].append(file_path)

        duplicates = {h: paths for h, paths in file_hashes.items() if len(paths) > 1}
        return duplicates


# --- Error Recovery ---

class ErrorRecovery:
    """Handles basic error recovery attempts, like simple PDF repair."""

    def __init__(self, config: Any): # Use Any to avoid circular import with ConfigManager
        """Initialize with configuration."""
        self.config = config # Store config instance
        self.error_counts = defaultdict(int)
        self.recovery_attempts = defaultdict(int)
        self.max_recovery_attempts = 1 # Limit repair attempts per file

    def can_attempt_recovery(self, file_path: str) -> bool:
        """Check if recovery can be attempted."""
        # Check global config setting first
        if not self.config.get("auto_recovery", True):
             return False
        return self.recovery_attempts[file_path] < self.max_recovery_attempts

    def record_recovery_attempt(self, file_path: str):
        """Record a recovery attempt."""
        self.recovery_attempts[file_path] += 1

    def attempt_pdf_repair(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """
        Attempt to repair a corrupted PDF by re-writing with PyPDF2.
        Returns (success, repaired_path_or_None)
        """
        if not self.can_attempt_recovery(file_path):
            return False, None

        self.record_recovery_attempt(file_path)
        repaired_path = f"{file_path}.repaired.pdf"
        logging.info(f"Attempting repair for {os.path.basename(file_path)} -> {os.path.basename(repaired_path)}")

        try:
            writer = PyPDF2.PdfWriter()
            with open(file_path, 'rb') as input_file:
                 # Be lenient reading the source
                reader = PyPDF2.PdfReader(input_file, strict=False)
                # Try adding pages individually
                pages_added = 0
                for page in reader.pages:
                    try:
                        writer.add_page(page)
                        pages_added += 1
                    except Exception as page_err:
                         logging.warning(f"Skipping corrupted page during repair of {os.path.basename(file_path)}: {page_err}")
                writer.remove_links() # Try removing potentially problematic links

            if pages_added == 0:
                 logging.warning(f"Repair failed for {os.path.basename(file_path)}: No pages could be added.")
                 return False, None

            # Save the repaired file
            with open(repaired_path, 'wb') as output_file:
                writer.write(output_file)

            logging.info(f"PDF repair successful, created {os.path.basename(repaired_path)} with {pages_added} pages.")
            return True, repaired_path

        except Exception as e:
            logging.error(f"PDF repair attempt failed for {os.path.basename(file_path)}: {e}", exc_info=True)
            # Clean up potentially invalid repaired file
            if os.path.exists(repaired_path):
                 try: os.remove(repaired_path)
                 except OSError: pass
            return False, None

    def record_error(self, error_type: str, filename: Optional[str] = None):
        """Record an error by type."""
        self.error_counts[error_type] += 1
        log_msg = f"Recorded error: {error_type}"
        if filename: log_msg += f" for file: {filename}"
        logging.debug(log_msg) # Log errors at debug level unless critical

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of errors and recovery attempts."""
        return {
            "total_errors_recorded": sum(self.error_counts.values()),
            "total_recovery_attempts": sum(self.recovery_attempts.values()),
            "error_counts_by_type": dict(self.error_counts)
        }

# --- Utility Classes ---

class EnhancedJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return json.JSONEncoder.default(self, obj)

# --- Function Definitions ---

# (Existing functions like setup_logging, parse_arguments, etc. follow) 