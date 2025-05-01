import os
import PyPDF2
import re
import logging
import argparse
import shutil
import json
import hashlib
import csv
from pathlib import Path
from typing import Tuple, Optional, Dict, List, Set
from datetime import datetime, timedelta
import calendar

# Add more imports for improved functionality
import concurrent.futures
import time
import sys
from collections import defaultdict


class ConfigManager:
    """Manages configuration settings for the application."""
    
    DEFAULT_CONFIG = {
        "input_folder": r"C:\Users\Christian\OneDrive - Arctaris Michigan Partners, LLC\Desktop\Bank Automation\input_statements",
        "processed_folder": r"C:\Users\Christian\OneDrive - Arctaris Michigan Partners, LLC\Desktop\Bank Automation\processed_statements",
        "log_level": "INFO",
        "backup_files": True,
        "max_workers": 4,  # For parallel processing
        "batch_size": 20,   # Files per batch
        "file_verification": True,  # Verify PDFs before processing
        "auto_recovery": True,  # Try to recover from errors
        "patterns": {
            "period_marker": "FOR THE PERIOD",
            "stop_markers": ["STE"],
            "skip_starters": [
                "Number", "Tax ID", "For Client",
                "Visit", "For 24-hour", "PNC Bank"
            ]
        }
    }
    
    def __init__(self, config_path: str = "config.json"):
        """Initialize with path to config file."""
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self) -> Dict:
        """Load configuration from file or create with defaults."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                    # Merge with defaults for any missing keys
                    merged_config = self._deep_merge(self.DEFAULT_CONFIG.copy(), config)
                    return merged_config
            else:
                # Create default config file
                with open(self.config_path, 'w') as f:
                    json.dump(self.DEFAULT_CONFIG, f, indent=4, sort_keys=True)
                return self.DEFAULT_CONFIG.copy()
        except Exception as e:
            logging.error(f"Error loading config: {e}. Using defaults.")
            return self.DEFAULT_CONFIG.copy()
    
    def _deep_merge(self, source, destination):
        """Deep merge two dictionaries."""
        for key, value in destination.items():
            if isinstance(value, dict):
                # get node or create one
                node = source.setdefault(key, {})
                if isinstance(node, dict):
                    self._deep_merge(node, value)
                else:
                    source[key] = value
            else:
                source[key] = value
        return source
    
    def save_config(self):
        """Save current configuration to file."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4, sort_keys=True)
        except Exception as e:
            logging.error(f"Error saving config: {e}")
    
    def get(self, key, default=None):
        """Get a configuration value."""
        keys = key.split('.')
        result = self.config
        try:
            for k in keys:
                result = result[k]
            return result
        except (KeyError, TypeError):
            return default


class StatementInfo:
    """Class to hold extracted statement information."""
    def __init__(self):
        self.bank_type = ""
        self.account_name = ""
        self.account_number = ""
        self.date = None
        self.original_filename = ""
        # Add fund_name attribute for PNC files
        self.fund_name = "" 
        
    def is_complete(self) -> bool:
        """Check if essential statement information is present."""
        # Define what constitutes "complete" - adjust as needed
        return bool(
            self.bank_type and 
            self.account_name and 
            self.account_number and 
            self.date
        )
        
    def get_formatted_filename(self, original_filename: str) -> str:
        """Generate a formatted filename with the extracted information."""
        # Start with the bank type prefix
        if self.bank_type == "PNC":
            # For PNC files, keep original filename but add fund name at the beginning
            if self.fund_name:
                # Clean up fund name for filename
                clean_fund = self.fund_name.replace(' ', '-')
                # Remove illegal filename characters
                clean_fund = re.sub(r'[<>:"/\\|?*]', '', clean_fund)
                # Return the fund name followed by original filename
                return f"{clean_fund}_{original_filename}"
            else:
                prefix = "PNC"
        elif self.bank_type == "Berkshire":
            prefix = "Berkshire"
            
        # For other banks, use the standard naming convention
        components = []
        if self.bank_type:
            components.append(self.bank_type)
        if self.account_name:
            safe_account_name = re.sub(r'[<>:"/\\|?*]', '', self.account_name)
            components.append(safe_account_name)
        if self.date:
            components.append(self.date.strftime("%Y%m%d"))
            
        return "_".join(components) + ".pdf"


class PDFProcessor:
    """Processes PDF files to extract account information."""
    
    def __init__(self, config: ConfigManager):
        """Initialize with configuration."""
        self.config = config
        # Add default attributes to prevent errors
        self.bank_detector = None  # Will use direct string matching instead
        self.extraction_stats = defaultdict(int)
    
    def process_pdf(self, file_path: str) -> Tuple[Optional[str], Optional[StatementInfo]]:
        """
        Process a PDF file to extract statement information with enhanced extraction.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Tuple of (extracted text, statement info)
        """
        if not os.path.exists(file_path):
            logging.error(f"File not found: {file_path}")
            return None, None
            
        try:
            # Store filename for reference
            filename = os.path.basename(file_path)
            self.current_filename = filename
            
            # Special handling for Online Statements files - identify as Cambridge Savings
            if "Online Statements_" in filename:
                logging.info(f"Processing Online Statements file as Cambridge: {filename}")
                statement_info = StatementInfo()
                statement_info.bank_type = "Cambridge"
                
                # Extract date from filename (format: Online Statements_YYYY-MM-DD)
                date_match = re.search(r'Online Statements_(\d{4}-\d{2}-\d{2})', filename)
                if date_match:
                    date_str = date_match.group(1)
                    try:
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                        statement_info.date = date_obj
                    except:
                        # Use current date as fallback
                        today = datetime.now()
                        statement_info.date = today
                else:
                    # Use current date if no date in filename
                    today = datetime.now()
                    statement_info.date = today
                
                # Extract number from filename if present for unique fund names
                num_match = re.search(r'\((\d+)\)', filename)
                if num_match:
                    account_id = num_match.group(1)
                    account_num = account_id.zfill(4)
                    
                    # Map to real account names using the Cambridge account mappings
                    # Example mappings from known accounts
                    cambridge_mappings = {
                        # Special case for numbered files - we'll map these to the accounts in order
                        '0001': '3346',  # ARCTARIS IMPACT INVESTORS, LLC
                        '0002': '3354',  # ARCTARIS IMPACT FUND, LP  
                        '0003': '3362',  # ARCTARIS IMPACT FUND, LP
                        '0004': '3396',  # ARCTARIS OPPORTUNITY ZONE 2022, LLC
                        '0005': '3403',  # ARCTARIS OPPORTUNITY ZONE 2022, LLC
                        '0006': '3445',  # OHIO INCLUSIVE HOUSING, LLC
                        '0007': '3453',  # OHIO INCLUSIVE HOUSING, LLC
                        '0008': '3479',  # MIDWEST COMMERCIAL DEVELOPMENT, LLC
                        '0009': '3487',  # WEST COAST COMMERCIAL DEVELOPMENT LLC
                        '0010': '3495',  # WEST COAST COMMERCIAL DEVELOPMENT LLC
                        '0011': '3502',  # EAST COAST INDUSTRIAL, LLC
                        '0012': '3510',  # EAST COAST INDUSTRIAL, LLC
                        '0013': '3528',  # ARCTARIS OPPORTUNITY ZONE FUND 2024,LLC
                        '0014': '3536',  # ARCTARIS OPPORTUNITY ZONE FUND 2024,LLC
                    }
                    
                    # Get the known account number for this file index
                    account_lookup = cambridge_mappings.get(account_num, None)
                    
                    if account_lookup:
                        # Use the mapping defined in _extract_cambridge_savings_info
                        cambridge_account_mappings = {
                            '3346': 'ARCTARIS IMPACT INVESTORS, LLC',
                            '3354': 'ARCTARIS IMPACT FUND, LP',
                            '3362': 'ARCTARIS IMPACT FUND, LP',
                            '3396': 'ARCTARIS OPPORTUNITY ZONE 2022, LLC',
                            '3403': 'ARCTARIS OPPORTUNITY ZONE 2022, LLC',
                            '3445': 'OHIO INCLUSIVE HOUSING, LLC',
                            '3453': 'OHIO INCLUSIVE HOUSING, LLC',
                            '3479': 'MIDWEST COMMERCIAL DEVELOPMENT, LLC',
                            '3487': 'WEST COAST COMMERCIAL DEVELOPMENT LLC',
                            '3495': 'WEST COAST COMMERCIAL DEVELOPMENT LLC',
                            '3502': 'EAST COAST INDUSTRIAL, LLC',
                            '3510': 'EAST COAST INDUSTRIAL, LLC',
                            '3528': 'ARCTARIS OPPORTUNITY ZONE FUND 2024,LLC',
                            '3536': 'ARCTARIS OPPORTUNITY ZONE FUND 2024,LLC'
                        }
                        # Set account number to the actual Cambridge account number
                        statement_info.account_number = account_lookup
                        
                        # And set the account name to the matching name
                        if account_lookup in cambridge_account_mappings:
                            statement_info.account_name = cambridge_account_mappings[account_lookup]
                        else:
                            statement_info.account_name = f"ARCTARIS ACCOUNT {account_lookup}"
                    else:
                        # If no specific mapping, use generic name
                        statement_info.account_number = account_num
                        statement_info.account_name = f"ARCTARIS ACCOUNT {account_num}"
                else:
                    # Default account info if no number in filename
                    statement_info.account_number = "3346"
                    statement_info.account_name = "ARCTARIS IMPACT INVESTORS, LLC"
                    
                    # Check the filename for month information to ensure we're organizing correctly
                    month_match = re.search(r'(\d{4}-\d{2})-\d{2}', filename)
                    if month_match:
                        year_month = month_match.group(1)
                        try:
                            # Parse the date more accurately from the filename
                            date_obj = datetime.strptime(year_month, '%Y-%m')
                            statement_info.date = datetime(date_obj.year, date_obj.month, 28)  # Use end of month
                        except:
                            # Current date is already set as fallback above
                            pass
                
                return "", statement_info
            
            # Special handling for dxweb files - always BankUnited
            if "dxweb" in filename.lower():
                logging.info(f"Processing dxweb file as BankUnited: {filename}")
                statement_info = StatementInfo()
                statement_info.bank_type = "BankUnited"
                
                # Extract the account ID from the filename
                number_match = re.search(r'dxweb\s*\((\d+)\)', filename, re.IGNORECASE)
                if number_match:
                    number = number_match.group(1)
                    # Map the dxweb number to actual account names similar to what's shown in the screenshot
                    dxweb_mappings = {
                        # Map based on the account names and numbers from screenshots
                        '8': 'ARC IMPACT-PROGRAM ERIE LLC - 0579',
                        '9': 'ARC IMPACT-PROGRAM ERIE LLC OPERATING - 0560',
                        '10': 'ARC IMPACT-PROGRAM SWPA LLC - 0749',
                        '11': 'ARC IMPACT-PROGRAM SWPA LLC OPERATING - 0706',
                        '12': 'ARCTARIS EASTERN DEVELOPMENT HOUSING LLC FUND OPERATING - 7400',
                        '13': 'ARCTARIS EASTERN DEVELOP SAVINGS - 7427',
                        '14': 'ARCTARIS IMPACT INVESTORS LLC COLLATERAL - 8190',
                        '15': 'ARCTARIS IMPACT INVESTORS LLC MMGNT - 8174',
                        '16': 'ARCTARIS IMPACT INVESTORS LLC OPER - 3008',
                        '17': 'ARCTARIS OPPORTUNITY ZONE FUND 2019 COLL - 8298',
                        '18': 'ARCTARIS OPPORTUNITY ZONE FUND 2019 MM - 8239',
                        '19': 'ARCTARIS OPPORTUNITY ZONE FUND 2019 OPER - 8220',
                        '20': 'ARCTARIS OPPORTUNITY ZONE FUND 2020 COLL - 8441',
                        '21': 'ARCTARIS OPPORTUNITY ZONE FUND 2020 LLC - 8425',
                        '22': 'ARCTARIS OPPORTUNITY ZONE FUND 2020 OPER - 8387',
                        '23': 'ARCTARIS OPPORTUNITY ZONE FUND 2022 COLL - 8530',
                        '24': 'ARCTARIS OPPORTUNITY ZONE FUND 2022 MGMT - 8514',
                        '25': 'ARCTARIS OPPORTUNITY ZONE FUND 2022 OPER - 8484',
                        '26': 'ARCTARIS PRODUCT DEVELOP OPERATING - 5785',
                        '27': 'ARCTARIS PRODUCT DEVELOP SAVINGS - 5793',
                        '28': 'ARCTARIS SOUTH EAST DEVELOPMENT LLC - 6075',
                        '29': 'ARCTARIS SOUTH EAST DEVELOPMENT LLC OPER - 6067',
                        '30': 'EAST COAST COMMERCIAL DEV OPERATING - 6640',
                        '31': 'EAST COAST COMMERCIAL DEV SAVINGS - 4120',
                        '32': 'MID ATLANTIC INCLUSIVE HOUSING LLC - 6059',
                        '33': 'MID ATLANTIC INCLUSIVE HOUSING LLC OPER - 5990',
                        '34': 'ARCTARIS IMPACT FUND LP - 7076',
                        '35': 'ARCTARIS OPPORTUNITY ZONE FUND 2019 LLC - 1396',
                    }
                    
                    # Get the account name from the mapping or use a default format
                    statement_info.account_name = dxweb_mappings.get(number, f"Account-{number}")
                else:
                    # If no number is found, use a generic name
                    statement_info.account_name = "Account"

            # For display in filename, use full month name
            month_name = statement_info.date.strftime('%B') if statement_info.date else datetime.now().strftime('%B')

            # Create the new filename with the exact format requested
            new_filename = f"Bank United {statement_info.account_name} {month_name} {year} Statement.pdf"
            
        elif statement_info.bank_type == "Cambridge":
            # Format as "[account name] [account number] [Month] [year].pdf"
            # Extract month and year from date
            if statement_info.date:
                month = statement_info.date.strftime('%B')  # Full month name
                year = statement_info.date.strftime('%Y')
            else:
                # Use current date if statement date not available
                current_date = datetime.now()
                month = current_date.strftime('%B')
                year = current_date.strftime('%Y')
                
            # Get account name if available
            account_name = "Arctaris Fund"  # Default account name
            if hasattr(statement_info, 'account_name') and statement_info.account_name:
                account_name = statement_info.account_name
            elif "Online Statements" in filename:
                # Extract number from filename if available (Online Statements_2025-02-28 (10).pdf)
                match = re.search(r'\((\d+)\)', filename)
                if match:
                    pass # Name already set from process_pdf based on mapping
                    # account_name = f"Arctaris Fund {match.group(1)}" # REMOVE THIS LINE
                # If this is the main statement without a number
                else:
                    pass # Name already set from process_pdf default
                    # account_name = "ARCTARIS IMPACT INVESTORS, LLC" # REMOVE THIS LINE
            
            # Get account number
            acct_number = "0000" # Default account number (Line 1372)
            if hasattr(statement_info, 'account_number') and statement_info.account_number:
                acct_number = statement_info.account_number # Use extracted number
            else:
                # Try to extract from filename if possible
                match = re.search(r'\((\d+)\)', filename)
                if match:
                    acct_number = match.group(1).zfill(4) # Use number from filename (Line 1378)
                # If no match, use the default account number for main statement
                else:
                    pass # Number already set from process_pdf default
                    # acct_number = "3346"  # REMOVE THIS LINE

            # Create the new filename
            new_filename = f"{account_name} {acct_number} Cambridge Savings {month} {year}.pdf"
            
            # Sanitize the filename
            new_filename = self._sanitize_filename(new_filename)
            
        elif statement_info.bank_type == "Berkshire":
            # For Berkshire files, use a consistent naming convention
            if statement_info.date:
                date_str = statement_info.date.strftime('%Y%m%d')
            else:
                date_str = datetime.now().strftime('%Y%m%d')

            # Use last 4 digits of account if available
            acct_last4 = "0000"
            if hasattr(statement_info, 'account_number') and statement_info.account_number:
                acct_last4 = statement_info.account_number[-4:] if len(statement_info.account_number) >= 4 else statement_info.account_number

            # Default fund name if not available
            fund_name = "ARCTARIS OPPORTUNITY ZONE FUND 2019 LLC"
            if hasattr(statement_info, 'account_name') and statement_info.account_name:
                fund_name = statement_info.account_name.upper()
            
            # Create filename in the format "[last 4 account number]-[account name]-[statement date].pdf" as shown in the screenshot
            new_filename = f"{acct_last4}-{fund_name}-{date_str}.pdf"
            
            # Sanitize the filename
            new_filename = self._sanitize_filename(new_filename)
        else:
            # For other banks, use the standard formatting
            new_filename = statement_info.get_formatted_filename(filename)

        # Create subfolder path based on bank type and date
        subfolder_path = self._create_subfolder_path(output_path, statement_info)
        if not subfolder_path:
            return False, f"Failed to create subfolder path for {filename}"

        # Create the full destination path
        full_output_path = os.path.join(output_path, subfolder_path)
        dest_file_path = os.path.join(full_output_path, new_filename)
        
        # Check if destination file already exists
        if os.path.exists(dest_file_path):
            # Look for existing sequence number in filename
            base_name, ext = os.path.splitext(new_filename)
            seq = 1
            
            # Extract existing sequence number if present
            seq_match = re.search(r'_(\d+)$', base_name)
            if seq_match:
                try:
                    seq = int(seq_match.group(1)) + 1
                    base_name = re.sub(r'_\d+$', '', base_name)
                except:
                    seq = 1
            
            # Try increasing sequence numbers until we find an available filename
            while os.path.exists(dest_file_path):
                new_filename = f"{base_name}_{seq}{ext}"
                dest_file_path = os.path.join(full_output_path, new_filename)
                seq += 1
                
                # Safety check to avoid infinite loops
                if seq > 100:
                    return False, f"Failed to find available filename for {filename}"
                
        # For dry run, just return the information
        if dry_run:
            # Track file for checklist
            self.processed_files.append({
                'original_file': filepath,
                'destination_file': os.path.join(subfolder_path, new_filename),
                'bank_type': statement_info.bank_type if statement_info and statement_info.bank_type else "Unknown",
                'status': 'Would process'
            })
            return True, f"Would rename to: {os.path.join(subfolder_path, new_filename)}"
        
        # Create destination folder if it doesn't exist
        if not os.path.exists(full_output_path):
            os.makedirs(full_output_path)
            self._created_folders.add(full_output_path)
        
        # Copy the file
        shutil.copy2(filepath, dest_file_path)
        
        # Track file for checklist
        self.processed_files.append({
            'original_file': filepath,
            'destination_file': os.path.join(subfolder_path, new_filename),
            'bank_type': statement_info.bank_type if statement_info and statement_info.bank_type else "Unknown",
            'status': 'Processed'
        })
        
        # If configured to delete originals, do so
        if self.config.get("delete_originals", False):
            os.remove(filepath)
            return True, f"Processed {filename} -> {new_filename} (deleted original)"
        else:
            return True, f"Processed {filename} -> {new_filename}"
            
    def generate_checklist(self, output_path: str = "checklists", dry_run: bool = False) -> str:
        """
        Generate a CSV checklist of processed files.
        
        Args:
            output_path: Path to save the checklist
            dry_run: Whether this is a dry run
            
        Returns:
            Path to the generated CSV file
        """
        # Create directory if it doesn't exist
        os.makedirs(output_path, exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        prefix = "preview_" if dry_run else ""
        csv_filename = f"{prefix}checklist_{timestamp}.csv"
        csv_path = os.path.join(output_path, csv_filename)
        
        # --- Checklist Sorting Logic ---
        def get_sort_key(file_info):
            # Extract year, month, and name for sorting
            year, month = 9999, 99  # Default for files without date (sort last)
            name = file_info.get('bank_type', 'ZZZ') or 'ZZZ' # Default for missing name
            original_name = os.path.basename(file_info.get('original_file', ''))
            
            # Use destination file name if bank type is missing but processing succeeded
            if name == 'ZZZ' and file_info.get('status') == 'Success':
                 name = file_info.get('destination_file', 'ZZZ')
            elif name == 'ZZZ':
                 name = original_name # Fallback to original filename if needed

            if file_info.get('date'):
                try:
                    year = file_info['date'].year
                    month = file_info['date'].month
                except AttributeError:
                    # Handle case where date might not be a datetime object
                    pass 
                    
            return (year, month, name.lower(), original_name.lower())

        # Sort the processed_files data using the custom key
        sorted_files = sorted(self.processed_files, key=get_sort_key)
        # --- End Sorting Logic ---

        # Define headers based on run type
        if dry_run:
            fieldnames = ['Original File', 'Proposed Destination', 'Bank Type', 'Status']
        else:
            fieldnames = ['Original File', 'Destination File', 'Bank Type', 'Status', 'Processed', 'Verified']

        # Corrected structure for writing CSV file with error handling
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                # Write sorted data
                for file_info in sorted_files:
                    row_data = {
                        'Original File': os.path.basename(file_info.get('original_file', 'N/A')),
                        'Bank Type': file_info.get('bank_type', 'Unknown'),
                        'Status': file_info.get('status', 'Unknown')
                    }

                    if dry_run:
                        row_data['Proposed Destination'] = file_info.get('destination_file', 'N/A')
                    else:
                        row_data['Destination File'] = file_info.get('destination_file', 'N/A')
                        # Mark 'Processed' if status is Success
                        row_data['Processed'] = 'X' if file_info.get('status') == 'Success' else ''
                        row_data['Verified'] = '' # Always blank initially

                    writer.writerow(row_data)
            
            # Log success AFTER the file is closed by the 'with' block
            logging.info(f"Successfully wrote {len(sorted_files)} rows to checklist: {csv_path}")
            return csv_path

        except IOError as e:
            # Correctly indented except block
            logging.error(f"Failed to write checklist file '{csv_path}': {e}")
            return None
        except Exception as e:
            # Correctly indented except block
            logging.error(f"An unexpected error occurred while writing checklist '{csv_path}': {e}")
            return None

    def _create_subfolder_path(self, base_path: str, statement_info: StatementInfo) -> str:
        """
        Create the subfolder path based on bank type and date.
        
        Args:
            base_path: Base output path
            statement_info: Statement information
            
        Returns:
            Subfolder path relative to base path
        """
        subfolder_components = []
        
        # Add bank type first
        if statement_info.bank_type:
            subfolder_components.append(statement_info.bank_type)
        else:
            subfolder_components.append("Unlabeled")
        
        # For BankUnited, use year-month format
        if statement_info.bank_type == "BankUnited":
            # Get year and month in numeric format
            if statement_info.date:
                year = statement_info.date.strftime('%Y')
                month = statement_info.date.strftime('%m')
            else:
                # Use current date
                current_date = datetime.now()
                year = current_date.strftime('%Y')
                month = current_date.strftime('%m')
            
            # Use year-month format in the subfolder path
            subfolder_components.append(f"{year}-{month}")
        else:
            # For other banks, use year-month format as before
            if statement_info.date:
                year_month = statement_info.date.strftime('%Y-%m')
                subfolder_components.append(year_month)
            else:
                # Use current date if no date
                current_date = datetime.now()
                year_month = current_date.strftime('%Y-%m')
                subfolder_components.append(year_month)
        
        # Create the subfolder path
        subfolder_path = os.path.join(*subfolder_components)
        
        # Ensure the folder exists
        full_path = os.path.join(base_path, subfolder_path)
        self.ensure_folder_exists(full_path)
        
        return subfolder_path

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize a filename to be safe for use in file systems."""
        # Replace illegal characters with underscores
        sanitized_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Remove leading and trailing underscores
        sanitized_filename = sanitized_filename.strip('_')
        return sanitized_filename


class PDFVerifier:
    """Verifies and validates PDF files before processing."""
    
    def __init__(self):
        """Initialize the PDF verifier."""
        self.verified_files = set()
        self.corrupt_files = set()
    
    def verify_pdf(self, file_path: str) -> Tuple[bool, str]:
        """
        Verify a PDF file is valid and readable.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Tuple of (is_valid, message)
        """
        # Skip if already verified
        if file_path in self.verified_files:
            return True, "Already verified"
            
        # Skip if known to be corrupt
        if file_path in self.corrupt_files:
            return False, "Known corrupt file"
            
        if not os.path.exists(file_path):
            return False, "File does not exist"
            
        if not os.path.isfile(file_path):
            return False, "Not a file"
            
        # Check file size (empty or suspiciously large files)
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            self.corrupt_files.add(file_path)
            return False, "Empty file"
            
        if file_size > 100 * 1024 * 1024:  # > 100MB
            return False, "File too large (>100MB)"
            
        # Try to open and read the PDF
        try:
            with open(file_path, 'rb') as f:
                # Check if it starts with PDF signature
                signature = f.read(5)
                if signature != b'%PDF-':
                    self.corrupt_files.add(file_path)
                    return False, "Not a valid PDF (missing signature)"
            
            # For PNC and dxweb files, skip text extraction check - these are usually valid
            filename = os.path.basename(file_path).lower()
            if (filename.startswith("statement_") or "dxweb" in filename) and filename.endswith(".pdf"):
                self.verified_files.add(file_path)
                return True, "PDF verified (special handling for known file types)"
                
            # Try to read with PyPDF2
            with open(file_path, 'rb') as f:
                try:
                    pdf = PyPDF2.PdfReader(f)
                    if len(pdf.pages) == 0:
                        self.corrupt_files.add(file_path)
                        return False, "PDF has no pages"
                        
                except Exception as e:
                    self.corrupt_files.add(file_path)
                    return False, f"Error reading PDF: {str(e)}"
                
            # All checks passed
            self.verified_files.add(file_path)
            return True, "PDF verified"
            
        except Exception as e:
            self.corrupt_files.add(file_path)
            return False, f"Error verifying PDF: {str(e)}"
    
    def get_file_hash(self, file_path: str) -> Optional[str]:
        """
        Calculate MD5 hash of file to detect duplicates.
        
        Args:
            file_path: Path to the file
            
        Returns:
            MD5 hash string or None if file can't be read
        """
        if not os.path.exists(file_path):
            logging.warning(f"File does not exist: {file_path}")
            return None
            
        try:
            with open(file_path, 'rb') as f:
                file_hash = hashlib.md5()
                try:
                    chunk = f.read(8192)
                    while chunk:
                        file_hash.update(chunk)
                        chunk = f.read(8192)
                    return file_hash.hexdigest()
                except Exception as e:
                    logging.warning(f"Error reading file during hashing: {file_path}, {str(e)}")
                    return None
        except Exception as e:
            logging.warning(f"Error opening file for hashing: {file_path}, {str(e)}")
            return None
    
    def find_duplicate_files(self, file_paths: List[str]) -> Dict[str, List[str]]:
        """
        Find duplicate files based on hash.
        
        Args:
            file_paths: List of file paths to check
            
        Returns:
            Dictionary of hash -> list of file paths
        """
        # Hash all files
        file_hashes = {}
        
        # Calculate hash for each file
        for file_path in file_paths:
            if not os.path.exists(file_path):
                logging.warning(f"File not found when checking for duplicates: {file_path}")
                continue
            
            try:
                # Get file hash
                file_hash = self.get_file_hash(file_path)
                if file_hash is None:
                    continue
                
                # Add to hash dict
                if file_hash not in file_hashes:
                    file_hashes[file_hash] = []
                    
                file_hashes[file_hash].append(file_path)
            except Exception as e:
                logging.warning(f"Error hashing file {file_path}: {str(e)}")
            
        # Find duplicates (hash with multiple files)
        duplicates = {}
        for file_hash, paths in file_hashes.items():
            if len(paths) > 1:
                duplicates[file_hash] = paths
                # Provide better logging for each duplicate group
                original = os.path.basename(paths[0])
                dups = [os.path.basename(p) for p in paths[1:]]
                logging.info(f"Duplicate group - Original: {original}, Duplicates: {', '.join(dups)}")
            
        return duplicates


class BankDetector:
    """Detects bank types with learning capabilities."""
    
    def __init__(self, config: ConfigManager):
        """Initialize with configuration."""
        self.config = config
        self.known_banks = {
            "PNC Bank": [
                "PNC BANK", 
                "PNCBANK",
                "PNC.COM"
            ],
            "Berkshire Bank": [
                "BERKSHIRE BANK",
                "BERKSHIREBANK"
            ],
            "Bank United": [
                "BANKUNITED",
                "BANK UNITED"
            ],
            "Cambridge Savings": [
                "CAMBRIDGE SAVINGS",
                "CAMBRIDGESAVINGS"
            ]
        }
        self.learned_patterns = self._load_learned_patterns()
        
    def _load_learned_patterns(self) -> Dict[str, List[str]]:
        """Load learned patterns from config or file."""
        learned_file = "bank_patterns.json"
        if os.path.exists(learned_file):
            try:
                with open(learned_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Error loading learned patterns: {e}")
        return {}
        
    def save_learned_patterns(self):
        """Save learned patterns to file."""
        try:
            with open("bank_patterns.json", 'w') as f:
                json.dump(self.learned_patterns, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving learned patterns: {e}")
            
    def detect_bank(self, text: str) -> str:
        """
        Detect the bank from statement text.
        
        Args:
            text: The statement text
            
        Returns:
            Bank type name or "Unknown"
        """
        if not text:
            return "Unknown"
            
        # Normalize text for matching
        normalized_text = text.upper().replace(" ", "")
        
        # Check known banks
        for bank_name, patterns in self.known_banks.items():
            for pattern in patterns:
                if pattern.replace(" ", "") in normalized_text:
                    return bank_name
                    
        # Check learned patterns
        for bank_name, patterns in self.learned_patterns.items():
            for pattern in patterns:
                if pattern.replace(" ", "") in normalized_text:
                    return bank_name
                    
        return "Unknown"
        
    def learn_pattern(self, bank_name: str, pattern: str):
        """
        Learn a new pattern for a bank.
        
        Args:
            bank_name: Name of the bank
            pattern: New pattern to learn
        """
        if bank_name not in self.learned_patterns:
            self.learned_patterns[bank_name] = []
            
        pattern = pattern.upper()
        if pattern not in self.learned_patterns[bank_name]:
            self.learned_patterns[bank_name].append(pattern)
            self.save_learned_patterns()
            logging.info(f"Learned new pattern for {bank_name}: {pattern}")
            
    def suggest_bank_from_features(self, text: str) -> Optional[str]:
        """
        Suggest bank type based on common features when detection fails.
        
        Args:
            text: The statement text
            
        Returns:
            Suggested bank name or None
        """
        features = {
            "PNC Bank": [
                r"Account\s+Number:\s+\d+-\d+-\d+",
                r"For\s+the\s+period",
                r"PNC\s+Treasury\s+Management"
            ],
            "Berkshire Bank": [
                r"Statement\s+of\s+Account",
                r"Last\s+statement",
                r"This\s+statement"
            ],
            "Bank United": [
                r"Customer\s+Service\s+Information",
                r"Statement\s+Date",
                r"Web\s+Site:\s+www\.bankunited\.com"
            ],
            "Cambridge Savings": [
                r"Statement\s+Period",
                r"Page\s+\d+\s+of\s+\d+",
                r"Enclosures"
            ]
        }
        
        # Count matching features for each bank
        scores = {}
        for bank, feature_list in features.items():
            score = 0
            for feature in feature_list:
                if re.search(feature, text, re.IGNORECASE):
                    score += 1
            if score > 0:
                scores[bank] = score
                
        # Return bank with highest score
        if scores:
            return max(scores, key=scores.get)
        return None


class ErrorRecovery:
    """Handles error recovery and repair operations."""
    
    def __init__(self, config: ConfigManager):
        """Initialize with configuration."""
        self.config = config
        self.error_counts = defaultdict(int)
        self.recovery_attempts = defaultdict(int)
        self.max_recovery_attempts = 1
        
    def can_attempt_recovery(self, file_path: str) -> bool:
        """Check if recovery can be attempted for a file."""
        if not self.config.get("auto_recovery", True):
            return False
            
        attempts = self.recovery_attempts[file_path]
        return attempts < self.max_recovery_attempts
        
    def record_recovery_attempt(self, file_path: str):
        """Record a recovery attempt for a file."""
        self.recovery_attempts[file_path] += 1
        
    def attempt_pdf_repair(self, file_path: str) -> Tuple[bool, str]:
        """
        Attempt to repair a corrupted PDF file.
        
        Args:
            file_path: Path to the corrupted PDF
            
        Returns:
            Tuple of (success, repaired_path or error message)
        """
        self.record_recovery_attempt(file_path)
        
        try:
            # Create a temporary repair file
            repaired_path = f"{file_path}.repaired.pdf"
            
            # Try a simple repair by re-writing with PyPDF2
            with open(file_path, 'rb') as input_file:
                try:
                    pdf = PyPDF2.PdfReader(input_file)
                    writer = PyPDF2.PdfWriter()
                    
                    # Copy each page that can be read
                    for i in range(len(pdf.pages)):
                        try:
                            page = pdf.pages[i]
                            writer.add_page(page)
                        except:
                            continue
                    
                    # Save the repaired file
                    with open(repaired_path, 'wb') as output_file:
                        writer.write(output_file)
                        
                    return True, repaired_path
                    
                except Exception as e:
                    logging.error(f"PDF repair failed: {str(e)}")
                    return False, f"Repair failed: {str(e)}"
        
        except Exception as e:
            logging.error(f"Error during PDF repair: {str(e)}")
            return False, f"Error: {str(e)}"
            
    def get_summary(self) -> Dict[str, int]:
        """Get summary of errors and recovery attempts."""
        return {
            "total_errors": sum(self.error_counts.values()),
            "recovery_attempts": sum(self.recovery_attempts.values()),
            "error_types": dict(self.error_counts)
        }
        
    def record_error(self, error_type: str):
        """Record an error by type."""
        self.error_counts[error_type] += 1


def setup_logging(log_level: str = "INFO", log_file: str = None):
    """Set up logging configuration with rotation and proper formatting."""
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
        
    # Create logs directory if it doesn't exist
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
    else:
        # Default log file with timestamp
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"pdf_processor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    
    # Setup root logger with a more detailed format
    log_format = "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # Clear any existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers = []
    
    # Configure logging
    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file)
        ]
    )
    
    # Also print start message
    logging.info(f"Logging initialized at level {log_level}")
    logging.info(f"Log file: {os.path.abspath(log_file)}")
    
    return log_file


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Process bank statement PDFs")
    
    parser.add_argument("--input", type=str, help="Input folder path")
    parser.add_argument("--output", type=str, help="Output folder path")
    parser.add_argument("--dry-run", action="store_true", 
                        help="Preview changes without executing")
    parser.add_argument("--show-preview", action="store_true",
                       help="Show detailed preview of changes by bank")
    parser.add_argument("--log-level", type=str, 
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       default="INFO", help="Set logging level")
    parser.add_argument("--config", type=str, default="config.json",
                       help="Path to configuration file")
    parser.add_argument("--log-file", type=str, 
                       help="Path to log file (defaults to logs/pdf_processor_TIMESTAMP.log)")
    parser.add_argument("--process-duplicates", action="store_true",
                       help="Process duplicate files instead of skipping them")
    parser.add_argument("--checklist-dir", type=str, default="checklists",
                       help="Directory to save checklist CSV files")
    parser.add_argument("--auto-confirm", action="store_true",
                       help="Skip the confirmation prompt and automatically process files")
    
    return parser.parse_args()


def main():
    """Main function to process PDF files."""
    start_time = time.time()
    
    # Parse command line arguments
    args = parse_arguments()
    
    # Load configuration
    config_manager = ConfigManager(args.config)
    
    # Set up logging
    log_level = args.log_level or config_manager.get("log_level", "INFO")
    log_file = setup_logging(log_level, args.log_file)
    
    # Initialize components
    bank_detector = BankDetector(config_manager)
    pdf_verifier = PDFVerifier()
    error_recovery = ErrorRecovery(config_manager)
    
    # Get folder paths (CLI args override config)
    input_folder = args.input or config_manager.get("input_folder")
    processed_folder = args.output or config_manager.get("processed_folder")
    
    # Validate paths
    if not input_folder or not os.path.isdir(input_folder):
        logging.error(f"Invalid input folder: {input_folder}")
        return 1
        
    # Create processors
    pdf_processor = PDFProcessor(config_manager)
    file_manager = FileManager(config_manager)
    
    # Log startup information
    logging.info(f"Starting PDF rename script (version 2.0)")
    logging.info(f"Input folder: {input_folder}")
    logging.info(f"Output folder: {processed_folder}")
    
    # Get list of PDF files
    try:
        all_files = os.listdir(input_folder)
        pdf_files = [f for f in all_files if f.lower().endswith('.pdf')]
        
        # Filter out repaired files
        original_files = []
        repaired_files = []
        for f in pdf_files:
            if f.lower().endswith('.repaired.pdf'):
                repaired_files.append(f)
            else:
                original_files.append(f)
                
        # Log the count of repaired files that will be skipped
        if repaired_files:
            logging.info(f"Found {len(repaired_files)} repaired files that will be skipped")
        
        # Use only original files
        pdf_files = original_files
        
    except Exception as e:
        logging.error(f"Error reading input directory: {str(e)}")
        return 1
    
    # Check if files exist
    if not pdf_files:
        logging.warning("No PDF files found in the input folder.")
        return 0
    
    total_files = len(pdf_files)
    logging.info(f"Found {total_files} PDF file(s) to process")
    
    # Check for duplicate files if enabled
    if config_manager.get("check_duplicates", True):
        file_paths = [os.path.join(input_folder, f) for f in pdf_files]
        duplicate_groups = pdf_verifier.find_duplicate_files(file_paths)
        
        if duplicate_groups:
            logging.warning(f"Found {len(duplicate_groups)} groups of duplicate files:")
            for hash_val, paths in duplicate_groups.items():
                logging.warning(f"  Duplicate group ({len(paths)} files):")
                for path in paths:
                    original_file = os.path.basename(path)
                    logging.warning(f"    - {original_file}")
                    
                # Add more detailed log for each duplicate group
                first_file = os.path.basename(paths[0])
                duplicates = [os.path.basename(p) for p in paths[1:]]
                logging.info(f"  Original: {first_file}, Duplicates: {', '.join(duplicates)}")
            
            if not args.process_duplicates and not args.dry_run:
                logging.info("Use --process-duplicates to process duplicate files")
                # Filter out duplicates, keeping only first file of each group
                unique_files = set()
                for file_path in file_paths:
                    file_hash = pdf_verifier.get_file_hash(file_path)
                    if file_hash in duplicate_groups:
                        # Only include first file from each duplicate group
                        if file_path == duplicate_groups[file_hash][0]:
                            unique_files.add(os.path.basename(file_path))
                    else:
                        unique_files.add(os.path.basename(file_path))
                
                pdf_files = [f for f in pdf_files if f in unique_files]
                logging.info(f"Processing {len(pdf_files)} unique files after removing duplicates")
    
    # Always show previews first
    logging.info("\n=== PREVIEW MODE ===")
    preview_results = []
    
    # Get batch size from config
    batch_size = config_manager.get("batch_size", 20)
    
    # Verify all files first if enabled
    if config_manager.get("file_verification", True):
        logging.info("Verifying PDF files...")
        verified_files = []
        failed_verification = []
        
        for filename in pdf_files:
            file_path = os.path.join(input_folder, filename)
            is_valid, message = pdf_verifier.verify_pdf(file_path)
            
            if is_valid:
                verified_files.append(filename)
            else:
                logging.warning(f"File verification failed for {filename}: {message}")
                failed_verification.append((filename, message))
        
        if failed_verification:
            logging.warning(f"{len(failed_verification)} files failed verification")
            
            # Try to repair files if recovery is enabled
            if config_manager.get("auto_recovery", True):
                repaired_files = []
                for filename, _ in failed_verification:
                    file_path = os.path.join(input_folder, filename)
                    if error_recovery.can_attempt_recovery(file_path):
                        logging.info(f"Attempting to repair {filename}")
                        success, repaired_path = error_recovery.attempt_pdf_repair(file_path)
                        
                        if success:
                            repaired_files.append((filename, repaired_path))
                            logging.info(f"Successfully repaired {filename}")
                
                # Add repaired files to verified list
                for filename, repaired_path in repaired_files:
                    verified_files.append(filename)
                    logging.info(f"Added repaired file {filename} to processing queue")
        
        # Use only verified files
        pdf_files = verified_files
        logging.info(f"{len(pdf_files)} files verified and ready for processing")
    
    # Process files in batches to avoid memory issues with large numbers of files
    processed_count = 0
    preview_results = []  # Initialize preview_results list

    for i in range(0, len(pdf_files), batch_size):
        batch = pdf_files[i:i + batch_size]
        batch_end = min(i + batch_size, len(pdf_files))
        logging.info(f"\nProcessing batch {i//batch_size + 1} ({i+1}-{batch_end} of {len(pdf_files)})")
        
        for filename in batch:
            processed_count += 1
            file_path = os.path.join(input_folder, filename)
            logging.info(f"[{processed_count}/{len(pdf_files)}] Processing file: {filename}")
            
            # Extract information from PDF
            try:
                text, statement_info = pdf_processor.process_pdf(file_path)
                
                if statement_info:
                    logging.info(f"Extracted information: {statement_info}")
                else:
                    logging.warning(f"Could not extract information from {filename}")
                    statement_info = StatementInfo()  # Empty info object
                
                # Process the file in preview mode
                success, message = file_manager.process_file(
                    file_path, processed_folder, dry_run=True
                )
                
                # Track results
                if success:
                    preview_results.append((file_path, statement_info, message))
                    logging.info(message)
                else:
                    logging.error(message)
            except Exception as e:
                error_recovery.record_error("extraction_error")
                logging.error(f"Error processing {filename}: {str(e)}")
                continue
    
    # If show-preview flag is set, display detailed preview by bank
    if args.show_preview and args.dry_run:
        # Group by bank type
        preview_by_bank = {}
        for file_path, statement_info, message in preview_results:
            bank_type = statement_info.bank_type if statement_info and statement_info.bank_type else "Unlabeled"
            if bank_type not in preview_by_bank:
                preview_by_bank[bank_type] = []
            # Format output to be easy to parse by the batch file
            original_filename = os.path.basename(file_path) 
            # Get the full destination path for better display
            if "Would rename to:" in message:
                dest_path = message.split("Would rename to: ")[1]
            else:
                dest_path = f"Unlabeled {original_filename}"
            
            # Include original filename for clarity
            output_line = f"From: {original_filename} -> To: {dest_path}"
            
            # Format exactly how the batch file is expecting to parse it
            if bank_type == "PNC":
                preview_by_bank[bank_type].append(f"PNCBank: {output_line}")
            elif bank_type == "Berkshire":
                preview_by_bank[bank_type].append(f"BerkshireBank: {output_line}")
            elif bank_type == "BankUnited":
                preview_by_bank[bank_type].append(f"BankUnited: {output_line}")
            elif bank_type == "Cambridge":
                preview_by_bank[bank_type].append(f"CambridgeSavings: {output_line}")
            else:
                preview_by_bank[bank_type].append(f"Unlabeled: {output_line}")
        
        # Print preview by bank formatted to be easy to parse by the batch file
        # Also print a summary count for each bank
        print(f"PREVIEW_SUMMARY: Found statements from {len(preview_by_bank)} bank types")
        for bank, files in sorted(preview_by_bank.items()):
            if not files:
                continue
            
            # Print a marker that the batch file can use to count files per bank
            print(f"BANK_COUNT: {bank} {len(files)}")
            
            # Print the individual files
            for file_info in files:
                print(file_info)
    
    # If dry-run flag is set, exit after preview
    if args.dry_run:
        elapsed_time = time.time() - start_time
        logging.info(f"\nDry run completed in {elapsed_time:.2f} seconds.")
        
        # --- Explicitly use absolute path for checklist --- 
        checklist_dir_abs = os.path.abspath(args.checklist_dir)
        logging.info(f"Using absolute path for checklist directory: {checklist_dir_abs}")
        # --------------------------------------------------
        
        # Generate checklist for dry run using the absolute path
        checklist_path = file_manager.generate_checklist(checklist_dir_abs, dry_run=True)
        logging.info(f"Preview checklist saved to: {checklist_path}")
        
        # Add a clear message about the number of files that would be processed
        num_files = len(preview_results)
        logging.info(f"{num_files} files would be processed.")
        
        # Print special markers for the batch file to capture
        print(f"PROCESSED_COUNT: {num_files}")
        print(f"CHECKLIST_PATH: {checklist_path}")
        
        return 0
        
    # Otherwise, ask for confirmation before proceeding unless auto-confirm is set
    if not args.auto_confirm:
        print(f"\nReady to process {len(preview_results)} files. Continue? (y/n): ")
        user_input = input().strip().lower()
        
        if user_input != 'y' and user_input != 'yes':
            logging.info("Operation cancelled by user.")
            return 0
    else:
        logging.info(f"Auto-confirm enabled, processing {len(preview_results)} files without prompt.")
        
    # Process files for real
    logging.info("\n=== PROCESSING FILES ===")
    results = {"success": 0, "failure": 0}
    processed_count = 0
    total_to_process = len(preview_results)
    
    # Process in smaller batches to release memory
    for i in range(0, total_to_process, batch_size):
        batch = preview_results[i:i + batch_size]
        batch_end = min(i + batch_size, total_to_process)
        logging.info(f"\nProcessing batch {i//batch_size + 1} ({i+1}-{batch_end} of {total_to_process})")
        
        for file_path, statement_info, _ in batch:
            processed_count += 1
            filename = os.path.basename(file_path)
            
            # --- Skip file if it couldn't be identified --- 
            if not statement_info or statement_info.bank_type == "Unlabeled":
                logging.warning(f"[{processed_count}/{total_to_process}] Skipping unidentified file: {filename}")
                continue # Skip to the next file in the batch
            # ----------------------------------------------

            logging.info(f"[{processed_count}/{total_to_process}] Processing file: {filename}")
            
            try:
                success, message = file_manager.process_file(
                    file_path, processed_folder, dry_run=False
                )
                
                if success:
                    results["success"] += 1
                    logging.info(message)
                else:
                    results["failure"] += 1
                    error_recovery.record_error("file_operation_error")
                    logging.error(message)
            except Exception as e:
                results["failure"] += 1
                error_recovery.record_error("unexpected_error")
                logging.error(f"Unexpected error processing {filename}: {str(e)}")
    
    # Generate final checklist
    checklist_path = file_manager.generate_checklist(args.checklist_dir)
    logging.info(f"Checklist saved to: {checklist_path}")
    
    # Print special markers for the batch file to capture
    print(f"PROCESSED_COUNT: {len(file_manager.processed_files)}")
    print(f"CHECKLIST_PATH: {checklist_path}")
    
    elapsed_time = time.time() - start_time
    logging.info(f"\nProcessing completed in {elapsed_time:.2f} seconds.")
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logging.info("Operation interrupted by user.")
        sys.exit(130)
    except Exception as e:
        logging.critical(f"Unhandled exception: {str(e)}", exc_info=True)
        sys.exit(1)