# bank_strategies.py
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
        statement_info.match_status = "Default_Name" # Initial status
        pnc_mappings = self.config.get_account_mappings("pnc") 
        arc_impact_mappings = self.config.get_account_mappings("pnc_special_mapping_last4")
        sensitive_accounts = self.config.get_sensitive_accounts(self.get_bank_name())
        account_found = False; fund_found = False; date_found = False; sensitive_match_made = False
        
        # Regex patterns (Generalized)
        # Old: r'(ARC[\\s-]IMPACT\\s+PROGRAM(?:\\s+(?:ERIE|SWPA|LIMA|PITTSBURGH|BUFFALO|HARTFORD|CUYAHOGA|CT))?(?:\\s+LLC)?)'
        arc_impact_pattern = re.compile(r'([A-Z\\s-]+IMPACT\\s+PROGRAM(?:\\s+([A-Z\\s-]+))?(?:\\s+LLC)?)', re.IGNORECASE) # Generalized ARC, and location list
        account_name_patterns = [
            # Old: r'ARCTARIS\\s+PRODUCT\\s+DEV(?:ELOPMENT)?\\s+([IVX]+)'
            re.compile(r'([A-Z\\s]+PRODUCT\\s+DEV(?:ELOPMENT)?)\\s+([IVX]+)', re.IGNORECASE), # Captures "Generic Product Dev" and Roman numeral separately
            # Old: r'ARCTARIS\\s+PRODUCT\\s+DEV(?:ELOPMENT)?\\s+(\\d+)'
            re.compile(r'([A-Z\\s]+PRODUCT\\s+DEV(?:ELOPMENT)?)\\s+(\\d+)', re.IGNORECASE), # Captures "Generic Product Dev" and number separately
            re.compile(r'(PRODUCT\\s+DEV(?:ELOPMENT)?)\\s+([IVX]+|[0-9]+)', re.IGNORECASE), # Already somewhat generic, captures "PRODUCT DEV" and num/roman
            # Old: r'PHASE\\s+([0-9]+[A-Z]?)\\s+HOLDINGS'
            re.compile(r'([A-Z\\s]+)\\s+([0-9]+[A-Z]?)\\s+([A-Z\\s]+)', re.IGNORECASE) # e.g. "ANY_WORDS NUMERIC_ID ANY_WORDS"
        ]
        fund_patterns = ['
            re.compile(r'([A-Z\\s]*[-]?\\s*CDE\\s+[0-9]+\\s+LLC)', re.IGNORECASE), # Generalized "
            re.compile(r'(?:[A-Z\\s]*-)?CDE[^A-Za-z0-9]*([0-9]+)[^A-Za-z0-9]*LLC', re.IGNORECASE), # 
            re.compile(r'((?:[A-Z\\s]*-)?CDE[^A-Za-z0-9]*[0-9]+[^A-Za-z0-9]*LLC)', re.IGNORECASE), # 
            re.compile(r'([A-Z\\s]+PRODUCT\\s+DEV(?:ELOPMENT)?\\s+(?:[IVX]+|[0-9]+))', re.IGNORECASE), # 
            re.compile(r'([A-Z\\s]+[^A-Za-z0-9]*(?:[A-Z\\s0-9\\-]+)[^A-Za-z0-9]*LLC)', re.IGNORECASE), # 
            re.compile(r'^([A-Za-z0-9\\s,.\\-]+)\\s+LLC', re.IGNORECASE), # Already generic
            re.compile(r'(?:[A-Z\\s]+)\\s+([A-Za-z0-9\\s,.\\-]+?)(?:\\s+LLC|$)', re.IGNORECASE), # 
            re.compile(r'([A-Za-z0-9\\s,.\\-]+FUND[A-Za-z0-9\\s,.\\-]*) ', re.IGNORECASE), # A
            re.compile(r'([A-Za-z]+\\s+[A-Z\\s]+[A-Za-z\\s]+)', re.IGNORECASE), # Generalized "EAST COAST"
            re.compile(r'([A-Za-z]+\\s+OPPORTUNITY\\s+ZONE[A-Za-z\\s]+)', re.IGNORECASE) # 
        ]

        logging.debug(f"PNC: Starting line processing. Sensitive accounts: {len(sensitive_accounts)}")
        for i, line in enumerate(lines):
            if not line.strip(): break
            if sensitive_match_made and date_found: break # Optimization: if definitive match and date, stop early
            logging.log(logging.DEBUG - 5 , f"PNC Line {i+1}: {line.strip()}")

            # 1. Attempt Number Extraction & Sensitive Match
            potential_account_num = None
            if not account_found:
                match = account_pattern.search(line) or account_last4_pattern.search(line)
                if match: 
                    potential_account_num = match.group(1)
                    sensitive_match = self._find_sensitive_match_by_number(potential_account_num, sensitive_accounts)
                    if sensitive_match:
                        statement_info.account_number = sensitive_match['number']
                        statement_info.account_name = sensitive_match['name']
                        statement_info.match_status = "Success! (Sensitive Number)"
                        logging.info(f"PNC: Confirmed account via sensitive number match: {statement_info.account_name}")
                        account_found = fund_found = sensitive_match_made = True 
                        # continue # Removed continue to allow date search on same line
                    else: 
                        num = potential_account_num
                        statement_info.account_number = num.replace('-', '') if '-' in num or len(num) > 4 else f"xxxx{num[-4:]}"
                        statement_info.match_status = "Regex Match (Review)" # Tentative
                        account_found = True
                        logging.debug(f"PNC: Regex found potential account '{statement_info.account_number}', no sensitive match.")

            # 2. Attempt Name Extraction & Sensitive Match
            if not fund_found or not sensitive_match_made: # Try even if num found, to confirm/upgrade name
                potential_fund_name = None
                match = arc_impact_pattern.search(line)
                if match: 
                  
                    base_name = match.group(1)
                    
                    potential_fund_name = base_name.upper().strip()

                else:
                    for idx, pattern in enumerate(account_name_patterns):
                        match = pattern.search(line)
                        if match:
                            # Adjust construction based on new capture groups
                            if idx == 0 or idx == 1: # For "Generic Product Dev" + Roman/Number
                                potential_fund_name = f"{match.group(1)} {match.group(2)}".upper().strip()
                            elif idx == 2: # 
                                potential_fund_name = f"{match.group(1)} {match.group(2)}".upper().strip()
                            elif idx == 3: # For "ANY_WORDS NUMERIC_ID ANY_WORDS" 
                                potential_fund_name = f"{match.group(1)} {match.group(2)} {match.group(3)}".upper().strip()
                            break
                    if not potential_fund_name:
                        for pattern in fund_patterns:
                            match = pattern.search(line)
                            if match:
                                extracted = match.group(1).strip(); cleaned = extracted.replace(',','').replace('.','')
                                cleaned = re.sub(r'\s+Tax\s+ID.*$', '', cleaned, flags=re.IGNORECASE).strip(); cleaned = re.sub(r'\s+', ' ', cleaned).upper()
                                if len(cleaned) > 3 and "SUMMARY" not in cleaned:
                                    potential_fund_name = cleaned; break
                
                if potential_fund_name:
                    sensitive_match = self._find_sensitive_match_by_name(potential_fund_name, sensitive_accounts)
                    if sensitive_match:
                        statement_info.account_name = sensitive_match['name']
                        statement_info.match_status = "Success! (Sensitive Name)" # Upgrade/set status
                        fund_found = True
                        if not account_found: 
                            statement_info.account_number = sensitive_match['number']
                            account_found = True
                        elif statement_info.account_number != sensitive_match['number']:
                            logging.warning(f"PNC: Sensitive name '{statement_info.account_name}' num {sensitive_match['number']} != earlier num {statement_info.account_number}. Prioritizing sensitive.")
                            statement_info.account_number = sensitive_match['number']
                        sensitive_match_made = True # Definitive match for name (and possibly number)
                        logging.info(f"PNC: Confirmed account via sensitive name match: {statement_info.account_name}")
                    elif not sensitive_match_made: # Only set tentative name if no sensitive match confirmed anything yet
                        statement_info.account_name = potential_fund_name
                        if statement_info.match_status not in ["Success! (Sensitive Number)"]:
                            statement_info.match_status = "Regex Match (Review)"
                        fund_found = True
                        logging.debug(f"PNC: Regex found potential name '{potential_fund_name}', no sensitive match.")

            # 3. Attempt Date Extraction
            if not date_found:
                match = date_pattern.search(line)
                if match: 
                    parsed_date = self._parse_date(match.group(1).strip(), ['%m/%d/%Y', '%m/%d/%y'])
                    if parsed_date: 
                        statement_info.date = parsed_date
                        date_found = True
                        logging.debug(f"PNC: Found date {parsed_date:%Y-%m-%d}")

            if sensitive_match_made and date_found: break # Re-check for early exit

        # --- Fallback Logic --- 
        if not sensitive_match_made:
            logging.debug(f"PNC: No definitive sensitive match, running fallback logic.")
            # Reset regex-found name if it wasn't confirmed by sensitive match or mapping
            # statement_info.account_name = None # This might be too aggressive if regex name was good but no mapping exists
            # fund_found = False 
            
            if account_found and statement_info.account_number:
                acc_num_for_map = statement_info.account_number 
                last4_for_map = acc_num_for_map[-4:]
                mapped_name = None
                if not acc_num_for_map.startswith('xxxx') and acc_num_for_map in pnc_mappings: 
                    mapped_name = pnc_mappings[acc_num_for_map]
                    logging.debug(f"PNC: Fallback map from full regex num {acc_num_for_map}")
                elif last4_for_map in arc_impact_mappings: 
                    mapped_name = arc_impact_mappings[last4_for_map]
                    logging.debug(f"PNC: Fallback map from last4 {last4_for_map}")
                
                if mapped_name:
                    statement_info.account_name = mapped_name
                    statement_info.match_status = "Fallback (Mapping)"
                    fund_found = True # Fund name is now considered found via mapping
        
        # --- Final Defaults & Status Refinement ---
        if not statement_info.account_name: 
            if account_found and statement_info.account_number: 
                default_suffix = statement_info.account_number[-4:]
                statement_info.account_name = f"PNC Account {default_suffix}"
            else:
                 statement_info.account_name = "UNKNOWN PNC ACCOUNT"
            statement_info.match_status = "Fallback (Default)"
            logging.warning(f"PNC: Using default name: {statement_info.account_name}")
        
        if not statement_info.date:
            logging.warning(f"PNC: Using fallback date (current date). No date found in statement.")
            # statement_info.date = datetime.now() # Or keep as None if preferred for checklist
            # if "Success!" in statement_info.match_status: statement_info.match_status = "Partial (No Date)" # Optional downgrade

        # Final status check: if it's still Default_Name, determine best fit
        if statement_info.match_status == "Default_Name":
            if sensitive_match_made: # This should have set a Success! status already
                pass # Should not happen if logic above is correct
            elif fund_found: # Implies name was found by regex or mapping
                # If by mapping, status is already Fallback (Mapping). If by regex, it should be Regex Match
                # This state needs careful thought - if fund_found is true but status is Default_Name, it's an issue.
                # For now, assume previous logic set it. If it truly is Default_Name here, it means regex failed too.
                if statement_info.account_name and "PNC Account" not in statement_info.account_name and "UNKNOWN" not in statement_info.account_name:
                    statement_info.match_status = "Regex Match (Review)" # Likely a regex name without sensitive/map
                else:
                    statement_info.match_status = "Fallback (Default)"
            elif account_found: # Only number found by regex
                statement_info.match_status = "Regex Match (Review)"
            else: # Nothing significant found
                statement_info.match_status = "Fallback (Default)"

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
        """ Subfolder: PNC / YYYY / Month """
        if statement_info.date:
            month_name = statement_info.date.strftime('%B') # Full month name, e.g., "April"
            year = statement_info.date.strftime('%Y') # 4-digit year
            # Construct path: PNC / 2025 / April
            return os.path.join(self.get_bank_name(), year, month_name)
        else:
            # Fallback if date is missing
            return os.path.join(self.get_bank_name(), "UnknownDate")


class BerkshireStrategy(BankStrategy):
    """Strategy for processing Berkshire Bank statements."""

    def get_bank_name(self) -> str:
        return "Berkshire"

    def extract_info(self, lines: List[str], statement_info: StatementInfo):
        # Initialize
        statement_info.bank_type = self.get_bank_name()
        # Default status, assuming it will need manual review due to being image-based
        statement_info.match_status = "Manual Review (Image PDF)"
        
        sensitive_accounts = self.config.get_sensitive_accounts(self.get_bank_name())
        original_filename = statement_info.original_filename or ""
        
        account_found_by_filename = False
        date_found_by_filename = False

        # 1. Try to get info from filename (heuristic for "NewStatement" format)
        if "newstatement" in original_filename.lower() or "new_statement" in original_filename.lower():
            logging.info(f"Berkshire: Detected NewStatement format from filename: '{original_filename}'.")
            match = re.search(r'_(\d{4})(?:\\.pdf)?$', original_filename) # Looking for _XXXX.pdf
            if match:
                potential_last4 = match.group(1)
                sensitive_match = self._find_sensitive_match_by_number(potential_last4, sensitive_accounts)
                if sensitive_match:
                    statement_info.account_number = sensitive_match['number']
                    statement_info.account_name = sensitive_match['name']
                    # Upgrade status if filename heuristic with sensitive match works
                    statement_info.match_status = "Success! (Filename Heuristic)"
                    logging.info(f"Berkshire: Confirmed account via sensitive filename match ({potential_last4}): {statement_info.account_name}")
                    account_found_by_filename = True
                else: 
                    logging.debug(f"Berkshire: NewStatement last4 '{potential_last4}' from filename, no sensitive match.")
                    # If no sensitive match, but we got a last4, we can use it for a default name
                    statement_info.account_number = f"xxxx{potential_last4}"
                    statement_info.account_name = f"BERKSHIRE ACCOUNT {potential_last4}"
                    statement_info.match_status = "Fallback (Filename Heuristic)" # Better than just image, but not sensitive confirmed
                    account_found_by_filename = True 
            else: 
                logging.debug(f"Berkshire: Could not extract last4 from NewStatement filename '{original_filename}'.")
        
        # 2. Attempt to parse a date from filename (YYYY-MM-DD or YYYYMMDD)
        # This is a generic heuristic, not specific to NewStatement
        date_match_filename = re.search(r'(\d{4}[-_]?\d{2}[-_]?\d{2})', original_filename)
        if date_match_filename:
            date_str = date_match_filename.group(1).replace('-','').replace('_','')
            parsed_date = self._parse_date(date_str, ['%Y%m%d'])
            if parsed_date:
                statement_info.date = parsed_date
                date_found_by_filename = True
                logging.info(f"Berkshire: Extracted date '{parsed_date:%Y-%m-%d}' from filename.")
        # 3. Log based on text extraction result (passed in `lines`)
        if not lines or not any(line.strip() for line in lines):
            logging.warning(f"Berkshire: No text extracted for '{original_filename}'. Expected for image-based PDF. Processing based on filename if possible.")
        else:
            # 
            logging.warning(f"Berkshire: Text was unexpectedly extracted for '{original_filename}'. Strategy will still prioritize filename heuristics and assume manual review needed.")
            # We could potentially try a quick regex scan here if text *is* present, but it complicates the "manual handling" decision.
            # For now, stick to the image-based assumption primarily.

        # --- Final Fallback & Status for Berkshire (after filename checks) ---
        if not statement_info.account_name: 
            # If no name from filename heuristic, use a generic default
            num_part = statement_info.account_number[-4:] if statement_info.account_number and len(statement_info.account_number) >=4 else "XXXX"
            statement_info.account_name = f"BERKSHIRE ACCOUNT {num_part}"
            # If account_found_by_filename was false, status is still likely "Manual Review (Image PDF)"
            # If account was found by filename but not sensitive, it's "Fallback (Filename Heuristic)"
            # If no account info at all, it remains "Manual Review (Image PDF)" or becomes "Fallback (Default)"
            if not account_found_by_filename: # If filename didn't yield any account number
                statement_info.match_status = "Fallback (Default - Image PDF)" 
            logging.warning(f"Berkshire: Using default name: {statement_info.account_name}")

        if not statement_info.date:
            logging.warning(f"Berkshire: No date from filename or content. Using fallback date.")
            # For Berkshire image PDFs, a missing date is common. 
            # Status should remain focused on the image/manual aspect unless filename provided a date.
            # No specific status change here unless we want e.g. "Manual Review (Image PDF - No Date)"

        # If status is still the initial "Default_Name", it means no filename heuristic applied successfully.
        # This shouldn't happen if the logic above sets it to Manual Review or Fallback.
        if statement_info.match_status == "Default_Name":
            statement_info.match_status = "Manual Review (Image PDF)" # Ensure it defaults to this if nothing else set it

        logging.info(f"Berkshire: Final status for '{original_filename}': {statement_info.match_status}")

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
        statement_info.match_status = "Default_Name" # Initial status
        # mappings = self.config.get_account_mappings("cambridge_name_substring") # Not used in this structure
        sensitive_accounts = self.config.get_sensitive_accounts(self.get_bank_name())
        
        # Information buckets from extraction passes
        extracted_num_str: Optional[str] = None # Raw number from PDF
        normalized_extracted_num: Optional[str] = None # Number with dashes removed
        sensitive_num_match: Optional[Dict] = None
        potential_fund_name: Optional[str] = None
        sensitive_name_match: Optional[Dict] = None
        extracted_date: Optional[datetime] = None

        full_text = "\n".join(lines) 
        
        # Define Regex patterns
        # Landmark pattern for Cambridge account number (e.g., Account Number XXXXXX-XX)
        account_num_landmark_pattern = re.compile(r'^Account(?:\s+Number)?[\s#:]*(\d+-?\d+)\b', re.IGNORECASE | re.MULTILINE)
        fund_patterns = [ 
            re.compile(r'^([A-Z\s]+\s+[A-Za-z0-9\s-]+(?:LLC|LP|INC)?)$', re.IGNORECASE), # Generalized ARCTARIS
            re.compile(r'^([A-Z\s&\d,-]+(?:LLC|LP|INC))\s*\r?$', re.MULTILINE), 
            re.compile(r'^(SUB[- ]?CDE\s+\d+\s+LLC)$', re.IGNORECASE), 
            re.compile(r'(?:Owner|Name)[:\s]+([A-Z\s]+\s+[A-Za-z0-9\s-]+(?:LLC|LP|INC)?)', re.IGNORECASE), # Generalized ARCTARIS
            re.compile(r'(?:Owner|Name)[:\s]+(SUB[- ]?CDE\s+\d+\s+LLC)', re.IGNORECASE),
            re.compile(r'^([A-Za-z0-9\s,.\-]+(?:\s+LLC|\s+LP|\s+INC))$', re.IGNORECASE)
        ]
        # Date patterns remain the same (landmark search used in Pass 3)
        generic_date_pattern = re.compile(r'(\d{1,2}/\d{1,2}/\d{2,4})')
        date_parse_formats = ['%m/%d/%Y', '%m/%d/%y']

        logging.debug(f"Cambridge: Starting multi-pass extraction. Sensitive accounts: {len(sensitive_accounts)}")

        # --- Pass 1: Find Account Number via Landmark --- 
        logging.debug(f"Cambridge Pass 1: Searching for account number landmark.")
        num_match = account_num_landmark_pattern.search(full_text)
        if num_match:
            extracted_num_str = num_match.group(1) # Store raw number (with potential dash)
            normalized_extracted_num = extracted_num_str.replace('-', '')
            logging.debug(f"Cambridge Pass 1: Landmark found potential account number: '{extracted_num_str}' (Normalized: '{normalized_extracted_num}')")
            # Check sensitive list using normalized number
            sensitive_num_match = self._find_sensitive_match_by_number(normalized_extracted_num, sensitive_accounts)
            if sensitive_num_match:
                logging.info(f"Cambridge Pass 1: Sensitive number match found for '{normalized_extracted_num}': {sensitive_num_match['name']}")
            else:
                logging.debug(f"Cambridge Pass 1: Landmark number '{normalized_extracted_num}' not in sensitive list.")
        else:
             logging.debug(f"Cambridge Pass 1: Account number landmark pattern not found.")

        # --- Pass 2: Find Account Name --- 
        logging.debug(f"Cambridge Pass 2: Searching for account name.")
        for pattern in fund_patterns:
            match = pattern.search(full_text) # Search full text
            if match:
                extracted = match.group(1).strip(); cleaned = re.sub(r'\s+', ' ', extracted).upper()
                if len(cleaned) > 5 and "CAMBRIDGE SAVINGS BANK" not in cleaned and "PAGE" not in cleaned:
                    potential_fund_name = cleaned
                    logging.debug(f"Cambridge Pass 2: Regex found potential name '{potential_fund_name}'.")
                    break 
        if potential_fund_name:
            # Use slightly stricter threshold for Cambridge name matching
            sensitive_name_match = self._find_sensitive_match_by_name(potential_fund_name, sensitive_accounts, threshold=0.90)
            if sensitive_name_match:
                logging.info(f"Cambridge Pass 2: Sensitive name match found for '{potential_fund_name}': {sensitive_name_match['name']}")
            else:
                logging.debug(f"Cambridge Pass 2: Potential name '{potential_fund_name}' not in sensitive list (threshold 0.90).")
        else:
            logging.debug(f"Cambridge Pass 2: No potential account name found via regex.")

        # --- Validation & Status Assignment --- 
        logging.debug(f"Cambridge Validation: Num Match: {bool(sensitive_num_match)}, Name Match: {bool(sensitive_name_match)}, Extracted Num: {extracted_num_str}, Extracted Name: {potential_fund_name}")
        account_assigned = False
        if sensitive_num_match:
            # Priority 1: Sensitive number match
            statement_info.account_number = sensitive_num_match['number'] # Use canonical number
            statement_info.account_name = sensitive_num_match['name']
            statement_info.match_status = "Success! (Sensitive Number)"
            logging.debug(f"Validation outcome: Sensitive Number Match takes precedence.")
            account_assigned = True
        elif sensitive_name_match:
            # Priority 2: Sensitive name match (validate against extracted number)
            statement_info.account_name = sensitive_name_match['name']
            if normalized_extracted_num: # Check if number was found via landmark
                sensitive_num_normalized = sensitive_name_match['number'].replace('-', '')
                if normalized_extracted_num == sensitive_num_normalized:
                    statement_info.match_status = "Success! (Name & Num Verified)"
                    statement_info.account_number = extracted_num_str # Use number from PDF (with dash if present)
                    logging.debug(f"Validation outcome: Sensitive Name Verified against extracted number ({normalized_extracted_num}).")
                else:
                    statement_info.match_status = "Warning (Sensitive Name Match, Num Mismatch)"
                    statement_info.account_number = extracted_num_str # Use number from PDF, flag warning
                    logging.warning(f"Validation outcome: Sensitive Name Matched, BUT number mismatch (PDF Norm: {normalized_extracted_num}, Sensitive Norm: {sensitive_num_normalized}).")
            else:
                # Sensitive name matched, but no number extracted from PDF to verify
                statement_info.match_status = "Success! (Sensitive Name, Num Unverified)"
                statement_info.account_number = sensitive_name_match['number'] # Use number from sensitive entry
                logging.debug(f"Validation outcome: Sensitive Name Matched, Number from sensitive list (unverified in PDF).")
            account_assigned = True
        elif extracted_num_str: 
            # Priority 3: Number extracted via landmark regex, no sensitive match
            statement_info.account_number = extracted_num_str # Use number from PDF
            # No last4 mapping for Cambridge, need name from regex or default
            if potential_fund_name:
                statement_info.account_name = potential_fund_name
                statement_info.match_status = "Regex Match (Review)" # Both found by regex
                logging.debug(f"Validation outcome: Landmark number and Regex name found (no sensitive).")
            else:
                 num_part = statement_info.account_number 
                 statement_info.account_name = f"CAMBRIDGE ACCOUNT {num_part}" # Default name
                 statement_info.match_status = "Regex Match (Review)" # Found number but no name
                 logging.debug(f"Validation outcome: Landmark number found, no name found.")
            account_assigned = True
        elif potential_fund_name: 
            # Priority 4: Only name extracted via regex, no sensitive match
            statement_info.account_name = potential_fund_name
            statement_info.match_status = "Regex Match (Review)"
            statement_info.account_number = None 
            logging.debug(f"Validation outcome: Regex name found, no number found.")
            account_assigned = True
        else:
            # Priority 5: Nothing significant found
            statement_info.match_status = "Fallback (Default)"
            statement_info.account_name = "CAMBRIDGE UNKNOWN ACCOUNT"
            statement_info.account_number = None
            logging.debug(f"Validation outcome: No number or name found.")
            account_assigned = True # Mark as assigned even if default

        # --- Pass 3: Find Date via Landmark --- 
        logging.debug(f"Cambridge Pass 3: Searching for date.")
        date_found = False
        for i, line in enumerate(lines):
            if date_found: break
            search_line_lower = line.lower()
            if "statement period" in search_line_lower or "statement date" in search_line_lower:
                logging.debug(f"Cambridge Date Search: Found landmark on line {i}: '{line.strip()}'")
                window_lines = lines[i : min(i + 3, len(lines))]
                search_window_text = "\n".join(window_lines)
                logging.debug(f"Cambridge Date Search: Window text:\n---\n{search_window_text}\n---")
                possible_dates = generic_date_pattern.findall(search_window_text)
                logging.debug(f"Cambridge Date Search: Dates found in window: {possible_dates}")
                parsed_dates = []
                for date_str in possible_dates:
                     parsed = self._parse_date(date_str, date_parse_formats)
                     if parsed:
                          parsed_dates.append(parsed)
                     else:
                          logging.warning(f"Cambridge Date Search: Failed to parse potential date string: '{date_str}'")
                if parsed_dates:
                     extracted_date = max(parsed_dates) 
                     logging.debug(f"Cambridge: Found date {extracted_date:%Y-%m-%d} from landmark window search.")
                     date_found = True
                     break 
            if not date_found:
             logging.debug("Cambridge Date Search: Landmark search did not find a valid date.")
        # --- End Date Logic --- 

        # --- Final Assignment & Fallbacks ---
        statement_info.date = extracted_date # Assign date found (or None)
        if not statement_info.date:
            logging.warning(f"Cambridge: No date found. Using fallback date (None).")
            # Optional status adjustment: if "Success!" in statement_info.match_status... etc.
        
        # Final safety net for default name if missed
        if not account_assigned:
             logging.warning("Cambridge: Reached final fallback - account info assignment missed.")
             num_part = statement_info.account_number if statement_info.account_number else "UNKNOWN"
             statement_info.account_name = f"CAMBRIDGE ACCOUNT {num_part}"
             statement_info.match_status = "Fallback (Default)"
             logging.warning(f"Cambridge: Assigning default name post-validation: {statement_info.account_name}")

        logging.info(f"Cambridge: Final extraction result: Name='{statement_info.account_name}', Num='{statement_info.account_number}', Date='{statement_info.date}', Status='{statement_info.match_status}'")

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
        statement_info.match_status = "Default_Name" # Initial status
        mappings = self.config.get_account_mappings("bankunited_last4")
        sensitive_accounts = self.config.get_sensitive_accounts(self.get_bank_name())
        account_found = False; fund_found = False; date_found = False; sensitive_match_made = False
        full_text = "\n".join(lines) # Keep for potential multiline name patterns

        # Define Regex patterns
        # Pattern for ******1234 format near "Account Number" or "ACCOUNT #"
        masked_account_pattern = re.compile(r'(?:Account\s+Number|ACCOUNT\s+#)\s*.*?(\*+)(\d{4})\b', re.IGNORECASE)
        # Fallback pattern for potentially full account numbers
        account_pattern_fallback = re.compile(r'Account(?: Number)?:?\s*(\d+)\b', re.IGNORECASE)
        fund_patterns = [
             re.compile(r'^([A-Z\s]+\s+[A-Za-z0-9\s-]+(?:LLC|LP|INC)?)$', re.IGNORECASE), # Generalized ARCTARIS
             re.compile(r'^(SUB[- ]?CDE\s+\d+\s+LLC)$', re.IGNORECASE),
             re.compile(r'^([A-Z\s&\d,-]+(?:LLC|LP|INC))\s*\r?$'),
             re.compile(r'^([A-Za-z0-9\s,.\-]+(?:\s+LLC|\s+LP|\s+INC))$', re.IGNORECASE)
        ]
        # Date logic remains landmark-based from previous successful approach
        date_only_pattern = re.compile(r"(\w+\s+\d{1,2},\s+\d{4})")
        bankunited_date_formats = ['%B %d, %Y', '%b %d, %Y']

        logging.debug(f"BankUnited: Starting extraction (single-loop). Sensitive accounts: {len(sensitive_accounts)}")

        # --- Process lines for Account, Name, Date --- 
        for i, line in enumerate(lines):
            if not line.strip(): continue
            # Optimization: Stop if definitive match found for name/fund AND date found
            if sensitive_match_made and date_found: break 
            
            logging.log(logging.DEBUG - 5 , f"BankUnited Line {i+1}: {line.strip()}")

            # 1. Attempt Account Number Extraction (Masked first, then Fallback)
            if not account_found:
                potential_num_str = None
                is_masked = False
                match_masked = masked_account_pattern.search(line)
                if match_masked:
                    potential_num_str = match_masked.group(2) # The 4 digits
                    is_masked = True
                    logging.debug(f"BankUnited: Masked account pattern found last 4: '{potential_num_str}'")
                else:
                    match_fallback = account_pattern_fallback.search(line)
                    if match_fallback:
                        potential_num_str = match_fallback.group(1) # Full number
                        logging.debug(f"BankUnited: Fallback regex found potential account number: '{potential_num_str}'")
                
                # If any number pattern matched, check sensitive list
                if potential_num_str:
                    sensitive_match = self._find_sensitive_match_by_number(potential_num_str, sensitive_accounts)
                    if sensitive_match:
                        statement_info.account_number = sensitive_match['number'] # Use canonical number
                        statement_info.account_name = sensitive_match['name']
                        statement_info.match_status = "Success! (Sensitive Number)"
                        logging.info(f"BankUnited: Confirmed account via sensitive number match ('{potential_num_str}'): {statement_info.account_name}")
                        account_found = fund_found = sensitive_match_made = True
                    else:
                        # No sensitive match, store what we found
                        if is_masked:
                            statement_info.account_number = f"xxxx{potential_num_str}"
                        else:
                            statement_info.account_number = potential_num_str
                        account_found = True
                        statement_info.match_status = "Regex Match (Review)" # Tentative
                        logging.debug(f"BankUnited: Regex account '{statement_info.account_number}' not sensitive. Status: {statement_info.match_status}")
            
            # 2. Attempt Name Extraction & Validation (Skip if already confirmed by sensitive number)
            if not sensitive_match_made: 
                potential_fund_name = None
                # Loop through patterns to find name (using full_text for potential multiline names)
                for pattern in fund_patterns:
                    match = pattern.search(full_text)
                    if match:
                        extracted = match.group(1).strip(); cleaned = re.sub(r'\s+', ' ', extracted).upper()
                        if len(cleaned) > 5 and "BANKUNITED" not in cleaned and "PAGE" not in cleaned:
                            potential_fund_name = cleaned; break
                if potential_fund_name:
                    logging.debug(f"BankUnited: Regex found potential name '{potential_fund_name}'. Checking sensitive list (threshold 0.95).")
                    sensitive_name_match_entry = self._find_sensitive_match_by_name(potential_fund_name, sensitive_accounts, threshold=0.95)
                    
                    if sensitive_name_match_entry:
                        # Sensitive name match found! Validate against number found earlier.
                        logging.info(f"BankUnited: Confirmed name via sensitive match: {sensitive_name_match_entry['name']}")
                        final_status = ""
                        final_account_number = None 

                        if account_found and statement_info.account_number:
                            extracted_num_for_validation = statement_info.account_number
                            extracted_last4 = extracted_num_for_validation[-4:]
                            sensitive_last4 = sensitive_name_match_entry['number'][-4:]
                            if extracted_last4 == sensitive_last4:
                                final_status = "Success! (Name & Num Verified)"
                                # Use the number we extracted from PDF (masked or full)
                                final_account_number = extracted_num_for_validation 
                                logging.debug(f"BankUnited: Sensitive name validated: PDF num last4 ({extracted_last4}) matches sensitive last4.")
                            else:
                                final_status = "Warning (Sensitive Name Match, Num Mismatch)"
                                # Use number from PDF, but flag mismatch
                                final_account_number = extracted_num_for_validation 
                                logging.warning(f"BankUnited: Sensitive name '{sensitive_name_match_entry['name']}' matched, but PDF number last4 ({extracted_last4}) != sensitive number last4 ({sensitive_last4}).")
                        else:
                            # Sensitive name matched, but couldn't extract any number from PDF
                            final_status = "Success! (Sensitive Name, Num Unverified)"
                            final_account_number = sensitive_name_match_entry['number'] # Use number from sensitive entry
                            logging.debug(f"BankUnited: Sensitive name matched, but no number found in PDF to verify.")

                        # Assign validated/unverified info
                        statement_info.account_name = sensitive_name_match_entry['name']
                        statement_info.account_number = final_account_number
                        statement_info.match_status = final_status
                        fund_found = True
                        account_found = True # Account is considered found if name confirmed
                        sensitive_match_made = True
                    
                    elif not fund_found: # Regex name found, but no sensitive name match AND no earlier mapping/sensitive number match
                        statement_info.account_name = potential_fund_name
                        # Only update status if it wasn't set better by number regex/mapping
                        if statement_info.match_status not in ["Success! (Sensitive Number)", "Fallback (Mapping)"]:
                            statement_info.match_status = "Regex Match (Review)" 
                        fund_found = True
                        logging.debug(f"BankUnited: Regex name '{potential_fund_name}' found, but no sensitive match.")

            # 3. Attempt Date Extraction (Using landmark approach within the loop)
            if not date_found:
                 # ... (Date landmark logic remains the same) ...
                 search_line_lower = line.lower()
                 if "statement period" in search_line_lower or "statement date" in search_line_lower:
                     logging.debug(f"BankUnited Date Search: Found landmark on line {i+1}: '{line.strip()}'")
                     window_lines = lines[i : min(i + 3, len(lines))]
                     search_window_text = "\n".join(window_lines)
                     logging.debug(f"BankUnited Date Search: Window text:\n---\n{search_window_text}\n---")
                     possible_dates = date_only_pattern.findall(search_window_text)
                     logging.debug(f"BankUnited Date Search: Dates found in window: {possible_dates}")
                     parsed_dates = []
                     for date_str in possible_dates:
                         parsed = self._parse_date(date_str, bankunited_date_formats)
                         if parsed:
                             parsed_dates.append(parsed)
                         else:
                             logging.warning(f"BankUnited Date Search: Failed to parse potential date string: '{date_str}'")
                     if parsed_dates:
                         statement_info.date = max(parsed_dates) 
                         date_found = True
                         logging.debug(f"BankUnited: Found date {statement_info.date:%Y-%m-%d} from landmark window search.")
            
            # Check for early exit inside the loop if definitive match and date found
            if sensitive_match_made and date_found: break 

        # --- Fallbacks & Final Status Checks --- (After loop)
        # Apply last4 mapping if no sensitive match and account number IS known
        if not sensitive_match_made and account_found and not fund_found and statement_info.account_number:
             # Check if number is masked or full before getting last4
             num_for_mapping = statement_info.account_number
             last4 = num_for_mapping[-4:] if len(num_for_mapping) >= 4 else None
             if last4 and last4 in mappings:
                 statement_info.account_name = mappings[last4]
                 statement_info.match_status = "Fallback (Mapping)"
                 fund_found = True
                 logging.debug(f"BankUnited: Applied fallback mapping for last4 '{last4}'.")

        # Apply default name if still needed
        if not statement_info.account_name: 
            last4_default = statement_info.account_number[-4:] if account_found and statement_info.account_number and len(statement_info.account_number) >= 4 else "XXXX"
            statement_info.account_name = f"BANKUNITED ACCOUNT {last4_default}"
            if statement_info.match_status not in ["Success! (Sensitive Number)", "Fallback (Mapping)"]:
                 statement_info.match_status = "Fallback (Default)" 
            logging.warning(f"BankUnited: Using default name: {statement_info.account_name}")

        # Check date
        if not statement_info.date:
            logging.warning(f"BankUnited: Using fallback date (None).")
            # Optional status downgrade: if "Success!" in statement_info.match_status: statement_info.match_status += " (No Date)"

        # Final sanity check on status if it's still the initial default
        if statement_info.match_status == "Default_Name":
             if sensitive_match_made: pass # Should have been set higher
             elif fund_found: # Name found (by mapping or regex)
                 if statement_info.account_name in mappings.values(): # Check if name came from mapping
                     statement_info.match_status = "Fallback (Mapping)"
                 else: # Must have been regex name
                     statement_info.match_status = "Regex Match (Review)"
             elif account_found: # Only number found (masked or full) by regex
                 statement_info.match_status = "Regex Match (Review)"
             else: # Nothing found
                 statement_info.match_status = "Fallback (Default)"
        
        logging.info(f"BankUnited: Final extraction result: Name='{statement_info.account_name}', Num='{statement_info.account_number}', Date='{statement_info.date}', Status='{statement_info.match_status}'")

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
        statement_info.match_status = "Unlabeled (Generic Extraction)" # Default status for unlabeled
        logging.info(f"Executing UnlabeledStrategy for '{statement_info.original_filename}'. Attempting generic extraction.")
        
        # Simplified generic extraction - focus on any account number and any date
        account_pattern = re.compile(r'(?:Account|Acct|ACCOUNT|ACCT)[^0-9]*(?:[\dX]+-){0,2}([0-9]{4})\b', re.IGNORECASE)
        account_number_full_pattern = re.compile(r'(?:Account|Acct|ACCOUNT|ACCT)[^0-9]*(\d{6,})\b', re.IGNORECASE)
        account_last4 = None; account_number = None; account_found = False
        
        for line in lines:
            if account_found: break
            match = account_number_full_pattern.search(line)
            if match: 
                account_number = match.group(1)
                account_last4 = account_number[-4:]
                account_found = True
                logging.debug(f"Unlabeled: Found potential full account ending in {account_last4}"); break
            else: 
                match = account_pattern.search(line)
                if match: 
                    account_last4 = match.group(1)
                    account_found = True
                    logging.debug(f"Unlabeled: Found potential last 4 digits {account_last4}")
        
        if account_number: 
            statement_info.account_number = account_number
        elif account_last4: 
            statement_info.account_number = f"xxxx{account_last4}"
        
        date_patterns = [
            re.compile(r'Statement Date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', re.I), 
            re.compile(r'Statement Date[:\s]*(\w+\s+\d{1,2},\s+\d{4})', re.I),
            re.compile(r'Statement Period.*?to\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', re.I), 
            re.compile(r'Statement Period.*?-\s+(\w+\s+\d{1,2},\s+\d{4})', re.I),
            re.compile(r'Ending\s+(\d{1,2}/\d{1,2}/\d{2,4})', re.I), 
            re.compile(r'As of\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', re.I),
            re.compile(r'Date\s+(\d{1,2}/\d{1,2}/\d{4})\b', re.I), 
            re.compile(r'\b(\d{1,2}/\d{1,2}/\d{4})\b') # Generic date anywhere
        ]
        date_formats = ['%m/%d/%Y', '%m/%d/%y', '%B %d, %Y', '%b %d, %Y', '%Y-%m-%d']
        statement_date = None; date_found = False
        
        for line in lines:
            if date_found: break
            for pattern in date_patterns:
                match = pattern.search(line)
                if match:
                    parsed_date = self._parse_date(match.group(1), date_formats)
                    if parsed_date and 2000 <= parsed_date.year <= datetime.now().year + 1:
                         statement_info.date = parsed_date
                         date_found = True
                         logging.debug(f"Unlabeled: Found potential date {statement_info.date:%Y-%m-%d}"); break
        
        if not statement_info.date: 
            logging.warning(f"Unlabeled: No date found. Using current date as fallback.")
            statement_info.date = datetime.now() # Fallback date
            statement_info.match_status = "Unlabeled (Generic - No Date)" # More specific status

        if not statement_info.account_name:
            if statement_info.account_number: 
                last4_display = statement_info.account_number[-4:] if len(statement_info.account_number) >= 4 else "XXXX"
                statement_info.account_name = f"UNLABELED ACCOUNT {last4_display}"
            else: 
                statement_info.account_name = "UNKNOWN UNLABELED ACCOUNT"
                # If no account number was found either, the status is worse
                if not date_found: # No date AND no account number
                    statement_info.match_status = "Unlabeled (Needs Review - No Info)"
                else: # Has date, but no account number
                    statement_info.match_status = "Unlabeled (Needs Review - No Account)"
            logging.info(f"Unlabeled: Setting default name: {statement_info.account_name}")
        
        logging.info(f"Unlabeled: Final status for '{statement_info.original_filename}': {statement_info.match_status}")

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
