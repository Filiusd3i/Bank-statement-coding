# c:\\Users\\Christian\\OneDrive - Arctaris Michigan Partners, LLC\\Desktop\\Bank Automation\\Codes\\Bank Statements\\bank_strategies.py
import re
import os
from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import logging
import Levenshtein # For fuzzy name matching

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

def sanitize_filename(filename: Optional[str], allow_spaces=False) -> str:
    """Sanitize a filename to be safe for use in file systems."""
    if not filename:
        return "sanitized_filename"
    # Remove or replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
    # Consolidate whitespace (including newlines etc.)
    if allow_spaces:
        sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    else:
        sanitized = re.sub(r'\s+', '_', sanitized).strip() # Default: replace space with underscore
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

    def _sanitize_filename(self, filename: Optional[str], allow_spaces=False) -> str:
        return sanitize_filename(filename, allow_spaces=allow_spaces)

    def _find_sensitive_match_by_number(self, number_to_check: str, sensitive_accounts: List[Dict]) -> Optional[Dict]:
        """Checks if a number matches (full or last 4) a sensitive account number."""
        if not number_to_check or not sensitive_accounts:
            return None
        
        # Normalize the number to check (remove non-digits)
        normalized_check = re.sub(r'\D', '', number_to_check)
        if not normalized_check:
            return None

        check_last4 = normalized_check[-4:]

        for account in sensitive_accounts:
            sensitive_number = account.get('number')
            if not sensitive_number:
                continue
            
            normalized_sensitive = re.sub(r'\D', '', str(sensitive_number))
            if not normalized_sensitive:
                continue
            
            # Prioritize full number match
            if normalized_check == normalized_sensitive:
                logging.debug(f"Sensitive match found based on full account number: {normalized_check}")
                return account
            
            # Check last 4 digits if full match failed
            sensitive_last4 = normalized_sensitive[-4:]
            if len(normalized_check) >= 4 and check_last4 == sensitive_last4:
                logging.debug(f"Sensitive match found based on last 4 digits: {check_last4}")
                return account
            
        return None

    def _find_sensitive_match_by_name(self, name_to_check: str, sensitive_accounts: List[Dict], threshold=0.85) -> Optional[Dict]:
        """Checks if a name fuzzy-matches a sensitive account name."""
        if not name_to_check or not sensitive_accounts:
            return None
        
        best_match = None
        highest_ratio = threshold # Require at least this similarity

        check_name_norm = name_to_check.upper().strip()

        for account in sensitive_accounts:
            sensitive_name = account.get('name')
            if not sensitive_name:
                continue
            
            sensitive_name_norm = sensitive_name.upper().strip()
            
            # Calculate similarity ratio (e.g., Levenshtein distance ratio)
            ratio = Levenshtein.ratio(check_name_norm, sensitive_name_norm)
            
            if ratio >= highest_ratio:
                highest_ratio = ratio
                best_match = account
        
        if best_match:
            logging.debug(f"Sensitive match found based on name '{name_to_check}' matching '{best_match['name']}' with ratio {highest_ratio:.2f}")
            return best_match
        else:
            return None


# --- Concrete Strategies ---

class PNCStrategy(BankStrategy):
    """Strategy for processing PNC Bank statements."""

    def get_bank_name(self) -> str:
        return "PNC"

    def extract_info(self, lines: List[str], statement_info: StatementInfo):
        statement_info.bank_type = self.get_bank_name()
        pnc_mappings = self.config.get_account_mappings("pnc")
        arc_impact_mappings = self.config.get_account_mappings("pnc_arc_impact_last4")
        sensitive_accounts = self.config.get_sensitive_accounts(self.get_bank_name())

        # Pre-compile regex patterns for efficiency
        account_pattern = re.compile(r'Account Number:\s*(\d+-\d+-\d+|\d+)', re.IGNORECASE)
        account_last4_pattern = re.compile(r'(?:Account|Acct)[^0-9]*(?:[0-9]+-){0,2}([0-9]{4})\b', re.IGNORECASE)
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
        sensitive_match_made = False

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
        logging.debug(f"PNCStrategy: Starting line processing for '{statement_info.original_filename}'. Sensitive accounts loaded: {len(sensitive_accounts)}")
        for i, line in enumerate(lines):
            if not line.strip(): continue # Skip empty lines
            if sensitive_match_made: break # Stop if we already have a definitive match
            logging.log(logging.DEBUG - 5 , f"PNC Line {i+1}: {line.strip()}") # Very verbose logging

            # Stop processing if all info is found
            if account_found and fund_found and date_found:
                logging.debug("PNCStrategy: All required info found, stopping line processing.")
                break

            # Extract account number
            if not account_found:
                match = account_pattern.search(line)
                if match:
                    potential_account_num = match.group(1) # Full number or dashed
                else:
                    match = account_last4_pattern.search(line)
                    if match:
                        potential_account_num = match.group(1) # Just last 4
               
                # Check potential number against sensitive list
                if potential_account_num:
                    sensitive_match = self._find_sensitive_match_by_number(potential_account_num, sensitive_accounts)
                    if sensitive_match:
                        statement_info.account_number = sensitive_match['number']
                        statement_info.account_name = sensitive_match['name']
                        logging.info(f"PNCStrategy: Confirmed account '{statement_info.account_name}' ({statement_info.account_number}) via sensitive number match on line {i+1}.")
                        account_found = True
                        fund_found = True
                        sensitive_match_made = True
                        continue # Move to next line or break
                    else:
                        # Didn't match sensitive, but regex found something. Store it tentatively.
                        if '-' in potential_account_num or len(potential_account_num) > 4: # Looks like full number
                             statement_info.account_number = potential_account_num.replace('-', '')
                        else: # Only last 4 found by regex
                             statement_info.account_number = f"xxxx{potential_account_num}"
                        account_found = True
                        logging.debug(f"PNCStrategy: Regex found potential account '{statement_info.account_number}' on line {i+1}, but no sensitive match.")
                        # Do NOT set fund_found = True here yet, rely on name matching or mappings later

            # Extract fund name using various patterns
            if not fund_found:
                # Look for ARC-IMPACT first
                match = arc_impact_pattern.search(line)
                if match:
                    fund_name = match.group(1)
                    # Clean the found name right away
                    fund_name = re.sub(r'ARC[\\s-]IMPACT', 'ARC-IMPACT', fund_name, flags=re.IGNORECASE).upper().strip()
                    statement_info.account_name = fund_name
                    logging.debug(f"PNCStrategy: Found ARC-IMPACT name '{fund_name}' on line {i+1}.")
                    fund_found = True
                    continue # Prioritize ARC-IMPACT match

                # Look for specific account name patterns if ARC-IMPACT wasn't found
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
                if fund_found: continue # Move to next line if found via account_name_patterns

                # Try generic fund patterns if specific ones weren't found
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
                        fund_name = re.sub(r'\\s+Tax\\s+ID.*$', '', fund_name, flags=re.IGNORECASE).strip() # Remove Tax ID info
                        fund_name = re.sub(r'\\s+', ' ', fund_name).upper() # Consolidate whitespace, uppercase
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
                     logging.debug(f"PNCStrategy: Fallback - Mapped name '{statement_info.account_name}' from last4 regex '{last4}'.")
                     fund_found = True
            elif full_account in pnc_mappings:
                statement_info.account_name = pnc_mappings[full_account]
                logging.debug(f"PNCStrategy: Fallback - Mapped name '{statement_info.account_name}' from full account regex '{full_account}'.")
                fund_found = True
            else: # Try last 4 of full account
                last4 = full_account[-4:]
                if last4 in arc_impact_mappings:
                    statement_info.account_name = arc_impact_mappings[last4]
                    logging.debug(f"PNCStrategy: Fallback - Mapped name '{statement_info.account_name}' from last4 of full account regex '{last4}'.")
                    fund_found = True

        # Set default account name if still not found
        if not statement_info.account_name:
            if account_found and statement_info.account_number and not statement_info.account_number.startswith("xxxx"):
                statement_info.account_name = f"PNC ACCOUNT {statement_info.account_number[-4:]}"
                logging.warning(f"PNCStrategy: No specific account name identified. Using default based on regex account #: '{statement_info.account_name}'.")
            else:
                statement_info.account_name = "UNKNOWN PNC ACCOUNT"
                logging.warning(f"PNCStrategy: No account name or identifiable number found. Using default: '{statement_info.account_name}'.")

        # Ensure date exists
        if not statement_info.date:
            logging.warning(f"PNCStrategy: No statement date found. Using current date fallback.")
            statement_info.date = datetime.now()

    def get_filename(self, statement_info: StatementInfo) -> str:
        """ PNC Filename: [Account name] statement_[account number]_YYYY_MM_DD.pdf """
        account_name = statement_info.account_name or "Unknown_PNC_Account"
        # Use full account number if available, sanitize for filename
        account_number_raw = statement_info.account_number or "UNKNOWN_ACCOUNT_NUM"
        account_number_clean = re.sub(r'[D-]', '', account_number_raw)
        account_number_clean = self._sanitize_filename(account_number_clean, allow_spaces=False)

        # Sanitize account name
        clean_account_name = self._sanitize_filename(account_name, allow_spaces=True)

        # Format date as YYYY_MM_DD
        date_str = statement_info.date.strftime("%Y_%m_%d") if statement_info.date else "NODATE"

        # Construct the new filename
        new_filename = f"{clean_account_name} statement_{account_number_clean}_{date_str}.pdf"

        # Limit length if necessary (optional, can be removed if length is not a concern)
        max_len = 200 # Example max length
        if len(new_filename) > max_len:
             original_filename_for_log = statement_info.original_filename or "unknown.pdf"
             base, ext = os.path.splitext(new_filename)
             cutoff = max_len - len(ext) - 3 # Make space for "..."
             new_filename = base[:cutoff] + "..." + ext
             logging.warning(f"PNCStrategy: Truncated filename for {original_filename_for_log} due to length: {new_filename}")
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
        sensitive_accounts = self.config.get_sensitive_accounts(self.get_bank_name())
        original_filename = statement_info.original_filename or ""
        # Check if it's the simplified "NewStatement" format
        is_new_statement_format = "newstatement" in original_filename.lower() or "new_statement" in original_filename.lower()

        # Patterns
        account_patterns = [
            re.compile(r'Account\s*[#:]?\s*(\d+)', re.IGNORECASE),
            re.compile(r'Account Number[:#\s]*(\d+)', re.IGNORECASE),
            re.compile(r'ACCT\s*[#:]?\s*(\d+)', re.IGNORECASE),
            re.compile(r'\bA/C\s*[#:]?\s*(\d+)', re.IGNORECASE),
            re.compile(r'xxxx(\d{4})\b', re.IGNORECASE), # Explicit last 4
            re.compile(r'Ending Balance on \d{1,2}/\d{1,2}/\d{2,4}\s+(\d+)', re.IGNORECASE) # Less reliable pattern
        ]
        # Simpler name patterns first
        fund_patterns = [
            re.compile(r'^(ARCTARIS\s+[A-Za-z0-9\s-]+(?:LLC|LP|INC)?)$?', re.IGNORECASE), # Arctaris name at line start
            re.compile(r'(?:Owner|Name)[:\s]+(ARCTARIS\s+[A-Za-z0-9\s-]+(?:LLC|LP|INC)?)', re.IGNORECASE), # Explicit Owner/Name
            re.compile(r'^(SUB[- ]?CDE\s+\d+\s+LLC)$?', re.IGNORECASE), # Sub CDE at line start
            re.compile(r'(?:Owner|Name)[:\s]+(SUB[- ]?CDE\s+\d+\s+LLC)', re.IGNORECASE), # Explicit Owner/Name for SUB CDE
            # More generic LLC/LP finder - use carefully
            re.compile(r'^([A-Za-z0-9\s,.\\-]+(?:\s+LLC|\s+LP|\s+INC))$?', re.IGNORECASE)
        ]
        date_pattern = re.compile(r'Statement Date[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})', re.IGNORECASE)
        period_end_date_pattern = re.compile(r'Statement Period[:\s]*.*? to [\s]*(\d{1,2}/\d{1,2}/\d{2,4})', re.IGNORECASE)

        account_found = False
        fund_found = False
        date_found = False
        sensitive_match_made = False

        # Handle "NewStatement" files - often just filename has info
        if is_new_statement_format:
            logging.info(f"BerkshireStrategy: Detected NewStatement format for {original_filename}. Checking sensitive list by filename heuristic.")
            match = re.search(r'_(\\d{4})(?:\\.pdf)?$', original_filename)
            if match:
                potential_last4 = match.group(1)
                sensitive_match = self._find_sensitive_match_by_number(potential_last4, sensitive_accounts)
                if sensitive_match:
                    statement_info.account_number = sensitive_match['number']
                    statement_info.account_name = sensitive_match['name']
                    logging.info(f"BerkshireStrategy: Confirmed NewStatement account '{statement_info.account_name}' via sensitive number match from filename ({potential_last4}).")
                    account_found = True
                    fund_found = True
                    sensitive_match_made = True
                    # Date usually missing, set fallback
                    statement_info.date = datetime.now()
                    date_found = True
                    return # Exit early, confirmed via sensitive filename match
                else:
                    logging.debug(f"BerkshireStrategy: Found last 4 '{potential_last4}' in NewStatement filename, but no sensitive match.")
            else:
                logging.debug(f"BerkshireStrategy: Could not extract last 4 from NewStatement filename '{original_filename}'.")
            # If no sensitive match from filename, proceed to line scan if lines exist
            if not sensitive_match_made:
                logging.debug("BerkshireStrategy: No sensitive match from NewStatement filename, proceeding to line scan.")

        # Process lines for regular statements or if NewStatement processing failed
        logging.debug(f"BerkshireStrategy: Starting line processing for '{original_filename}'. Sensitive accounts loaded: {len(sensitive_accounts)}")
        for i, line in enumerate(lines):
            if not line.strip(): continue
            if sensitive_match_made: break # Stop if we got a definitive match
            logging.log(logging.DEBUG - 5 , f"Berkshire Line {i+1}: {line.strip()}") # Very verbose logging

            # Try extracting account number using regex
            potential_account_num_or_last4 = None
            if not account_found:
                for pattern in account_patterns:
                     match = pattern.search(line)
                     if match:
                          potential_account_num_or_last4 = match.group(1)
                          break # Found potential number/last4 with one pattern
               
                # Check potential number against sensitive list
                if potential_account_num_or_last4:
                    sensitive_match = self._find_sensitive_match_by_number(potential_account_num_or_last4, sensitive_accounts)
                    if sensitive_match:
                        statement_info.account_number = sensitive_match['number']
                        statement_info.account_name = sensitive_match['name']
                        logging.info(f"BerkshireStrategy: Confirmed account '{statement_info.account_name}' ({statement_info.account_number}) via sensitive number match on line {i+1}.")
                        account_found = True
                        fund_found = True
                        sensitive_match_made = True
                        continue # Move to next line or break
                    else:
                        # Didn't match sensitive, but regex found something. Store tentatively.
                        if len(potential_account_num_or_last4) > 4 and not potential_account_num_or_last4.startswith('xxxx'):
                             statement_info.account_number = potential_account_num_or_last4
                        else: # Only last 4 or xxxx format found
                             last4_digits = potential_account_num_or_last4[-4:]
                             statement_info.account_number = f"xxxx{last4_digits}"
                        account_found = True
                        logging.debug(f"BerkshireStrategy: Regex found potential account '{statement_info.account_number}' on line {i+1}, but no sensitive match.")

            # Try extracting potential fund name using regex
            if not fund_found:
                 potential_fund_name = None
                 for pattern in fund_patterns:
                      match = pattern.search(line)
                      if match:
                           extracted_name = match.group(1).strip()
                           cleaned_name = re.sub(r'\s+', ' ', extracted_name).upper()
                           if len(cleaned_name) > 5 and "ACCOUNT SUMMARY" not in cleaned_name and "STATEMENT OF" not in cleaned_name:
                                potential_fund_name = cleaned_name
                                break
                
                 # Check potential name against sensitive list
                 if potential_fund_name:
                     sensitive_match = self._find_sensitive_match_by_name(potential_fund_name, sensitive_accounts)
                     if sensitive_match:
                         statement_info.account_name = sensitive_match['name']
                         fund_found = True
                         if not account_found:
                             statement_info.account_number = sensitive_match['number']
                             account_found = True
                             logging.info(f"BerkshireStrategy: Confirmed account '{statement_info.account_name}' ({statement_info.account_number}) via sensitive name match on line {i+1}.")
                             sensitive_match_made = True
                         else:
                             logging.info(f"BerkshireStrategy: Confirmed account name '{statement_info.account_name}' via sensitive name match on line {i+1} (number already found).")
                         if sensitive_match_made:
                              continue
                     else:
                         statement_info.account_name = potential_fund_name
                         fund_found = True
                         logging.debug(f"BerkshireStrategy: Regex found potential name '{potential_fund_name}' on line {i+1}, but no sensitive match.")

            # Extract date
            if not date_found:
                match = date_pattern.search(line)
                if match:
                    date_str = match.group(1)
                    parsed = self._parse_date(date_str, ['%m/%d/%Y', '%m/%d/%y'])
                    if parsed:
                        statement_info.date = parsed
                        logging.debug(f"BerkshireStrategy: Found statement date '{statement_date.strftime('%Y-%m-%d')}' on line {i+1}.")
                        date_found = True
                else:
                    match = period_end_date_pattern.search(line)
                    if match:
                        date_str = match.group(1)
                        parsed = self._parse_date(date_str, ['%m/%d/%Y', '%m/%d/%y'])
                        if parsed:
                            statement_info.date = parsed
                            logging.debug(f"BerkshireStrategy: Found period end date '{statement_date.strftime('%Y-%m-%d')}' on line {i+1}.")
                            date_found = True
                if date_found: continue

        # Fallback Logic
        if not sensitive_match_made:
            logging.debug(f"BerkshireStrategy: No definitive sensitive match. Applying fallback logic.")
            # If account found via regex but name still not confirmed (e.g., regex name had no sensitive match)
            if account_found and not fund_found and statement_info.account_number:
                # Extract last 4 from the stored regex number
                regex_acc_num = statement_info.account_number
                last4_regex = regex_acc_num[-4:] if len(regex_acc_num) >= 4 else None
                if last4_regex and last4_regex in mappings:
                    statement_info.account_name = mappings[last4_regex]
                    fund_found = True
                    logging.debug(f"BerkshireStrategy: Fallback mapping '{statement_info.account_name}' from regex last4 '{last4_regex}'.")

        # Final default setting
        if not statement_info.account_name:
            if account_found and statement_info.account_number:
                 last4 = statement_info.account_number[-4:] if len(statement_info.account_number) >=4 else "XXXX"
                 statement_info.account_name = f"BERKSHIRE ACCOUNT {last4}"
                 logging.warning(f"BerkshireStrategy: No specific account name identified. Using default: '{statement_info.account_name}'.")
            else:
                 statement_info.account_name = "UNKNOWN BERKSHIRE ACCOUNT"
                 logging.warning(f"BerkshireStrategy: No account name or identifiable number found. Using default: '{statement_info.account_name}'.")

        if not statement_info.date:
            logging.warning(f"BerkshireStrategy: No statement date found. Using current date as fallback.")
            statement_info.date = datetime.now()

    def get_filename(self, statement_info: StatementInfo) -> str:
        """ Filename: [last4]-[Account Name]-[YYYYMMDD].pdf """
        last4 = "XXXX"
        if statement_info.account_number:
             # Clean the number first (remove non-digits)
             clean_num_str = re.sub(r'\D', '', statement_info.account_number)
             if len(clean_num_str) >= 4:
                  last4 = clean_num_str[-4:]

        account_name = statement_info.account_name or "Unknown_Account"
        # Format date safely
        date_str = statement_info.date.strftime('%Y%m%d') if statement_info.date else "NODATE"

        # Clean account name (replace spaces with underscore by default)
        clean_name = self._sanitize_filename(account_name.upper(), allow_spaces=False)

        filename = f"{last4}-{clean_name}-{date_str}.pdf"
        
        # Add length check if needed
        max_len = 200
        if len(filename) > max_len:
             base, ext = os.path.splitext(filename)
             cutoff = max_len - len(ext) - 3
             filename = base[:cutoff] + "..." + ext
             logging.warning(f"BerkshireStrategy: Truncated filename: {filename}")
        return filename

    def get_subfolder_path(self, statement_info: StatementInfo) -> str:
        """ Subfolder: Berkshire / YYYY-MM """
        year_month = statement_info.date.strftime('%Y-%m') if statement_info.date else "UnknownDate"
        return os.path.join(self.get_bank_name(), year_month)


class CambridgeStrategy(BankStrategy):
    """Strategy for processing Cambridge Savings Bank statements."""

    def get_bank_name(self) -> str:
        return "Cambridge"

    def extract_info(self, lines: List[str], statement_info: StatementInfo):
        statement_info.bank_type = self.get_bank_name()
        mappings = self.config.get_account_mappings("cambridge_name_substring")
        sensitive_accounts = self.config.get_sensitive_accounts(self.get_bank_name())

        # Patterns
        account_pattern = re.compile(r'Account(?: Number)?:?\\s*(\\d+-?\\d+)\\b', re.IGNORECASE)
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
        clean_name = self._sanitize_filename(account_name.upper())

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
        """ Filename: [Account Name] [Account Number] BankUnited [Month] [Year].pdf """
        account_name = statement_info.account_name or "Unknown BankUnited Account"
        account_number = statement_info.account_number or "UNKNOWN_ACCOUNT_NUM"
        bank_name = self.get_bank_name() # Should be "BankUnited"

        # Sanitize components
        # Use spaces, not underscores, and keep case as extracted unless upper explicitly desired
        clean_account_name = self._sanitize_filename(account_name, allow_spaces=True)
        # Sanitize account number, keep it identifiable
        clean_account_number = self._sanitize_filename(account_number, allow_spaces=False) # No spaces in account number

        # Get date components
        if statement_info.date:
            month = statement_info.date.strftime("%B") # Full month name, e.g., "March"
            year = statement_info.date.strftime("%Y") # 4-digit year, e.g., "2024"
        else:
            month = "NoMonth"
            year = "NoYear"

        # Construct the filename using spaces
        new_filename = f"{clean_account_name} {clean_account_number} {bank_name} {month} {year}.pdf"

        # Limit length
        max_len = 200 # Keep filename length reasonable
        if len(new_filename) > max_len:
             # Basic truncation, might need smarter logic if this happens often
             base, ext = os.path.splitext(new_filename)
             cutoff = max_len - len(ext) - 3 # Make space for "..."
             new_filename = base[:cutoff] + "..." + ext
             logging.warning(f"BankUnitedStrategy: Truncated filename to {max_len} chars: {new_filename}")
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
        account_pattern = re.compile(r'(?:Account|Acct|ACCOUNT|ACCT)[^0-9]*(?:[\dX]+-){0,2}([0-9]{4})\b', re.IGNORECASE)
        account_number_full_pattern = re.compile(r'(?:Account|Acct|ACCOUNT|ACCT)[^0-9]*(\d{6,})\b', re.IGNORECASE)
        account_last4 = None; account_number = None
        for line in lines:
             match = account_number_full_pattern.search(line)
             if match: account_number = match.group(1); account_last4 = account_number[-4:]; logging.debug(f"Unlabeled: Found potential full account ending in {account_last4}"); break
             else: match = account_pattern.search(line)
             if match: account_last4 = match.group(1); logging.debug(f"Unlabeled: Found potential last 4 digits {account_last4}")
        if account_number: statement_info.account_number = account_number
        elif account_last4: statement_info.account_number = f"xxxx{account_last4}"
        date_patterns = [
            re.compile(r'Statement Date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', re.I), re.compile(r'Statement Date[:\s]*(\w+\s+\d{1,2},\s+\d{4})', re.I),
            re.compile(r'Statement Period.*?to\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', re.I), re.compile(r'Statement Period.*?-\s+(\w+\s+\d{1,2},\s+\d{4})', re.I),
            re.compile(r'Ending\s+(\d{1,2}/\d{1,2}/\d{2,4})', re.I), re.compile(r'As of\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', re.I),
            re.compile(r'Date\s+(\d{1,2}/\d{1,2}/\d{4})\b', re.I), re.compile(r'\b(\d{1,2}/\d{1,2}/\d{4})\b')
        ]
        date_formats = ['%m/%d/%Y', '%m/%d/%y', '%B %d, %Y', '%b %d, %Y', '%Y-%m-%d']
        statement_date = None
        for line in lines:
            for pattern in date_patterns:
                match = pattern.search(line)
                if match:
                    parsed_date = self._parse_date(match.group(1), date_formats)
                    if parsed_date and 2000 <= parsed_date.year <= datetime.now().year + 1:
                         statement_date = parsed_date; logging.debug(f"Unlabeled: Found potential date {statement_date:%Y-%m-%d}"); break
            if statement_date: break
        statement_info.date = statement_date
        if not statement_info.date: logging.warning(f"Unlabeled: No date found. Using current date."); statement_info.date = datetime.now()
        if not statement_info.account_name:
            if statement_info.account_number: last4 = statement_info.account_number[-4:] if len(statement_info.account_number) >= 4 else "XXXX"; statement_info.account_name = f"ACCOUNT {last4}"; logging.info(f"Unlabeled: Setting default name: {statement_info.account_name}")
            else: statement_info.account_name = "UNKNOWN ACCOUNT"; logging.info(f"Unlabeled: Setting default name: {statement_info.account_name}")

    def get_filename(self, statement_info: StatementInfo) -> str:
        """ For Unlabeled files, keep the original filename. """
        if statement_info.original_filename:
             # Return the base name (e.g., "MyStatement.pdf") from the full original path
             original_basename = os.path.basename(statement_info.original_filename)
             logging.debug(f"UnlabeledStrategy: Keeping original filename: {original_basename}")
             return original_basename
        else:
             # Fallback if original filename is somehow missing
             logging.warning("UnlabeledStrategy: Original filename missing in statement_info. Using fallback name.")
             return "UNLABELED_FILE_ERROR.pdf"

    def get_subfolder_path(self, statement_info: StatementInfo) -> str:
        """ Subfolder: Unlabeled / YYYY-MM (Keep this organization) """
        year_month = statement_info.date.strftime('%Y-%m') if statement_info.date else "UnknownDate"
        return os.path.join(self.get_bank_name(), year_month)


# Note: BANK_STRATEGIES map is no longer needed here, it's in PDFProcessor

# Mapping from bank type string to strategy class
# BANK_STRATEGIES: Dict[str, type[BankStrategy]] = { # Original was likely type mapping
#     "PNC": PNCStrategy,
#     "Berkshire": BerkshireStrategy,
#     "BankUnited": BankUnitedStrategy,
#     "Cambridge": CambridgeStrategy,
#     "Unlabeled": UnlabeledStrategy
# } 