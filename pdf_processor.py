# c:\Users\Christian\OneDrive - Arctaris Michigan Partners, LLC\Desktop\Bank Automation\Codes\Bank Statements\pdf_processor.py
import os
# import PyPDF2 # Replaced with pdfplumber
import pdfplumber # Added
import re
import logging
from typing import Tuple, Optional, Dict, Type, List # Added List
from collections import defaultdict

# Assuming these are in sibling modules now
from config_manager import ConfigManager
from statement_info import StatementInfo
from bank_strategies import (
    BankStrategy, PNCStrategy, BerkshireStrategy,
    CambridgeStrategy, BankUnitedStrategy, UnlabeledStrategy
)

class PDFProcessor:
    """Processes PDF files to extract account information using bank-specific strategies."""

    # Map bank identifiers (lowercase) to their strategy classes
    STRATEGY_MAP: Dict[str, Type[BankStrategy]] = {
        "pnc": PNCStrategy,
        "berkshire": BerkshireStrategy,
        "bankunited": BankUnitedStrategy,
        "cambridge": CambridgeStrategy,
        # Add other mappings here
        "unlabeled": UnlabeledStrategy # Default/fallback
    }

    # Bank indicators for content-based identification (used if filename fails)
    # More comprehensive list now, matching UnlabeledStrategy
    BANK_INDICATORS = {
        "PNC": [
            "PNC BANK", "WWW.PNC.COM", "PNC.COM", "PNCBANK.COM", "PNC FINANCIAL SERVICES",
            "PNC VIRTUAL WALLET", "PNC BANK, N.A.", "PNC ONLINE BANKING", "© PNC BANK", "PNC"
        ],
        "Berkshire": [
            "BERKSHIRE BANK", "BERKSHIREBANK.COM", "WWW.BERKSHIREBANK.COM", "BERKSHIREBANKONLINE",
            "BERKBANK", "BERK BANK", "MYBANKNOW", "MEMBER FDIC BERKSHIRE", "BERKSHIRE, N.A.", "BERKSHIRE"
        ],
        "BankUnited": [
            "BANKUNITED", "BANK UNITED", "BANKUNITED.COM", "WWW.BANKUNITED.COM", "BANKUNITEDONLINE",
            "BANKUNITED, N.A.", "BKU", "BU ONLINE", "WWW.BANKUNITEDFL.COM"
        ],
        "Cambridge": [
            "CAMBRIDGE SAVINGS", "CAMBRIDGE SAVINGS BANK", "CAMBRIDGESAVINGS.COM", "WWW.CAMBRIDGESAVINGS.COM",
            "CSB", "CAMBRIDGESAVINGSBANK", "CAMBRIDGE BANK", "CAMBRIDGE, MA", "CSB CUSTOMER SERVICE"
        ]
    }

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.extraction_stats = defaultdict(int)
        # Cache removed, filename logic simplified below

    def _extract_text_with_pdfplumber(self, file_path: str, filename: str) -> Tuple[List[str], bool]:
        """Extracts text from PDF using pdfplumber, returning lines and success status."""
        lines = []
        text_extraction_success = False
        full_text = ""
        try:
            with pdfplumber.open(file_path) as pdf:
                if not pdf.pages:
                    logging.warning(f"pdfplumber found no pages in: {filename}")
                    self.extraction_stats["empty_pdf"] += 1
                    return lines, text_extraction_success # Return empty if no pages

                max_pages_to_scan = min(len(pdf.pages), self.config_manager.get("pdf_scan_max_pages", 10)) # Configurable max pages
                logging.info(f"Extracting text from up to {max_pages_to_scan} pages in {filename} using pdfplumber")

                for i, page in enumerate(pdf.pages):
                    if i >= max_pages_to_scan:
                        logging.debug(f"Stopping text extraction at page {i} (limit reached) for {filename}")
                        break
                    try:
                        page_text = page.extract_text(x_tolerance=2, y_tolerance=2) # Tolerances help with layout
                        if page_text:
                            full_text += page_text + "\n"
                            if not text_extraction_success:
                                text_extraction_success = True # Mark success on first good page
                                sample = page_text[:150].replace('\n', ' ') + ("..." if len(page_text) > 150 else "")
                                logging.info(f"First successful text extraction (page {i+1}, {len(page_text)} chars) from {filename}. Sample: '{sample}'")
                        else:
                             logging.debug(f"No text extracted by pdfplumber from page {i+1} of {filename}")
                    except Exception as page_ex:
                        logging.warning(f"pdfplumber error extracting text from page {i+1} of {filename}: {page_ex}")

            if text_extraction_success:
                lines = full_text.splitlines()
                logging.info(f"pdfplumber successfully extracted {len(full_text)} characters ({len(lines)} lines) from {filename}")
            else:
                logging.warning(f"pdfplumber failed to extract any text from {filename}")
                self.extraction_stats["text_extraction_failed"] += 1

        except pdfplumber.exceptions.PDFSyntaxError as pdf_err:
            logging.error(f"Corrupted or invalid PDF for pdfplumber: {filename}. Error: {pdf_err}")
            self.extraction_stats["corrupted_pdf"] += 1
        except PermissionError:
            logging.error(f"Permission denied accessing file for pdfplumber: {file_path}")
            self.extraction_stats["permission_error"] += 1
        except Exception as read_ex:
             logging.error(f"Unexpected error reading PDF with pdfplumber '{filename}': {read_ex}", exc_info=True)
             self.extraction_stats["read_error"] += 1

        return lines, text_extraction_success

    def _identify_bank_from_content(self, text_content: str, filename: str) -> Optional[str]:
        """Identifies the most likely bank key based on keywords in text content."""
        if not text_content:
            return None

        text_upper = text_content.upper()
        bank_scores = {bank: 0 for bank in self.BANK_INDICATORS.keys()}
        min_score_threshold = self.config_manager.get("bank_id_min_score", 2) # Configurable threshold

        # Check for all indicators and count occurrences
        for bank, indicators in self.BANK_INDICATORS.items():
            for indicator in indicators:
                if indicator in text_upper:
                    occurrences = text_upper.count(indicator)
                    bank_scores[bank] += occurrences
                    logging.debug(f"Found indicator '{indicator}' ({occurrences}x) for {bank} in {filename}")

        # Log findings for debugging
        positive_scores = {b: s for b, s in bank_scores.items() if s > 0}
        if positive_scores:
            logging.debug(f"Content-based bank scores for {filename}: {positive_scores}")
        else:
            logging.debug(f"No bank indicators found in content for {filename}")
            return None

        # Determine most likely bank if score is above threshold
        max_score = 0
        detected_bank = None
        sorted_scores = sorted(bank_scores.items(), key=lambda item: item[1], reverse=True)

        if sorted_scores and sorted_scores[0][1] >= min_score_threshold:
             detected_bank = sorted_scores[0][0] # Bank name (e.g., "PNC")
             max_score = sorted_scores[0][1]
             logging.info(f"Identified bank '{detected_bank}' from content analysis of {filename} with score {max_score} (Threshold: {min_score_threshold})")
             return detected_bank.lower() # Return lowercase key
        else:
             logging.info(f"Content analysis did not yield a bank identification above threshold {min_score_threshold} for {filename}. Top score: {sorted_scores[0] if sorted_scores else 'N/A'}")
             return None

    def process_pdf(self, file_path: str) -> Tuple[Optional[StatementInfo], Optional[BankStrategy]]:
        """
        Process a PDF file: Extract text, identify bank (filename -> content), execute strategy.
        Returns a tuple of (StatementInfo, instantiated BankStrategy) or (None, None).
        """
        filename = os.path.basename(file_path)
        logging.debug(f"Processing PDF: {filename}")

        if not os.path.exists(file_path):
            logging.error(f"File not found: {file_path}")
            self.extraction_stats["file_not_found"] += 1
            return None, None

        try:
            logging.info(f"Processing PDF: {filename}")

            # Create StatementInfo object first
            statement_info = StatementInfo()
            # Assign the original filename
            statement_info.original_filename = filename

            # 1. Extract text using pdfplumber
            extracted_text, num_pages = self._extract_text_with_pdfplumber(file_path, filename)

            # 2. Identify Bank Type
            bank_key = None
            # Try filename first (quick check)
            filename_bank_key = self._identify_bank_key_from_filename(filename)
            if filename_bank_key != "unlabeled":
                logging.info(f"Preliminary bank identification via filename '{filename}': {filename_bank_key}")
                bank_key = filename_bank_key
            else:
                logging.info(f"Filename did not yield specific bank for '{filename}'. Analyzing content.")
                # If filename fails, try content analysis
                if extracted_text:
                    content_bank_key = self._identify_bank_from_content(extracted_text, filename)
                    if content_bank_key:
                        bank_key = content_bank_key
                    else:
                         bank_key = "unlabeled" # Stick with unlabeled if content fails too
                else:
                     logging.warning(f"Cannot perform content analysis for bank ID on {filename} due to text extraction failure.")
                     bank_key = "unlabeled" # Fallback if no text

            logging.info(f"Final determined bank key for {filename}: '{bank_key}'")
            strategy_class = self.STRATEGY_MAP.get(bank_key, UnlabeledStrategy)
            strategy = strategy_class(self.config_manager) # Instantiate the determined strategy

            # If the strategy is UnlabeledStrategy, return None for info immediately
            # This signals FileManager not to rename or move the file.
            if strategy_class is UnlabeledStrategy:
                logging.info(f"File '{filename}' identified as Unlabeled. Skipping further processing and renaming/moving.")
                self.extraction_stats["unlabeled_identified"] += 1 # Track specifically identified unlabeled
                # Return None for StatementInfo, but the strategy instance for potential logging
                return None, strategy

            # --- Proceed only if it's NOT UnlabeledStrategy ---

            # 3. Extract Information using the selected strategy
            try:
                # Pass extracted lines to the strategy
                # The strategy should handle empty lines if text_extracted is False
                strategy.extract_info(extracted_text, statement_info)

                # The strategy should set statement_info.bank_type correctly now.
                # UnlabeledStrategy might refine the bank_type based on its *own* internal logic if needed.
                if not statement_info.bank_type or statement_info.bank_type == "Unlabeled":
                     # If the strategy failed to set a specific bank type, log a warning
                     if bank_key != "unlabeled": # Only warn if we initially thought it was a specific bank
                         logging.warning(f"Strategy {strategy.__class__.__name__} did not assign a specific bank type for {filename}, despite initial key '{bank_key}'.")
                     statement_info.bank_type = strategy.get_bank_name() # Ensure it's at least set to the strategy's type

            except Exception as strategy_ex:
                logging.error(f"Error during {strategy.__class__.__name__} execution for {filename}: {strategy_ex}", exc_info=True)
                self.extraction_stats["strategy_error"] += 1
                # Keep potentially partial info, ensure bank type is set from strategy instance
                statement_info.bank_type = strategy.get_bank_name()
                # Return strategy instance even on failure for potential logging/reporting
                # Return None for StatementInfo here to signal failure to FileManager
                return None, strategy # Modified: Ensure StatementInfo is None on failure

            # 4. Final Check and Return
            # Consider a successful extraction if bank type is not Unlabeled *and* essential info exists
            # (e.g., account number or name, date). This check might need refinement.
            is_successful = (
                statement_info and
                statement_info.bank_type and
                statement_info.bank_type != "Unlabeled" and
                (statement_info.account_name or statement_info.account_number) and
                statement_info.date
            )

            if is_successful:
                logging.info(f"Extraction successful ({filename}): Bank={statement_info.bank_type}, Account='{statement_info.account_name}', AccNum='{statement_info.account_number}', Date='{statement_info.date.strftime('%Y-%m-%d') if statement_info.date else 'N/A'}'")
                self.extraction_stats["success"] += 1
                return statement_info, strategy
            else:
                log_level = logging.WARNING if statement_info.bank_type != "Unlabeled" else logging.INFO
                logging.log(log_level, f"Strategy {strategy.__class__.__name__} did not extract sufficient info for {filename}. Result: Bank='{statement_info.bank_type}', Account='{statement_info.account_name}', AccNum='{statement_info.account_number}', Date='{statement_info.date.strftime('%Y-%m-%d') if statement_info.date else 'N/A'}'")
                if statement_info.bank_type != "Unlabeled":
                     self.extraction_stats["extraction_failed"] += 1
                else:
                     self.extraction_stats["unlabeled_unidentified"] += 1
                # Return strategy instance even on failure for potential logging/reporting
                return None, strategy

        except Exception as e:
            logging.error(f"Error processing PDF: {filename}. Error: {e}", exc_info=True)
            self.extraction_stats["processing_error"] += 1
            return None, None

    def _identify_bank_key_from_filename(self, filename: str) -> str:
        """
        Quickly identify bank type key (lowercase string) from known filename patterns.
        Returns 'unlabeled' if no pattern matches.
        """
        filename_lower = filename.lower()
        # Using a simple dict lookup for cleaner/faster checks of specific prefixes/substrings
        filename_patterns = {
            "cambridge": ["online statements_", "online_statements"],
            "bankunited": ["dxweb"],
            "berkshire": ["newstatement", "new_statement"],
            "pnc": ["statement_"] # Assuming statement_ is primarily PNC based on previous logic
        }

        for bank, patterns in filename_patterns.items():
            for pattern in patterns:
                # Check for exact prefix or substring presence
                if pattern.endswith('_') and filename_lower.startswith(pattern):
                    logging.debug(f"Identified bank '{bank}' from filename prefix pattern '{pattern}': {filename}")
                    return bank
                elif not pattern.endswith('_') and pattern in filename_lower:
                    logging.debug(f"Identified bank '{bank}' from filename substring pattern '{pattern}': {filename}")
                    return bank

        # Add regex checks only if simple patterns fail
        regex_patterns = {
             "pnc": [r'pnc.*statement', r'statement.*pnc', r'virtual.*wallet', r'pnc.*account'],
             "berkshire": [r'berk.*bank', r'berkshire.*statement', r'berk.*statement', r'mybanknow'],
             "bankunited": [r'bankunited', r'bank.*united', r'statement.*united', r'bu.*online'],
             "cambridge": [r'cambridge.*savings', r'cambridge.*bank', r'csb.*statement', r'cambridge.*statement']
        }

        for bank, patterns in regex_patterns.items():
            for pattern in patterns:
                # Avoid redundant checks if already found by simple patterns
                if re.search(pattern, filename_lower):
                    # Don't log again if simple pattern already found it
                    # if bank not in [b for b, p_list in filename_patterns.items() if any(p in filename_lower for p in p_list)]:
                    logging.debug(f"Identified bank '{bank}' from filename regex pattern '{pattern}': {filename}")
                    return bank

        # Check if bank name itself is in the filename (last resort for filename check)
        for bank_key in self.STRATEGY_MAP.keys():
            if bank_key != "unlabeled" and bank_key in filename_lower:
                 logging.debug(f"Identified bank '{bank_key}' from filename presence: {filename}")
                 return bank_key


        logging.debug(f"Could not identify specific bank from filename patterns for {filename}.")
        return "unlabeled"  # Default if no match

    def get_extraction_stats(self) -> Dict[str, int]:
        """Get statistics about PDF extractions."""
        return dict(self.extraction_stats) 