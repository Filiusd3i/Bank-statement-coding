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

    # --- Sensitive Data Matching Helpers --- 
    def _find_sensitive_match_by_number(self, number_to_check: str, sensitive_accounts: List[Dict]) -> Optional[Dict]:
        """Checks if a number matches (full or last 4) a sensitive account number."""
        if not number_to_check or not sensitive_accounts:
            return None
        normalized_check = re.sub(r'\D', '', number_to_check) # Remove non-digits
        if not normalized_check:
            return None
        check_last4 = normalized_check[-4:]

        for account in sensitive_accounts:
            sensitive_number = account.get('number')
            if not sensitive_number: continue
            normalized_sensitive = re.sub(r'\D', '', str(sensitive_number))
            if not normalized_sensitive: continue
            
            # Prioritize full number match
            if normalized_check == normalized_sensitive:
                logging.debug(f"Sensitive match found based on full account number: {normalized_check}")
                return account
            
            # Check last 4 digits if full match failed
            sensitive_last4 = normalized_sensitive[-4:]
            # Ensure we have at least 4 digits to compare
            if len(normalized_check) >= 4 and len(normalized_sensitive) >=4 and check_last4 == sensitive_last4:
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
            if not sensitive_name: continue
            sensitive_name_norm = sensitive_name.upper().strip()
            
            # Calculate similarity ratio
            ratio = Levenshtein.ratio(check_name_norm, sensitive_name_norm)
            
            if ratio >= highest_ratio:
                highest_ratio = ratio
                best_match = account
                
        if best_match:
            logging.debug(f"Sensitive match found based on name '{name_to_check}' matching '{best_match['name']}' with ratio {highest_ratio:.2f}")
            return best_match
        return None


# --- Concrete Strategies ---

class PNCStrategy(BankStrategy):
    """Strategy for processing PNC Bank statements."""

    def get_bank_name(self) -> str:
        return "PNC"

    def extract_info(self, lines: List[str], statement_info: StatementInfo):
        # Initialize
        statement_info.bank_type = self.get_bank_name()
        pnc_mappings = self.config.get_account_mappings("pnc") # Keep for fallback
        arc_impact_mappings = self.config.get_account_mappings("pnc_arc_impact_last4") # Keep for fallback
        sensitive_accounts = self.config.get_sensitive_accounts(self.get_bank_name())
        account_found = False; fund_found = False; date_found = False; sensitive_match_made = False
        
        # Keep your existing Regex patterns here
        account_pattern = re.compile(r'Account Number:\s*(\d+-\d+-\d+|\d+)', re.IGNORECASE)
        account_last4_pattern = re.compile(r'(?:Account|Acct)[^0-9]*(?:[0-9]+-){0,2}([0-9]{4})\b', re.IGNORECASE)
        date_pattern = re.compile(r'For the Period .*?(?:through|to)\s*(\d{1,2}/\d{1,2}/\d{2,4})', re.IGNORECASE)
        arc_impact_pattern = re.compile(r'(ARC[\s-]IMPACT\s+PROGRAM(?:\s+(?:ERIE|SWPA|LIMA|PITTSBURGH|BUFFALO|HARTFORD|CUYAHOGA|CT))?(?:\s+LLC)?)', re.IGNORECASE)
        account_name_patterns = [ # Keep your specific patterns
            re.compile(r'ARCTARIS\s+PRODUCT\s+DEV(?:ELOPMENT)?\s+([IVX]+)', re.IGNORECASE),
            re.compile(r'ARCTARIS\s+PRODUCT\s+DEV(?:ELOPMENT)?\s+(\d+)', re.IGNORECASE),
            re.compile(r'PRODUCT\s+DEV(?:ELOPMENT)?\s+([IVX]+|[0-9]+)', re.IGNORECASE),
            re.compile(r'PHASE\s+([0-9]+[A-Z]?)\s+HOLDINGS', re.IGNORECASE)
        ]
        fund_patterns = [ # Keep your specific patterns
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

        logging.debug(f"PNC: Starting line processing. Sensitive accounts: {len(sensitive_accounts)}")
        for i, line in enumerate(lines):
            if not line.strip() or sensitive_match_made: break
            logging.log(logging.DEBUG - 5 , f"PNC Line {i+1}: {line.strip()}")

            # 1. Attempt Number Extraction & Sensitive Match
            potential_account_num = None
            if not account_found:
                match = account_pattern.search(line) or account_last4_pattern.search(line)
                if match: 
                    potential_account_num = match.group(1)
                    # Check sensitive list FIRST
                    sensitive_match = self._find_sensitive_match_by_number(potential_account_num, sensitive_accounts)
                    if sensitive_match:
                        statement_info.account_number = sensitive_match['number']
                        statement_info.account_name = sensitive_match['name']
                        logging.info(f"PNC: Confirmed account via sensitive number match: {statement_info.account_name}")
                        account_found = fund_found = sensitive_match_made = True 
                        continue # Go to next line, we have definitive info
                    else: 
                        # No sensitive match, store tentative regex result
                        num = potential_account_num
                        statement_info.account_number = num.replace('-', '') if '-' in num or len(num) > 4 else f"xxxx{num[-4:]}"
                        account_found = True # Mark as found, but not definitive
                        logging.debug(f"PNC: Regex found potential account '{statement_info.account_number}', no sensitive match.")

            # 2. Attempt Name Extraction & Sensitive Match
            if not fund_found:
                potential_fund_name = None
                # --- Start: Keep your existing Regex logic for finding potential_fund_name ---
                match = arc_impact_pattern.search(line)
                if match: 
                    potential_fund_name = re.sub(r'ARC[\\s-]IMPACT', 'ARC-IMPACT', match.group(1), flags=re.IGNORECASE).upper().strip()
                else:
                    for pattern in account_name_patterns:
                        match = pattern.search(line)
                        if match:
                            if "PRODUCT DEV" in pattern.pattern.upper(): potential_fund_name = f"ARCTARIS PRODUCT DEV {match.group(1)}".upper()
                            elif "PHASE" in pattern.pattern.upper(): potential_fund_name = f"PHASE {match.group(1)} HOLDINGS".upper()
                            break
                    if not potential_fund_name:
                        for pattern in fund_patterns:
                            match = pattern.search(line)
                            if match:
                                extracted = match.group(1).strip(); cleaned = extracted.replace(',','').replace('.','')
                                cleaned = re.sub(r'\s+Tax\s+ID.*$', '', cleaned, flags=re.IGNORECASE).strip(); cleaned = re.sub(r'\s+', ' ', cleaned).upper()
                                if "ARC IMPACT" in cleaned: cleaned = cleaned.replace("ARC IMPACT", "ARC-IMPACT")
                                if len(cleaned) > 3 and "SUMMARY" not in cleaned:
                                    potential_fund_name = cleaned; break
                # --- End: Keep your existing Regex logic for finding potential_fund_name ---
                
                if potential_fund_name:
                    # Check sensitive list FIRST
                    sensitive_match = self._find_sensitive_match_by_name(potential_fund_name, sensitive_accounts)
                    if sensitive_match:
                        statement_info.account_name = sensitive_match['name']
                        fund_found = True
                        if not account_found: # Found name first, get number from sensitive data
                            statement_info.account_number = sensitive_match['number']
                            account_found = True
                            sensitive_match_made = True # Definitive match now
                            logging.info(f"PNC: Confirmed account via sensitive name match: {statement_info.account_name}")
                            continue # Go to next line
                        else:
                            # Account number found earlier (maybe tentatively), now name confirmed
                            logging.info(f"PNC: Confirmed name via sensitive match: {statement_info.account_name} (num found earlier)")
                            # Should we mark sensitive_match_made = True here too? Maybe, depends if number match is better. Let's be conservative.
                    else: 
                        # No sensitive match, store tentative regex result
                        statement_info.account_name = potential_fund_name
                        fund_found = True # Mark as found, but not definitive
                        logging.debug(f"PNC: Regex found potential name '{potential_fund_name}', no sensitive match.")

            # 3. Attempt Date Extraction (can run independently)
            if not date_found:
                match = date_pattern.search(line)
                if match: 
                    parsed_date = self._parse_date(match.group(1).strip(), ['%m/%d/%Y', '%m/%d/%y'])
                    if parsed_date: 
                        statement_info.date = parsed_date
                        date_found = True
                        logging.debug(f"PNC: Found date {parsed_date:%Y-%m-%d}")
                        continue # Go to next line
        
        # --- Fallback Logic --- (Only run if no definitive sensitive match was made)
        if not sensitive_match_made:
            logging.debug(f"PNC: No definitive sensitive match, running fallback logic.")
            # Reset any tentatively found name from regex if sensitive match failed
            statement_info.account_name = None 
            fund_found = False # Reset this flag too
            
            # Try mapping only if account number was found (even tentatively)
            if account_found and statement_info.account_number:
                acc_num = statement_info.account_number # The one found by regex (might be xxxx...)
                last4 = acc_num[-4:]
                if not acc_num.startswith('xxxx') and acc_num in pnc_mappings: 
                    statement_info.account_name = pnc_mappings[acc_num]
                    fund_found = True # Mark as found via fallback
                    logging.debug(f"PNC: Fallback map from full regex num {acc_num}")
                elif last4 in arc_impact_mappings: 
                    statement_info.account_name = arc_impact_mappings[last4]
                    fund_found = True # Mark as found via fallback
                    logging.debug(f"PNC: Fallback map from last4 {last4}")
        
        # --- Final Defaults --- 
        # Set default name only if no name was found by sensitive data OR fallback mapping
        if not statement_info.account_name: 
            if account_found and statement_info.account_number: 
                # Use account number (prefer last 4 if possible) for default if number is known
                default_suffix = statement_info.account_number[-4:]
                statement_info.account_name = f"PNC Account {default_suffix}"
            else:
                 # Absolute fallback if no number or name known
                 statement_info.account_name = "UNKNOWN PNC ACCOUNT"
            logging.warning(f"PNC: Using default name: {statement_info.account_name}")
        # Set default date only if no date was found
        if not statement_info.date:
            logging.warning(f"PNC: Using fallback date.")

    def get_filename(self, statement_info: StatementInfo) -> str:
        """ PNC Filename: [Account Name] [Original Filename].pdf (Simplified based on user request) """
        account_name = statement_info.account_name or "Unknown_PNC_Account"
        original_filename = statement_info.original_filename

        if not original_filename:
            logging.warning("PNCStrategy: Original filename missing in StatementInfo. Using fallback name.")
            # Fallback: construct something basic, though ideally original_filename is always present
            account_number_clean = self._sanitize_filename(statement_info.account_number or "UNKNOWN_ACCOUNT_NUM", allow_spaces=False)
            date_str = "NODATE" # Cannot get date from original if it's missing
            clean_account_name_fallback = self._sanitize_filename(account_name, allow_spaces=True)
            return f"{clean_account_name_fallback} statement_{account_number_clean}_{date_str}.pdf" # Fallback to old format attempt

        # Extract the base name from the original filename (e.g., file.pdf from /path/to/file.pdf)
        original_basename = os.path.basename(original_filename)

        # Sanitize the account name (obtained from extract_info/sensitive matching)
        clean_account_name = self._sanitize_filename(account_name, allow_spaces=True)

        # Construct the new filename by prepending the sanitized name to the original basename
        # Ensure there's a space between the name and the original filename part
        new_filename = f"{clean_account_name} {original_basename}"

        # Limit length if necessary
        max_len = 200
        if len(new_filename) > max_len:
             original_filename_for_log = statement_info.original_filename or "unknown.pdf"
             # Ensure the extension is preserved during truncation
             base, ext = os.path.splitext(new_filename) # Use new_filename here
             # Check if original_basename already had an extension we need to preserve
             orig_base, orig_ext = os.path.splitext(original_basename)
             if not ext and orig_ext: # If new_filename lost extension, use original
                 ext = orig_ext
             elif not ext and not orig_ext: # If neither had extension, default to .pdf
                 ext = ".pdf"
                 
             cutoff = max_len - len(ext) - 3 # Make space for "..." and extension
             # Make sure cutoff doesn't result in negative index
             cutoff = max(0, cutoff) 
             # Reconstruct base from the parts we have
             base_part1 = clean_account_name
             base_part2 = orig_base # Use original base name without extension
             full_base = f"{base_part1} {base_part2}"
             
             new_filename = full_base[:cutoff] + "..." + ext
             logging.warning(f"PNCStrategy: Truncated filename for {original_filename_for_log} due to length: {new_filename}")
             
        # Ensure the final filename has a .pdf extension if it was lost somehow
        if not new_filename.lower().endswith('.pdf'):
            base, ext = os.path.splitext(new_filename)
            if ext: # If there's an extension but it's not pdf
                new_filename = base + ".pdf"
            else: # If there's no extension
                 new_filename = new_filename + ".pdf"
                 
        return new_filename

    def get_subfolder_path(self, statement_info: StatementInfo) -> str:
        """ Subfolder: PNC (Simplified based on user request) """
        # Simply return the bank name to place all PNC files in the base PNC folder.
        return self.get_bank_name()


class BerkshireStrategy(BankStrategy):
    """Strategy for processing Berkshire Bank statements."""

    def get_bank_name(self) -> str:
        return "Berkshire"

    def extract_info(self, lines: List[str], statement_info: StatementInfo):
        # Initialize
        statement_info.bank_type = self.get_bank_name()
        mappings = self.config.get_account_mappings("berkshire_last4") # Keep for fallback
        sensitive_accounts = self.config.get_sensitive_accounts(self.get_bank_name())
        original_filename = statement_info.original_filename or ""
        is_new_statement_format = "newstatement" in original_filename.lower() or "new_statement" in original_filename.lower()
        account_found = False; fund_found = False; date_found = False; sensitive_match_made = False
        
        # Keep your existing Regex patterns here
        account_patterns = [ # Keep your specific patterns
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

        # Handle NewStatement format via sensitive filename heuristic FIRST
        if is_new_statement_format:
            logging.info(f"Berkshire: Detected NewStatement format. Checking filename heuristic.")
            match = re.search(r'_(\d{4})(?:\\.pdf)?$', original_filename)
            if match:
                potential_last4 = match.group(1)
                sensitive_match = self._find_sensitive_match_by_number(potential_last4, sensitive_accounts)
                if sensitive_match:
                    statement_info.account_number = sensitive_match['number']
                    statement_info.account_name = sensitive_match['name']
                    logging.info(f"Berkshire: Confirmed NewStatement via sensitive filename match ({potential_last4}): {statement_info.account_name}")
                    account_found = fund_found = sensitive_match_made = date_found = True # Mark all as found
                    statement_info.date = datetime.now() # Use fallback date for these
                    return # Exit early, definitive match from filename
                else: 
                    logging.debug(f"Berkshire: NewStatement last4 '{potential_last4}' found, no sensitive match.")
            else: 
                logging.debug(f"Berkshire: Could not extract last4 from NewStatement filename '{original_filename}'.")
            # If no sensitive match from filename, proceed to line scan unless we should stop?
            # For now, let's assume we proceed if no sensitive match.
            if not sensitive_match_made: 
                 logging.debug("Berkshire: No sensitive match from NewStatement filename, proceeding to line scan.")

        # Process lines (unless already matched via NewStatement filename)
        if not sensitive_match_made:
             logging.debug(f"Berkshire: Starting line processing. Sensitive accounts: {len(sensitive_accounts)}")
             for i, line in enumerate(lines):
                 if not line.strip() or sensitive_match_made: break
                 logging.log(logging.DEBUG - 5 , f"Berkshire Line {i+1}: {line.strip()}")

                 # 1. Attempt Number Extraction & Sensitive Match
                 potential_account_num = None
                 if not account_found:
                     for pattern in account_patterns:
                         match = pattern.search(line)
                         if match: potential_account_num = match.group(1); break
                     if potential_account_num:
                         sensitive_match = self._find_sensitive_match_by_number(potential_account_num, sensitive_accounts)
                         if sensitive_match:
                             statement_info.account_number = sensitive_match['number']
                             statement_info.account_name = sensitive_match['name']
                             logging.info(f"Berkshire: Confirmed account via sensitive number match: {statement_info.account_name}")
                             account_found = fund_found = sensitive_match_made = True; continue
                         else: # Tentative regex match
                             num = potential_account_num; last4 = num[-4:]
                             statement_info.account_number = num if len(num) > 4 and not num.startswith('xxxx') else f"xxxx{last4}"
                             account_found = True; logging.debug(f"Berkshire: Regex found potential account '{statement_info.account_number}', no sensitive match.")

                 # 2. Attempt Name Extraction & Sensitive Match
                 if not fund_found:
                     potential_fund_name = None
                     # --- Start: Keep your existing Regex logic for finding potential_fund_name ---
                     for pattern in fund_patterns:
                         match = pattern.search(line)
                         if match:
                             extracted = match.group(1).strip(); cleaned = re.sub(r'\s+', ' ', extracted).upper()
                             if len(cleaned) > 5 and "ACCOUNT SUMMARY" not in cleaned and "STATEMENT OF" not in cleaned:
                                 potential_fund_name = cleaned; break
                     # --- End: Keep your existing Regex logic ---
                     
                     if potential_fund_name:
                         sensitive_match = self._find_sensitive_match_by_name(potential_fund_name, sensitive_accounts)
                         if sensitive_match:
                             statement_info.account_name = sensitive_match['name']; fund_found = True
                             if not account_found: # Found name first
                                 statement_info.account_number = sensitive_match['number']; account_found = True; sensitive_match_made = True
                                 logging.info(f"Berkshire: Confirmed account via sensitive name match: {statement_info.account_name}")
                                 continue
                             else: logging.info(f"Berkshire: Confirmed name via sensitive match: {statement_info.account_name} (num found earlier)")
                         else: # Tentative regex name match
                             statement_info.account_name = potential_fund_name; fund_found = True
                             logging.debug(f"Berkshire: Regex found potential name '{potential_fund_name}', no sensitive match.")

                 # 3. Attempt Date Extraction
                 if not date_found:
                     match = date_pattern.search(line) or period_end_date_pattern.search(line)
                     if match: 
                         parsed_date = self._parse_date(match.group(1), ['%m/%d/%Y', '%m/%d/%y'])
                         if parsed_date: 
                             statement_info.date = parsed_date; date_found = True; logging.debug(f"Berkshire: Found date {parsed_date:%Y-%m-%d}"); continue
        
        # --- Fallback Logic --- (Only if no sensitive match was definitive)
        if not sensitive_match_made:
            logging.debug(f"Berkshire: No definitive sensitive match, running fallback logic.")
            # Try mapping only if fund wasn't found yet and account number was found (even tentatively)
            if account_found and not fund_found and statement_info.account_number: 
                acc_num = statement_info.account_number # The one found by regex
                last4 = acc_num[-4:] if len(acc_num) >= 4 else None
                if last4 and last4 in mappings: 
                    statement_info.account_name = mappings[last4]
                    fund_found = True # Mark as found via fallback
                    logging.debug(f"Berkshire: Fallback map from regex last4 {last4}")

        # --- Final Defaults ---
        if not statement_info.account_name: 
            last4 = statement_info.account_number[-4:] if account_found and len(statement_info.account_number) >= 4 else "XXXX"
            statement_info.account_name = f"BERKSHIRE ACCOUNT {last4}"
            logging.warning(f"Berkshire: Using default name: {statement_info.account_name}")
        if not statement_info.date:
            logging.warning(f"Berkshire: Using fallback date.")

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
             cutoff = max_len - len(ext) - 3 # Make space for "..."
             filename = base[:cutoff] + "..." + ext
             logging.warning(f"BerkshireStrategy: Truncated filename to {max_len} chars: {filename}")
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
        # Initialize
        statement_info.bank_type = self.get_bank_name()
        mappings = self.config.get_account_mappings("cambridge_name_substring") # Keep for fallback
        sensitive_accounts = self.config.get_sensitive_accounts(self.get_bank_name())
        account_found = False; fund_found = False; date_found = False; sensitive_match_made = False
        full_text = "\n".join(lines) # For multiline regex if needed
        
        # Keep your existing Regex patterns here
        account_pattern = re.compile(r'Account(?: Number)?:?\s*(\d+-?\d+)\b', re.IGNORECASE)
        fund_patterns = [ # Keep your specific patterns (including multiline ones)
            re.compile(r'^(ARCTARIS\s+[A-Za-z0-9\s-]+(?:LLC|LP|INC)?)$', re.IGNORECASE),
            re.compile(r'^([A-Z\s&\d,-]+(?:LLC|LP|INC))\s*\r?$', re.MULTILINE), 
            # ... etc (Ensure other patterns here are also correct)
            re.compile(r'^(SUB[- ]?CDE\s+\d+\s+LLC)$', re.IGNORECASE), # Example: Ensure others are also correct
            re.compile(r'^([A-Za-z0-9\s,.\-]+(?:\s+LLC|\s+LP|\s+INC))$', re.IGNORECASE) # Example: Ensure others are also correct
        ]
        date_pattern = re.compile(r'Statement Date[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})', re.IGNORECASE)
        period_date_pattern = re.compile(r'Statement Period[:\s]*.*?\s+to\s+(\d{1,2}/\d{1,2}/\d{2,4})', re.IGNORECASE)

        logging.debug(f"Cambridge: Starting line processing. Sensitive accounts: {len(sensitive_accounts)}")
        for i, line in enumerate(lines):
            if not line.strip() or sensitive_match_made: break
            logging.log(logging.DEBUG - 5 , f"Cambridge Line {i+1}: {line.strip()}")

            # 1. Attempt Number Extraction & Sensitive Match
            potential_account_num = None
            if not account_found:
                match = account_pattern.search(line)
                if match: potential_account_num = match.group(1).replace('-', '')
                if potential_account_num:
                    sensitive_match = self._find_sensitive_match_by_number(potential_account_num, sensitive_accounts)
                    if sensitive_match:
                        statement_info.account_number = sensitive_match['number']
                        statement_info.account_name = sensitive_match['name']
                        logging.info(f"Cambridge: Confirmed account via sensitive number match: {statement_info.account_name}")
                        account_found = fund_found = sensitive_match_made = True; continue
                    else: # Tentative regex match
                        statement_info.account_number = potential_account_num; account_found = True
                        logging.debug(f"Cambridge: Regex found potential account '{potential_account_num}', no sensitive match.")

            # 2. Attempt Name Extraction & Sensitive Match
            if not fund_found:
                potential_fund_name = None
                # --- Start: Keep your existing Regex logic for finding potential_fund_name ---
                for pattern in fund_patterns:
                     # Use full_text for multiline patterns, line for others
                     text_to_search = full_text if pattern.flags & re.MULTILINE else line
                     match = pattern.search(text_to_search)
                     if match:
                         extracted = match.group(1).strip(); cleaned = re.sub(r'\s+', ' ', extracted).upper()
                         # Add your specific validation logic here
                         if len(cleaned) > 5 and "ACCOUNT ACTIVITY" not in cleaned: 
                             potential_fund_name = cleaned; break 
                # --- End: Keep your existing Regex logic ---
                
                if potential_fund_name:
                    sensitive_match = self._find_sensitive_match_by_name(potential_fund_name, sensitive_accounts)
                    if sensitive_match:
                        statement_info.account_name = sensitive_match['name']; fund_found = True
                        if not account_found: # Found name first
                            statement_info.account_number = sensitive_match['number']; account_found = True; sensitive_match_made = True
                            logging.info(f"Cambridge: Confirmed account via sensitive name match: {statement_info.account_name}")
                            continue
                        else: logging.info(f"Cambridge: Confirmed name via sensitive match: {statement_info.account_name} (num found earlier)")
                    else: # Tentative regex name match
                        statement_info.account_name = potential_fund_name; fund_found = True
                        logging.debug(f"Cambridge: Regex found potential name '{potential_fund_name}', no sensitive match.")

            # 3. Attempt Date Extraction
            if not date_found:
                match = date_pattern.search(line) or period_date_pattern.search(line)
                if match: 
                    parsed_date = self._parse_date(match.group(1), ['%m/%d/%Y', '%m/%d/%y'])
                    if parsed_date: 
                        statement_info.date = parsed_date; date_found = True; logging.debug(f"Cambridge: Found date {parsed_date:%Y-%m-%d}"); continue

        # --- Fallback Logic ---
        if not sensitive_match_made:
            logging.debug(f"Cambridge: No definitive sensitive match, running fallback logic.")
            # Try substring mapping only if fund WAS found (tentatively) by regex but not sensitive, and mapping exists
            if fund_found and statement_info.account_name and mappings:
                current_name = statement_info.account_name; mapped_name = None
                for sub, mapped in mappings.items():
                    if sub.lower() in current_name.lower(): mapped_name = mapped; break
                if mapped_name: 
                    statement_info.account_name = mapped_name # Overwrite tentative name
                    logging.debug(f"Cambridge: Fallback map from substring '{sub}' of regex name '{current_name}'.")

        # --- Final Defaults ---
        if not statement_info.account_name: 
            last4 = statement_info.account_number[-4:] if account_found and len(statement_info.account_number) >= 4 else "XXXX"
            statement_info.account_name = f"CAMBRIDGE ACCOUNT {last4}"
            logging.warning(f"Cambridge: Using default name: {statement_info.account_name}")
        if not statement_info.date:
            logging.warning(f"Cambridge: Using fallback date.")

    def get_filename(self, statement_info: StatementInfo) -> str:
        """ Filename: [Account Name] [Account Number] Cambridge Savings [Month] [YYYY].pdf """
        account_name = statement_info.account_name or "Unknown Account"
        account_number = statement_info.account_number or "0000"
        month = statement_info.date.strftime("%B") if statement_info.date else "NoMonth"
        year = statement_info.date.strftime("%Y") if statement_info.date else "NoYear"

        # Clean name
        clean_name = self._sanitize_filename(account_name.upper())

        filename = f"{clean_name} {account_number} Cambridge Savings {month} {year}.pdf"
        return filename # Already sanitized name, rest is safe

    def get_subfolder_path(self, statement_info: StatementInfo) -> str:
        """ Subfolder: Cambridge / YYYY-MM """
        year_month = statement_info.date.strftime("%Y-%m") if statement_info.date else "UnknownDate"
        return os.path.join("Cambridge", year_month)


class BankUnitedStrategy(BankStrategy):
    """Strategy for processing BankUnited statements."""

    def get_bank_name(self) -> str:
        return "BankUnited"

    def extract_info(self, lines: List[str], statement_info: StatementInfo):
        # Initialize
        statement_info.bank_type = self.get_bank_name()
        mappings = self.config.get_account_mappings("bankunited_last4") # Keep for fallback
        sensitive_accounts = self.config.get_sensitive_accounts(self.get_bank_name())
        account_found = False; fund_found = False; date_found = False; sensitive_match_made = False
        
        # Keep your existing Regex patterns here
        account_pattern = re.compile(r'Account(?: Number)?:?\s*(\d+)\b', re.IGNORECASE)
        fund_patterns = [ # Keep your specific patterns
             re.compile(r'^(ARCTARIS\s+[A-Za-z0-9\s-]+(?:LLC|LP|INC)?)$?', re.IGNORECASE),
             re.compile(r'^(SUB[- ]?CDE\s+\d+\s+LLC)$?', re.IGNORECASE),
             # Look for ALL CAPS line that contains LLC/LP/INC
             re.compile(r'^([A-Z\s&\d,-]+(?:LLC|LP|INC))\s*\r?$'),
             # Generic LLC/LP finder
             re.compile(r'^([A-Za-z0-9\s,.\-]+(?:\s+LLC|\s+LP|\s+INC))$?', re.IGNORECASE)
        ]
        date_pattern = re.compile(r'Statement Date[:\s]*(\w+\s+\d{1,2},\s+\d{4})', re.IGNORECASE)
        period_date_pattern = re.compile(r'Statement Period\s+.*\s+-\s+(\w+\s+\d{1,2},\s+\d{4})', re.IGNORECASE)

        logging.debug(f"BankUnited: Starting line processing. Sensitive accounts: {len(sensitive_accounts)}")
        for i, line in enumerate(lines):
            if not line.strip() or sensitive_match_made: break
            logging.log(logging.DEBUG - 5 , f"BankUnited Line {i+1}: {line.strip()}")

            # 1. Attempt Number Extraction & Sensitive Match
            potential_account_num = None
            if not account_found:
                match = account_pattern.search(line)
                if match: potential_account_num = match.group(1)
                if potential_account_num:
                    sensitive_match = self._find_sensitive_match_by_number(potential_account_num, sensitive_accounts)
                    if sensitive_match:
                        statement_info.account_number = sensitive_match['number']
                        statement_info.account_name = sensitive_match['name']
                        logging.info(f"BankUnited: Confirmed account via sensitive number match: {statement_info.account_name}")
                        account_found = fund_found = sensitive_match_made = True; continue
                    else: # Tentative regex match
                        statement_info.account_number = potential_account_num; account_found = True
                        logging.debug(f"BankUnited: Regex found potential account '{potential_account_num}', no sensitive match.")
                        # Tentative map from last4 (do this early?)
                        if not fund_found: 
                            last4 = potential_account_num[-4:]
                            if last4 in mappings: 
                                statement_info.account_name = mappings[last4]
                                fund_found = True # Tentatively found name via mapping
                                logging.debug(f"BankUnited: Tentative map from regex last4 {last4}")

            # 2. Attempt Name Extraction & Sensitive Match
            if not fund_found: # Check again in case mapping above found it
                potential_fund_name = None
                # --- Start: Keep your existing Regex logic for finding potential_fund_name ---
                for pattern in fund_patterns:
                    match = pattern.search(line)
                    if match:
                        extracted = match.group(1).strip(); cleaned = re.sub(r'\s+', ' ', extracted).upper()
                        # Add your specific validation logic here
                        if len(cleaned) > 5 and "BANKUNITED" not in cleaned and "PAGE" not in cleaned:
                             potential_fund_name = cleaned; break
                # --- End: Keep your existing Regex logic ---
                
                if potential_fund_name:
                    sensitive_match = self._find_sensitive_match_by_name(potential_fund_name, sensitive_accounts)
                    if sensitive_match:
                        statement_info.account_name = sensitive_match['name']; fund_found = True
                        if not account_found: # Found name first
                            statement_info.account_number = sensitive_match['number']; account_found = True; sensitive_match_made = True
                            logging.info(f"BankUnited: Confirmed account via sensitive name match: {statement_info.account_name}")
                            continue
                        else: logging.info(f"BankUnited: Confirmed name via sensitive match: {statement_info.account_name} (num found earlier)")
                    else: # Tentative regex name match
                        statement_info.account_name = potential_fund_name; fund_found = True
                        logging.debug(f"BankUnited: Regex found potential name '{potential_fund_name}', no sensitive match.")

            # 3. Attempt Date Extraction
            if not date_found:
                match = date_pattern.search(line) or period_date_pattern.search(line)
                if match: 
                    parsed_date = self._parse_date(match.group(1), ['%B %d, %Y', '%b %d, %Y'])
                    if parsed_date: 
                        statement_info.date = parsed_date; date_found = True; logging.debug(f"BankUnited: Found date {parsed_date:%Y-%m-%d}"); continue
        
        # --- Fallback Logic ---
        if not sensitive_match_made:
            logging.debug(f"BankUnited: No definitive sensitive match, running fallback logic.")
            # If account was found (tentatively) but name wasn't confirmed by sensitive match
            if account_found and not fund_found and statement_info.account_number: 
                last4 = statement_info.account_number[-4:]
                if last4 in mappings: 
                    statement_info.account_name = mappings[last4]
                    fund_found = True # Mark as found via fallback
                    logging.debug(f"BankUnited: Fallback map from regex last4 {last4}")

        # --- Final Defaults ---
        if not statement_info.account_name: 
            last4 = statement_info.account_number[-4:] if account_found and len(statement_info.account_number) >= 4 else "XXXX"
            statement_info.account_name = f"BANKUNITED ACCOUNT {last4}"
            logging.warning(f"BankUnited: Using default name: {statement_info.account_name}")
        if not statement_info.date:
            logging.warning(f"BankUnited: Using fallback date.")

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