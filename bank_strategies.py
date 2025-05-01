# c:\\Users\\Christian\\OneDrive - Arctaris Michigan Partners, LLC\\Desktop\\Bank Automation\\Codes\\Bank Statements\\bank_strategies.py
import re
import os
from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import logging

# Assuming these are in sibling modules now
from statement_info import StatementInfo
from config_manager import ConfigManager

# --- Helper Functions (Consider moving to utils.py later) ---

def parse_date(date_str: Optional[str], formats: List[str]) -> Optional[datetime]:
    """Helper to parse dates with multiple potential formats."""
    if not date_str:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except (ValueError, TypeError):
            continue
    logging.debug(f"Could not parse date string '{date_str}' with formats {formats}")
    return None

def sanitize_filename(filename: Optional[str]) -> str:
    """Sanitize a filename to be safe for use in file systems."""
    if not filename:
        return "sanitized_filename"
    # Remove or replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
    # Consolidate whitespace (including newlines etc.) to single space
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    # Remove leading/trailing problematic chars like spaces, periods, underscores
    sanitized = sanitized.strip(' _.')
    # Ensure not empty after sanitization
    return sanitized if sanitized else "sanitized_filename"


# --- Base Strategy ---

class BankStrategy(ABC):
    """Abstract base class for bank-specific processing strategies."""

    def __init__(self, config: ConfigManager):
        self.config = config

    @abstractmethod
    def extract_info(self, lines: List[str], statement_info: StatementInfo):
        """Extract bank-specific information into the StatementInfo object."""
        # Subclasses MUST set statement_info.bank_type
        pass

    @abstractmethod
    def get_filename(self, statement_info: StatementInfo) -> str:
        """Generate the final filename based on the extracted info."""
        pass

    @abstractmethod
    def get_subfolder_path(self, statement_info: StatementInfo) -> str:
        """Generate the subfolder path relative to the base output directory."""
        pass

    @abstractmethod
    def get_bank_name(self) -> str:
        """Return the canonical name of the bank this strategy handles."""
        pass

    # Make helpers available to subclasses (could also be static methods or moved to utils)
    def _parse_date(self, date_str: Optional[str], formats: List[str]) -> Optional[datetime]:
        return parse_date(date_str, formats)

    def _sanitize_filename(self, filename: Optional[str]) -> str:
        return sanitize_filename(filename)


# --- Concrete Strategies ---

class PNCStrategy(BankStrategy):
    """Strategy for processing PNC Bank statements."""

    def get_bank_name(self) -> str:
        return "PNC"

    def extract_info(self, lines: List[str], statement_info: StatementInfo):
        statement_info.bank_type = self.get_bank_name()
        pnc_mappings = self.config.get_account_mappings("pnc")
        arc_impact_mappings = self.config.get_account_mappings("pnc_arc_impact_last4")

        # Pre-compile regex patterns for efficiency
        account_pattern = re.compile(r'Account Number:\s*(\d+-\d+-\d+|\d+)', re.IGNORECASE)
        account_last4_pattern = re.compile(r'(?:Account|Acct)[^0-9]*(?:[0-9]+-){0,2}([0-9]{4})', re.IGNORECASE)
        date_pattern = re.compile(r'For the Period .*?(?:through|to)\s*(\d{1,2}/\d{1,2}/\d{2,4})', re.IGNORECASE)
        # ... (Keep other specific patterns as needed for PNC)
        account_name_patterns = [
            re.compile(r'ARCTARIS\s+PRODUCT\s+DEV(?:ELOPMENT)?\s+([IVX]+)', re.IGNORECASE),
            re.compile(r'ARCTARIS\s+PRODUCT\s+DEV(?:ELOPMENT)?\s+(\d+)', re.IGNORECASE),
            re.compile(r'PRODUCT\s+DEV(?:ELOPMENT)?\s+([IVX]+|[0-9]+)', re.IGNORECASE),
            re.compile(r'PHASE\s+([0-9]+[A-Z]?)\s+HOLDINGS', re.IGNORECASE)
        ]
        fund_patterns = [
            re.compile(r'(SUB\s*[-]?\s*CDE\s+[0-9]+\s+LLC)', re.IGNORECASE),
            re.compile(r'(?:Sub-)?CDE[^A-Za-z0-9]*([0-9]+)[^A-Za-z0-9]*LLC', re.IGNORECASE),
            re.compile(r'((?:Sub-)?CDE[^A-Za-z0-9]*[0-9]+[^A-Za-z0-9]*LLC)', re.IGNORECASE),
            re.compile(r'(ARCTARIS\s+PRODUCT\s+DEV(?:ELOPMENT)?\s+(?:[IVX]+|[0-9]+))', re.IGNORECASE),
            re.compile(r'(ARCTARIS[^A-Za-z0-9]*(?:[A-Za-z0-9\s\-]+)[^A-Za-z0-9]*LLC)', re.IGNORECASE),
            # Generic LLC finder - use carefully
            re.compile(r'^([A-Za-z0-9\s,.\-]+)\s+LLC', re.IGNORECASE), # Match start of line LLC
            re.compile(r'ARCTARIS\s+([A-Za-z0-9\s,.\-]+?)(?:\s+LLC|$)', re.IGNORECASE),
            re.compile(r'([A-Za-z0-9\s,.\-]+FUND[A-Za-z0-9\s,.\-]*)', re.IGNORECASE),
            re.compile(r'([A-Za-z]+\s+EAST\s+COAST[A-Za-z\s]+)', re.IGNORECASE),
            re.compile(r'([A-Za-z]+\s+OPPORTUNITY\s+ZONE[A-Za-z\s]+)', re.IGNORECASE)
        ]
        arc_impact_pattern = re.compile(r'(ARC[\s-]IMPACT\s+PROGRAM(?:\s+(?:ERIE|SWPA|LIMA|PITTSBURGH|BUFFALO|HARTFORD|CUYAHOGA|CT))?(?:\s+LLC)?)', re.IGNORECASE)

        account_found = False
        fund_found = False
        date_found = False

        # Try mapping from filename first (might be redundant if processor handles it)
        # This provides a fallback if text extraction is poor but filename is good.
        if statement_info.original_filename:
            filename_lower = statement_info.original_filename.lower()
            match = re.search(r'statement_(\d+)_?', filename_lower)
            if match:
                account_id = match.group(1)
                logging.debug(f"PNCStrategy: Found account ID {account_id} from filename.")
                statement_info.account_number = account_id
                account_found = True
                if account_id in pnc_mappings:
                    statement_info.account_name = pnc_mappings[account_id]
                    logging.debug(f"PNCStrategy: Mapped account name '{statement_info.account_name}' from full ID in filename.")
                    fund_found = True
                else:
                    last4 = account_id[-4:]
                    if last4 in arc_impact_mappings:
                        statement_info.account_name = arc_impact_mappings[last4]
                        logging.debug(f"PNCStrategy: Mapped account name '{statement_info.account_name}' from last4 ({last4}) in filename.")
                        fund_found = True

        # Process lines if needed
        logging.debug(f"PNCStrategy: Starting line processing for '{statement_info.original_filename}'. Found so far: Acc={account_found}, Fund={fund_found}, Date={date_found}")
        for i, line in enumerate(lines):
            if not line.strip(): continue # Skip empty lines
            logging.log(logging.DEBUG - 5 , f"PNC Line {i+1}: {line.strip()}") # Very verbose logging

            # Stop processing if all info is found
            if account_found and fund_found and date_found:
                logging.debug("PNCStrategy: All required info found, stopping line processing.")
                break

            # Extract account number
            if not account_found:
                match = account_pattern.search(line)
                if match:
                    full_account = match.group(1).replace('-', '')
                    statement_info.account_number = full_account
                    logging.debug(f"PNCStrategy: Found full account '{full_account}' on line {i+1}.")
                    account_found = True
                    # Check mapping again even if found in filename (content is more reliable)
                    if full_account in pnc_mappings:
                        statement_info.account_name = pnc_mappings[full_account]
                        logging.debug(f"PNCStrategy: Mapped name '{statement_info.account_name}' from full account in content.")
                        fund_found = True # Assume mapping implies fund name found
                    else:
                        last4 = full_account[-4:]
                        if last4 in arc_impact_mappings:
                            statement_info.account_name = arc_impact_mappings[last4]
                            logging.debug(f"PNCStrategy: Mapped name '{statement_info.account_name}' from last4 ({last4}) in content.")
                            fund_found = True
                else: # Only try last 4 if full pattern failed on this line
                    match = account_last4_pattern.search(line)
                    if match:
                        last4 = match.group(1)
                        # Don't overwrite full account if already found, but use last4 for lookup
                        if not statement_info.account_number:
                            statement_info.account_number = f"xxxx{last4}" # Placeholder
                            logging.debug(f"PNCStrategy: Found last 4 digits '{last4}' on line {i+1} (no full account yet).")
                        account_found = True # Mark as found even if only last 4
                        # Check mapping based on last 4 if fund not already found
                        if not fund_found and last4 in arc_impact_mappings:
                            statement_info.account_name = arc_impact_mappings[last4]
                            logging.debug(f"PNCStrategy: Mapped name '{statement_info.account_name}' from last4 ({last4}) in content (after finding last4).")
                            fund_found = True

            # Extract fund name using various patterns
            if not fund_found:
                 # Look for ARC-IMPACT first
                match = arc_impact_pattern.search(line)
                    if match:
                        fund_name = match.group(1)
                    fund_name = re.sub(r'ARC[\s-]IMPACT', 'ARC-IMPACT', fund_name, flags=re.IGNORECASE).upper().strip()
                        statement_info.account_name = fund_name
                    logging.debug(f"PNCStrategy: Found ARC-IMPACT name '{fund_name}' on line {i+1}.")
                        fund_found = True
                    continue # Prioritize ARC-IMPACT match

                 # Look for specific account name patterns
                    for pattern in account_name_patterns:
                        match = pattern.search(line)
                        if match:
                            if "PRODUCT DEV" in pattern.pattern.upper():
                                identifier = match.group(1)
                                fund_name = f"ARCTARIS PRODUCT DEV {identifier}"
                                statement_info.account_name = fund_name.upper()
                            logging.debug(f"PNCStrategy: Found name '{fund_name}' via PRODUCT DEV pattern on line {i+1}.")
                                fund_found = True
                            break # Stop checking account_name_patterns
                            elif "PHASE" in pattern.pattern.upper():
                                identifier = match.group(1)
                                fund_name = f"PHASE {identifier} HOLDINGS"
                                statement_info.account_name = fund_name.upper()
                            logging.debug(f"PNCStrategy: Found name '{fund_name}' via PHASE pattern on line {i+1}.")
                                fund_found = True
                            break # Stop checking account_name_patterns
                if fund_found: continue # Move to next line if found

                 # Try generic fund patterns
                     for pattern in fund_patterns:
                        match = pattern.search(line)
                        if match:
                            fund_name = match.group(1).strip()
                        # Apply cleaning/normalization
                        if "cde" in fund_name.lower() and "sub" not in fund_name.lower():
                           # Check if line context suggests SUB-CDE
                           if "sub-cde" in line.lower() and re.search(r'CDE[^A-Za-z0-9]*[0-9]+', fund_name, re.IGNORECASE):
                                    fund_name = "SUB-" + fund_name
                            fund_name = fund_name.replace(',', '').replace('.', '')
                        fund_name = re.sub(r'\s+Tax\s+ID.*$', '', fund_name, flags=re.IGNORECASE).strip() # Remove Tax ID info
                        fund_name = re.sub(r'\s+', ' ', fund_name).upper() # Consolidate whitespace, uppercase
                        if "ARC IMPACT" in fund_name: fund_name = fund_name.replace("ARC IMPACT", "ARC-IMPACT")

                        if len(fund_name) > 3 and "SUMMARY" not in fund_name : # Basic check for meaningful name, avoid summary lines
                                statement_info.account_name = fund_name
                            logging.debug(f"PNCStrategy: Found name '{fund_name}' via generic pattern '{pattern.pattern}' on line {i+1}.")
                                fund_found = True
                            break # Stop checking fund_patterns
                if fund_found: continue

            # Extract date
            if not date_found:
                match = date_pattern.search(line)
                if match:
                    date_str = match.group(1).strip()
                    parsed_date = self._parse_date(date_str, ['%m/%d/%Y', '%m/%d/%y'])
                    if parsed_date:
                        statement_info.date = parsed_date
                        logging.debug(f"PNCStrategy: Found date '{parsed_date.strftime('%Y-%m-%d')}' on line {i+1}.")
                        date_found = True
                        continue # Move to next line

        # Final checks and fallbacks after processing all lines
        logging.debug(f"PNCStrategy: Finished line processing. Status: Acc={account_found}, Fund={fund_found}, Date={date_found}")
        if account_found and not fund_found and statement_info.account_number:
            # If account number found but no name, try mapping again (maybe placeholder acc num was updated)
            full_account = statement_info.account_number
            if full_account.startswith("xxxx"): # Check if it's still a placeholder
                 last4 = full_account[-4:]
                 if last4 in arc_impact_mappings:
                     statement_info.account_name = arc_impact_mappings[last4]
                     logging.debug(f"PNCStrategy: Fallback - Mapped name '{statement_info.account_name}' from last4 placeholder.")
                     fund_found = True
            elif full_account in pnc_mappings:
                statement_info.account_name = pnc_mappings[full_account]
                 logging.debug(f"PNCStrategy: Fallback - Mapped name '{statement_info.account_name}' from full account.")
                 fund_found = True
            else: # Try last 4 of full account
                last4 = full_account[-4:]
                if last4 in arc_impact_mappings:
                    statement_info.account_name = arc_impact_mappings[last4]
                     logging.debug(f"PNCStrategy: Fallback - Mapped name '{statement_info.account_name}' from last4 of full account.")
                     fund_found = True

        # Set default account name if still not found
        if not statement_info.account_name:
            if statement_info.account_number and not statement_info.account_number.startswith("xxxx"):
                statement_info.account_name = f"PNC ACCOUNT {statement_info.account_number[-4:]}"
                logging.warning(f"PNCStrategy: No specific account name found for {statement_info.original_filename}. Using default: '{statement_info.account_name}'.")
            else:
                statement_info.account_name = "UNKNOWN PNC ACCOUNT"
                logging.warning(f"PNCStrategy: No account name or usable number found for {statement_info.original_filename}. Using default: '{statement_info.account_name}'.")

        # Ensure date exists
        if not statement_info.date:
            logging.warning(f"PNCStrategy: No statement date found for {statement_info.original_filename}. Using current date as fallback.")
            statement_info.date = datetime.now() # Fallback date


    def get_filename(self, statement_info: StatementInfo) -> str:
        """ PNC Filename: [Account Name]_[Original Filename] """
        account_name = statement_info.account_name or "Unknown_PNC_Account"
        original_filename = statement_info.original_filename or "statement.pdf"
        clean_account_name = self._sanitize_filename(account_name.upper())
        clean_original = self._sanitize_filename(os.path.splitext(original_filename)[0]) # Sanitize base name
        date_str = statement_info.date.strftime("%Y%m%d") if statement_info.date else "NODATE"
        # Construct: BANK_YYYYMMDD_ACCOUNT_NAME_LAST4.pdf
        last4 = statement_info.account_number[-4:] if statement_info.account_number and len(statement_info.account_number) >= 4 else "XXXX"
        new_filename = f"PNC_{date_str}_{clean_account_name}_{last4}.pdf"
        # Limit length if necessary
        max_len = 200 # Example max length
        if len(new_filename) > max_len:
             base, ext = os.path.splitext(new_filename)
             new_filename = base[:max_len - len(ext)] + ext
             logging.warning(f"PNCStrategy: Truncated filename for {original_filename} due to length.")
        return new_filename

    def get_subfolder_path(self, statement_info: StatementInfo) -> str:
        """ Subfolder: PNC / YYYY-MM """
        year_month = statement_info.date.strftime('%Y-%m') if statement_info.date else "UnknownDate"
        # Maybe include account name in subfolder?
        # clean_account_name = self._sanitize_filename(statement_info.account_name or "UnknownAccount")
        # return os.path.join("PNC", clean_account_name, year_month)
        return os.path.join(self.get_bank_name(), year_month)


class BerkshireStrategy(BankStrategy):
    """Strategy for processing Berkshire Bank statements."""

    def get_bank_name(self) -> str:
        return "Berkshire"

    def extract_info(self, lines: List[str], statement_info: StatementInfo):
        statement_info.bank_type = self.get_bank_name()
        mappings = self.config.get_account_mappings("berkshire_last4")
        original_filename = statement_info.original_filename or ""
        # Check if it's the simplified "NewStatement" format
        is_new_statement_format = "newstatement" in original_filename.lower() or "new_statement" in original_filename.lower()

        # Patterns
        account_patterns = [
            re.compile(r'Account\s*[#:]?\s*(\d+)', re.IGNORECASE),
            re.compile(r'Account Number[:#\s]*(\d+)', re.IGNORECASE),
            re.compile(r'ACCT\s*[#:]?\s*(\d+)', re.IGNORECASE),
            re.compile(r'\bA/C\s*[#:]?\s*(\d+)', re.IGNORECASE),
            re.compile(r'xxxx(\d{4})', re.IGNORECASE), # Explicit last 4
            re.compile(r'Ending Balance on \d{1,2}/\d{1,2}/\d{2,4}\s+(\d+)', re.IGNORECASE) # Less reliable pattern
        ]
        # Simpler name patterns first
        fund_patterns = [
            re.compile(r'^(ARCTARIS\s+[A-Za-z0-9\s-]+(?:LLC|LP|INC)?)$?', re.IGNORECASE), # Arctaris name at line start
            re.compile(r'(?:Owner|Name)[:\s]+(ARCTARIS\s+[A-Za-z0-9\s-]+(?:LLC|LP|INC)?)', re.IGNORECASE), # Explicit Owner/Name
            re.compile(r'^(SUB[- ]?CDE\s+\d+\s+LLC)$?', re.IGNORECASE), # Sub CDE at line start
            re.compile(r'(?:Owner|Name)[:\s]+(SUB[- ]?CDE\s+\d+\s+LLC)', re.IGNORECASE), # Explicit Owner/Name for SUB CDE
            # More generic LLC/LP finder - use carefully
            re.compile(r'^([A-Za-z0-9\s,.\-]+(?:\s+LLC|\s+LP|\s+INC))$?', re.IGNORECASE)
        ]
        date_pattern = re.compile(r'Statement Date[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})', re.IGNORECASE)
        period_end_date_pattern = re.compile(r'Statement Period[:\s]*.*? to [\s]*(\d{1,2}/\d{1,2}/\d{2,4})', re.IGNORECASE)

        account_number = None
        account_last4 = None
        fund_name = None
        statement_date = None

        # Handle "NewStatement" files - often just filename has info
        if is_new_statement_format:
            logging.info(f"BerkshireStrategy: Detected NewStatement format for {original_filename}. Relying heavily on mappings.")
            # Try to get last 4 from filename if possible (e.g., NewStatement_1234.pdf)
            match = re.search(r'_(\\d{4})(?:\\.pdf)?$', original_filename)
        if match:
                account_last4 = match.group(1)
                logging.debug(f"BerkshireStrategy: Found last 4 '{account_last4}' from NewStatement filename.")
                if account_last4 in mappings:
                    fund_name = mappings[account_last4]
                    logging.debug(f"BerkshireStrategy: Mapped name '{fund_name}' from last4 in NewStatement filename.")
                    statement_info.account_name = fund_name
                    statement_info.account_number = f"xxxx{account_last4}"
            # Date is usually not in these files, use fallback
            statement_date = datetime.now()
            logging.warning(f"BerkshireStrategy: Using current date as fallback for NewStatement file {original_filename}.")
            # Exit early if we got the name from filename mapping
            if fund_name:
                statement_info.date = statement_date
                return
            # Otherwise, continue to process lines if any exist (might be corrupted/empty)

        # Process lines for regular statements or if NewStatement processing failed
        logging.debug(f"BerkshireStrategy: Starting line processing for '{statement_info.original_filename}'.")
        for i, line in enumerate(lines):
            if not line.strip(): continue
            logging.log(logging.DEBUG - 5 , f"Berkshire Line {i+1}: {line.strip()}") # Very verbose logging

            # Extract Account Number/Last 4
            if not account_number and not account_last4:
                    for pattern in account_patterns:
                        match = pattern.search(line)
                        if match:
                        num = match.group(1)
                        if len(num) >= 4:
                            account_last4 = num[-4:]
                            # Check if it looks like a full number
                            if len(num) > 5 and pattern != account_patterns[4]: # Avoid assigning full num if just xxxx1234 matched
                                account_number = num
                                logging.debug(f"BerkshireStrategy: Found full account '{account_number}' (last4: {account_last4}) on line {i+1}.")
                else:
                                logging.debug(f"BerkshireStrategy: Found last 4 '{account_last4}' on line {i+1}.")
                            # Try mapping immediately
                            if not fund_name and account_last4 in mappings:
                                fund_name = mappings[account_last4]
                                logging.debug(f"BerkshireStrategy: Mapped name '{fund_name}' from last4 ({account_last4}) in content.")
                            break # Stop checking account patterns for this line

            # Extract Fund Name
            if not fund_name:
                         for pattern in fund_patterns:
                            match = pattern.search(line)
                            if match:
                                potential_name = match.group(1).strip()
                        potential_name = re.sub(r'\s+', ' ', potential_name).upper()
                        # Basic validation
                        if len(potential_name) > 5 and "ACCOUNT SUMMARY" not in potential_name and "STATEMENT OF" not in potential_name:
                            fund_name = potential_name
                            logging.debug(f"BerkshireStrategy: Found potential name '{fund_name}' via pattern '{pattern.pattern}' on line {i+1}.")
                            break # Stop checking fund patterns for this line

            # Extract Date
            if not statement_date:
                match = date_pattern.search(line)
                if match:
                    date_str = match.group(1)
                    parsed = self._parse_date(date_str, ['%m/%d/%Y', '%m/%d/%y'])
                    if parsed:
                        statement_date = parsed
                        logging.debug(f"BerkshireStrategy: Found statement date '{statement_date.strftime('%Y-%m-%d')}' on line {i+1}.")
                else:
                    match = period_end_date_pattern.search(line)
                           if match:
                               date_str = match.group(1)
                        parsed = self._parse_date(date_str, ['%m/%d/%Y', '%m/%d/%y'])
                        if parsed:
                            statement_date = parsed
                            logging.debug(f"BerkshireStrategy: Found period end date '{statement_date.strftime('%Y-%m-%d')}' on line {i+1}.")

            # Optimization: Stop if all found
            if (account_number or account_last4) and fund_name and statement_date:
                 logging.debug("BerkshireStrategy: All required info found, stopping line processing early.")
                              break

        # Assign extracted info to statement_info
        logging.debug(f"BerkshireStrategy: Finished line processing. Status: AccNum={bool(account_number)}, Last4={bool(account_last4)}, Fund={bool(fund_name)}, Date={bool(statement_date)}")
        if account_number:
            statement_info.account_number = account_number
        elif account_last4:
            statement_info.account_number = f"xxxx{account_last4}"

        if fund_name:
            statement_info.account_name = fund_name
        elif account_last4 and account_last4 in mappings:
            # Final mapping check if fund name wasn't found directly
            statement_info.account_name = mappings[account_last4]
            logging.debug(f"BerkshireStrategy: Fallback mapping '{statement_info.account_name}' from last4 ({account_last4}).")
        elif not statement_info.account_name: # Avoid overwriting if set by NewStatement logic
            if account_last4:
                statement_info.account_name = f"BERKSHIRE ACCOUNT {account_last4}"
                logging.warning(f"BerkshireStrategy: No specific account name found for {original_filename}. Using default: '{statement_info.account_name}'.")
            else:
                 statement_info.account_name = "UNKNOWN BERKSHIRE ACCOUNT"
                 logging.warning(f"BerkshireStrategy: No account name or number found for {original_filename}. Using default: '{statement_info.account_name}'.")

        if statement_date:
            statement_info.date = statement_date
        elif not statement_info.date: # Avoid overwriting if set by NewStatement logic
             logging.warning(f"BerkshireStrategy: No statement date found for {original_filename}. Using current date as fallback.")
             statement_info.date = datetime.now()

    def get_filename(self, statement_info: StatementInfo) -> str:
        """ Filename: [last4]-[Account Name]-[YYYYMMDD].pdf """
        last4 = "0000"
        if statement_info.account_number and len(statement_info.account_number) >= 4:
             last4 = statement_info.account_number[-4:]
        elif statement_info.account_number: # Handle cases where only last4 was stored
             last4 = re.sub(r'[^0-9]', '', statement_info.account_number) # Extract digits if placeholder used

        account_name = statement_info.account_name or "Unknown_Account"
        date_str = statement_info.date.strftime('%Y%m%d') if statement_info.date else datetime.now().strftime('%Y%m%d')

        # Clean account name
        clean_name = self._sanitize_filename(account_name.upper())

        filename = f"{last4}-{clean_name}-{date_str}.pdf"
        return filename

    def get_subfolder_path(self, statement_info: StatementInfo) -> str:
        """ Subfolder: Berkshire / YYYY-MM """
        year_month = statement_info.date.strftime('%Y-%m') if statement_info.date else datetime.now().strftime('%Y-%m')
        return os.path.join("Berkshire", year_month)


class CambridgeStrategy(BankStrategy):
    """Strategy for processing Cambridge Savings Bank statements."""

    def get_bank_name(self) -> str:
        return "Cambridge"

    def extract_info(self, lines: List[str], statement_info: StatementInfo):
        statement_info.bank_type = self.get_bank_name()
        # Mappings likely based on account name substrings?
        mappings = self.config.get_account_mappings("cambridge_name_substring")

        # Patterns
        account_pattern = re.compile(r'Account(?: Number)?:?\s*(\d+-?\d+)\b', re.IGNORECASE)
        # Account names are often just the fund name
        fund_patterns = [
            re.compile(r'^(ARCTARIS\s+[A-Za-z0-9\s-]+(?:LLC|LP|INC)?)$?', re.IGNORECASE),
            re.compile(r'^(SUB[- ]?CDE\s+\d+\s+LLC)$?', re.IGNORECASE),
            # Look for name near address block?
            re.compile(r'^([A-Z\s&\d,-]+(?:LLC|LP|INC))\s*\r?$', re.MULTILINE), # Line with just uppercase/space/&/- and LLC/LP/INC
            # Generic LLC/LP finder
            re.compile(r'^([A-Za-z0-9\s,.\-]+(?:\s+LLC|\s+LP|\s+INC))$?', re.IGNORECASE)
        ]
        date_pattern = re.compile(r'Statement Date[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})', re.IGNORECASE)
        period_date_pattern = re.compile(r'Statement Period[:\s]*.*?\s+to\s+(\d{1,2}/\d{1,2}/\d{2,4})', re.IGNORECASE)

        account_number = None
        fund_name = None
        statement_date = None

        full_text = "\n".join(lines) # For multiline regex

        logging.debug(f"CambridgeStrategy: Starting processing for '{statement_info.original_filename}'.")
            for i, line in enumerate(lines):
            if not line.strip(): continue
            logging.log(logging.DEBUG - 5 , f"Cambridge Line {i+1}: {line.strip()}")

            # Stop processing if all info is found
            if account_number and fund_name and statement_date:
                 logging.debug("CambridgeStrategy: All required info found, stopping line processing.")
                 break

                # Extract Account Number
                if not account_number:
                match = account_pattern.search(line)
                if match:
                    account_number = match.group(1).replace('-', '')
                    logging.debug(f"CambridgeStrategy: Found account number '{account_number}' on line {i+1}.")
                    # Cambridge doesn't seem to use last4 mapping, maybe full number?
                    # Or map based on name?
                    continue

            # Extract Fund Name
            if not fund_name:
                for pattern in fund_patterns:
                    # Try multiline pattern on full text first
                    if pattern.flags & re.MULTILINE:
                         m_match = pattern.search(full_text)
                         if m_match:
                             potential_name = m_match.group(1).strip()
                             potential_name = re.sub(r'\s+', ' ', potential_name).upper()
                             if len(potential_name) > 5:
                                 fund_name = potential_name
                                 logging.debug(f"CambridgeStrategy: Found potential name '{fund_name}' via multiline pattern '{pattern.pattern}'.")
                                 break
                    # Try line-based patterns
                        match = pattern.search(line)
                        if match:
                        potential_name = match.group(1).strip()
                        potential_name = re.sub(r'\s+', ' ', potential_name).upper()
                        if len(potential_name) > 5 and "ACCOUNT ACTIVITY" not in potential_name:
                            fund_name = potential_name
                            logging.debug(f"CambridgeStrategy: Found potential name '{fund_name}' via pattern '{pattern.pattern}' on line {i+1}.")
                                break
                if fund_name: continue

                # Extract Date
                if not statement_date:
                match = date_pattern.search(line)
                if match:
                    date_str = match.group(1)
                    parsed = self._parse_date(date_str, ['%m/%d/%Y', '%m/%d/%y'])
                    if parsed:
                        statement_date = parsed
                        logging.debug(f"CambridgeStrategy: Found statement date '{statement_date.strftime('%Y-%m-%d')}' on line {i+1}.")
                        continue
                else:
                     match = period_date_pattern.search(line)
                        if match:
                            date_str = match.group(1)
                         parsed = self._parse_date(date_str, ['%m/%d/%Y', '%m/%d/%y'])
                         if parsed:
                             statement_date = parsed
                             logging.debug(f"CambridgeStrategy: Found period end date '{statement_date.strftime('%Y-%m-%d')}' on line {i+1}.")
                             continue

        # Post-processing and assignment
        logging.debug(f"CambridgeStrategy: Finished line processing. Status: AccNum={bool(account_number)}, Fund={bool(fund_name)}, Date={bool(statement_date)}")
        if account_number:
             statement_info.account_number = account_number

        if fund_name:
            # Try to map using substrings if mapping exists
            mapped_name = None
            if mappings:
                 for sub, mapped in mappings.items():
                      if sub.lower() in fund_name.lower():
                           mapped_name = mapped
                           logging.debug(f"CambridgeStrategy: Mapped name '{mapped_name}' from substring '{sub}'.")
                    break
            statement_info.account_name = mapped_name or fund_name # Use mapped if found, else use extracted
        elif not statement_info.account_name:
             if account_number:
                 statement_info.account_name = f"CAMBRIDGE ACCOUNT {account_number[-4:]}"
                 logging.warning(f"CambridgeStrategy: No specific account name found for {statement_info.original_filename}. Using default: '{statement_info.account_name}'.")
             else:
                  statement_info.account_name = "UNKNOWN CAMBRIDGE ACCOUNT"
                  logging.warning(f"CambridgeStrategy: No account name or number found for {statement_info.original_filename}. Using default: '{statement_info.account_name}'.")

        if statement_date:
        statement_info.date = statement_date
        elif not statement_info.date:
            logging.warning(f"CambridgeStrategy: No statement date found for {statement_info.original_filename}. Using current date fallback.")
            statement_info.date = datetime.now()

    def get_filename(self, statement_info: StatementInfo) -> str:
        """ Filename: [Account Name] [Account Number] Cambridge Savings [Month] [YYYY].pdf """
        account_name = statement_info.account_name or "Unknown Account"
        account_number = statement_info.account_number or "0000"
        month = statement_info.date.strftime('%B') if statement_info.date else datetime.now().strftime('%B')
        year = statement_info.date.strftime('%Y') if statement_info.date else datetime.now().strftime('%Y')

        # Clean name
        clean_name = self._sanitize_filename(account_name)

        filename = f"{clean_name} {account_number} Cambridge Savings {month} {year}.pdf"
        return filename # Already sanitized name, rest is safe

    def get_subfolder_path(self, statement_info: StatementInfo) -> str:
        """ Subfolder: Cambridge / YYYY-MM """
        year_month = statement_info.date.strftime('%Y-%m') if statement_info.date else datetime.now().strftime('%Y-%m')
        return os.path.join("Cambridge", year_month)


class BankUnitedStrategy(BankStrategy):
    """Strategy for processing BankUnited statements."""

    def get_bank_name(self) -> str:
        return "BankUnited"

    def extract_info(self, lines: List[str], statement_info: StatementInfo):
        statement_info.bank_type = self.get_bank_name()
        mappings = self.config.get_account_mappings("bankunited_last4")

        # Patterns
        account_pattern = re.compile(r'Account(?: Number)?:?\s*(\d+)\b', re.IGNORECASE)
        # BankUnited often has name on a line by itself near the top
        fund_patterns = [
             re.compile(r'^(ARCTARIS\s+[A-Za-z0-9\s-]+(?:LLC|LP|INC)?)$?', re.IGNORECASE),
             re.compile(r'^(SUB[- ]?CDE\s+\d+\s+LLC)$?', re.IGNORECASE),
             # Look for ALL CAPS line that contains LLC/LP/INC
             re.compile(r'^([A-Z\s&\d,-]+(?:LLC|LP|INC))\s*\r?$'),
             # Generic LLC/LP finder
             re.compile(r'^([A-Za-z0-9\s,.\-]+(?:\s+LLC|\s+LP|\s+INC))$?', re.IGNORECASE)
        ]
        date_pattern = re.compile(r'Statement Date[:\s]*(\w+\s+\d{1,2},\s+\d{4})', re.IGNORECASE) # Format: Month DD, YYYY
        period_date_pattern = re.compile(r'Statement Period\s+.*\s+-\s+(\w+\s+\d{1,2},\s+\d{4})', re.IGNORECASE)

        account_number = None
        account_last4 = None
        fund_name = None
        statement_date = None

        logging.debug(f"BankUnitedStrategy: Starting processing for '{statement_info.original_filename}'.")
        for i, line in enumerate(lines):
            if not line.strip(): continue
            logging.log(logging.DEBUG - 5 , f"BankUnited Line {i+1}: {line.strip()}")

            # Stop processing if all info is found
            if (account_number or account_last4) and fund_name and statement_date:
                 logging.debug("BankUnitedStrategy: All required info found, stopping line processing.")
                 break

            # Extract Account Number
            if not account_number and not account_last4:
                match = account_pattern.search(line)
                if match:
                    num_str = match.group(1)
                    if len(num_str) >= 4:
                        account_number = num_str
                        account_last4 = num_str[-4:]
                        logging.debug(f"BankUnitedStrategy: Found account number '{account_number}' (last4: {account_last4}) on line {i+1}.")
                        # Try mapping
                        if not fund_name and account_last4 in mappings:
                             fund_name = mappings[account_last4]
                             logging.debug(f"BankUnitedStrategy: Mapped name '{fund_name}' from last4 ({account_last4}) in content.")
                        continue

            # Extract Fund Name
            if not fund_name:
                for pattern in fund_patterns:
                    match = pattern.search(line)
                    if match:
                        potential_name = match.group(1).strip()
                        potential_name = re.sub(r'\s+', ' ', potential_name).upper()
                        if len(potential_name) > 5 and "BANKUNITED" not in potential_name and "PAGE" not in potential_name:
                            fund_name = potential_name
                            logging.debug(f"BankUnitedStrategy: Found potential name '{fund_name}' via pattern '{pattern.pattern}' on line {i+1}.")
                            # Try mapping based on found name?
                            break
                if fund_name: continue

            # Extract Date
            if not statement_date:
                match = date_pattern.search(line) or period_date_pattern.search(line)
                 if match:
                    date_str = match.group(1)
                    # BankUnited uses Month DD, YYYY format
                    parsed = self._parse_date(date_str, ['%B %d, %Y', '%b %d, %Y'])
                    if parsed:
                        statement_date = parsed
                        logging.debug(f"BankUnitedStrategy: Found date '{statement_date.strftime('%Y-%m-%d')}' on line {i+1}.")
                        continue

        # Post-processing and assignment
        logging.debug(f"BankUnitedStrategy: Finished line processing. Status: AccNum={bool(account_number)}, Last4={bool(account_last4)}, Fund={bool(fund_name)}, Date={bool(statement_date)}")
        if account_number:
             statement_info.account_number = account_number
        elif account_last4:
             statement_info.account_number = f"xxxx{account_last4}"

        if fund_name:
            statement_info.account_name = fund_name
        elif account_last4 and account_last4 in mappings:
            statement_info.account_name = mappings[account_last4]
            logging.debug(f"BankUnitedStrategy: Fallback mapping '{statement_info.account_name}' from last4 ({account_last4}).")
        elif not statement_info.account_name:
             if account_last4:
                  statement_info.account_name = f"BANKUNITED ACCOUNT {account_last4}"
                  logging.warning(f"BankUnitedStrategy: No specific account name found. Using default: '{statement_info.account_name}'.")
             else:
                   statement_info.account_name = "UNKNOWN BANKUNITED ACCOUNT"
                   logging.warning(f"BankUnitedStrategy: No account name or number found. Using default: '{statement_info.account_name}'.")

        if statement_date:
        statement_info.date = statement_date
        elif not statement_info.date:
             logging.warning(f"BankUnitedStrategy: No statement date found. Using current date fallback.")
             statement_info.date = datetime.now()

    def get_filename(self, statement_info: StatementInfo) -> str:
        """ Filename: BANKUNITED_[YYYYMMDD]_[Account Name]_[Last4].pdf """
        account_name = statement_info.account_name or "Unknown_BankUnited_Account"
        clean_account_name = self._sanitize_filename(account_name.upper())
        date_str = statement_info.date.strftime("%Y%m%d") if statement_info.date else "NODATE"
        last4 = statement_info.account_number[-4:] if statement_info.account_number and len(statement_info.account_number) >= 4 else "XXXX"
        new_filename = f"BANKUNITED_{date_str}_{clean_account_name}_{last4}.pdf"

        max_len = 200
        if len(new_filename) > max_len:
             base, ext = os.path.splitext(new_filename)
             new_filename = base[:max_len - len(ext)] + ext
             logging.warning(f"BankUnitedStrategy: Truncated filename due to length.")
        return new_filename

    def get_subfolder_path(self, statement_info: StatementInfo) -> str:
        """ Subfolder: BankUnited / YYYY-MM """
        year_month = statement_info.date.strftime('%Y-%m') if statement_info.date else "UnknownDate"
        return os.path.join(self.get_bank_name(), year_month)


class UnlabeledStrategy(BankStrategy):
    """Strategy for processing statements that couldn't be identified by filename or content analysis in PDFProcessor."""

    def get_bank_name(self) -> str:
        return "Unlabeled"

    def extract_info(self, lines: List[str], statement_info: StatementInfo):
        # Set bank type to Unlabeled. PDFProcessor already tried to identify it.
        statement_info.bank_type = self.get_bank_name()
        logging.info(f"Executing UnlabeledStrategy for '{statement_info.original_filename}'. Attempting generic extraction.")

        # Attempt to extract account number using a generic pattern (last 4 digits is often useful)
        account_pattern = re.compile(r'(?:Account|Acct|ACCOUNT|ACCT)[^0-9]*(?:[\dX]+-){0,2}([0-9]{4})\b', re.IGNORECASE)
        account_number_full_pattern = re.compile(r'(?:Account|Acct|ACCOUNT|ACCT)[^0-9]*(\d{6,})\b', re.IGNORECASE)
        account_last4 = None
        account_number = None
        for line in lines:
             match = account_number_full_pattern.search(line)
             if match:
                 account_number = match.group(1)
                 account_last4 = account_number[-4:]
                 logging.debug(f"UnlabeledStrategy: Found potential full account number ending in {account_last4}")
                 break # Prefer full number
             else:
            match = account_pattern.search(line)
            if match:
                     account_last4 = match.group(1)
                     logging.debug(f"UnlabeledStrategy: Found potential last 4 digits {account_last4}")
                     # Don't break, keep looking for a fuller number if possible

        if account_number:
             statement_info.account_number = account_number
        elif account_last4:
             statement_info.account_number = f"xxxx{account_last4}"

        # Try to extract a date using various common formats
        # Prioritize patterns that are less likely to be random numbers
        date_patterns = [
            re.compile(r'Statement Date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', re.I),
            re.compile(r'Statement Date[:\s]*(\w+\s+\d{1,2},\s+\d{4})', re.I), # Month DD, YYYY
            re.compile(r'Statement Period.*?to\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', re.I),
            re.compile(r'Statement Period.*?-\s+(\w+\s+\d{1,2},\s+\d{4})', re.I),
            re.compile(r'Ending\s+(\d{1,2}/\d{1,2}/\d{2,4})', re.I),
            re.compile(r'As of\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', re.I),
            re.compile(r'Date\s+(\d{1,2}/\d{1,2}/\d{4})\b', re.I), # Date followed by specific format
            re.compile(r'\b(\d{1,2}/\d{1,2}/\d{4})\b') # Generic date format as last resort
        ]
        date_formats = ['%m/%d/%Y', '%m/%d/%y', '%B %d, %Y', '%b %d, %Y', '%Y-%m-%d']

        statement_date = None
        for line in lines:
            for pattern in date_patterns:
                match = pattern.search(line)
                if match:
                    date_str = match.group(1)
                    parsed_date = self._parse_date(date_str, date_formats)
                    if parsed_date:
                        # Simple validation: ensure year is reasonable
                        if 2000 <= parsed_date.year <= datetime.now().year + 1:
                             statement_date = parsed_date
                             logging.debug(f"UnlabeledStrategy: Found potential date '{statement_date.strftime('%Y-%m-%d')}' using pattern '{pattern.pattern}'.")
                             break # Found a date
            if statement_date:
                break # Stop searching lines if date found

        statement_info.date = statement_date

        # Use current date if no date found
        if not statement_info.date:
            logging.warning(f"UnlabeledStrategy: No date found for '{statement_info.original_filename}'. Using current date.")
            statement_info.date = datetime.now()

        # Set default account name if nothing better found (PDFProcessor might have set a bank-specific default already)
        if not statement_info.account_name:
            if statement_info.account_number:
                statement_info.account_name = f"ACCOUNT {statement_info.account_number[-4:]}"
                logging.info(f"UnlabeledStrategy: Setting default account name: '{statement_info.account_name}'.")
            else:
                statement_info.account_name = "UNKNOWN ACCOUNT"
                logging.info(f"UnlabeledStrategy: Setting default account name: '{statement_info.account_name}'.")

    def get_filename(self, statement_info: StatementInfo) -> str:
        """ Filename: UNLABELED_[YYYYMMDD]_[OriginalBaseName]_[Last4].pdf """
        original_basename = os.path.splitext(statement_info.original_filename or "unknown")[0]
        clean_original = self._sanitize_filename(original_basename)
        date_str = statement_info.date.strftime("%Y%m%d") if statement_info.date else "NODATE"
        last4 = statement_info.account_number[-4:] if statement_info.account_number and len(statement_info.account_number) >= 4 else "XXXX"
        new_filename = f"UNLABELED_{date_str}_{clean_original}_{last4}.pdf"
        # Limit length
        max_len = 200
        if len(new_filename) > max_len:
             base, ext = os.path.splitext(new_filename)
             new_filename = base[:max_len - len(ext)] + ext
             logging.warning(f"UnlabeledStrategy: Truncated filename due to length.")
        return new_filename

    def get_subfolder_path(self, statement_info: StatementInfo) -> str:
        """ Subfolder: Unlabeled / YYYY-MM """
        year_month = statement_info.date.strftime('%Y-%m') if statement_info.date else "UnknownDate"
        return os.path.join(self.get_bank_name(), year_month)


# Note: BANK_STRATEGIES map is no longer needed here, it's in PDFProcessor

# Mapping from bank type string to strategy class
BANK_STRATEGIES: Dict[str, BankStrategy] = {
    "PNC": PNCStrategy(),
    "Berkshire": BerkshireStrategy(),
    "BankUnited": BankUnitedStrategy(),
    "Cambridge": CambridgeStrategy(),
    "Unlabeled": UnlabeledStrategy() # Add a generic strategy for unlabeled/unknown
} 