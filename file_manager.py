# file_manager.py
import os
import shutil
import logging
import csv
from datetime import datetime
from typing import List, Dict, Tuple, Set, Optional, Any

# Assuming these are in sibling modules now
from config_manager import ConfigManager
from statement_info import StatementInfo
# We don't need the full strategy here, just the info object processed by it
# from bank_strategies import BankStrategy # Not strictly needed

class FileManager:
    """Manages file operations like copying, renaming, and organizing."""

    def __init__(self, config: ConfigManager):
        """Initialize with configuration."""
        self.config = config
        self._created_folders: Set[str] = set() # Cache for created folders
        self.processed_files_log: List[Dict[str, Any]] = [] # Log for checklist

    def ensure_folder_exists(self, folder_path: str, dry_run: bool = False) -> bool:
        """Ensure the folder exists, creating it if necessary."""
        if folder_path in self._created_folders or os.path.exists(folder_path):
            self._created_folders.add(folder_path) # Ensure it's cached
            return True
        if dry_run:
            logging.debug(f"Dry Run: Would create folder {folder_path}")
            return True
        try:
            os.makedirs(folder_path, exist_ok=True)
            self._created_folders.add(folder_path)
            logging.info(f"Created directory: {folder_path}")
            return True
        except Exception as e:
            logging.error(f"Error creating folder {folder_path}: {e}")
            return False

    def _get_non_conflicting_filename(self, dest_folder: str, desired_filename: str) -> str:
        """Checks if a filename exists and returns a non-conflicting version."""
        base_name, extension = os.path.splitext(desired_filename)
        counter = 1
        final_filename = desired_filename
        final_path = os.path.join(dest_folder, final_filename)

        while os.path.exists(final_path):
            final_filename = f"{base_name} ({counter}){extension}"
            final_path = os.path.join(dest_folder, final_filename)
            counter += 1
            if counter > 100: # Safety break
                 logging.error(f"Could not find non-conflicting name for {desired_filename} after 100 attempts in {dest_folder}")
                 raise FileExistsError("Too many conflicts finding destination filename.")

        if final_filename != desired_filename:
             logging.warning(f"Destination exists. Renaming to: {final_filename}")

        return final_filename

    def process_file(self,
                     source_filepath: str,
                     base_output_path: str,
                     statement_info: StatementInfo,
                     strategy: 'BankStrategy', # Forward reference if needed, or import later
                     dry_run: bool = False
                    ) -> Tuple[bool, Dict[str, Any] | str]:
        """
        Processes a single file: determines destination, copies/moves, logs.
        Returns a structured dictionary on dry run success.

        Args:
            source_filepath: Full path to the original PDF file.
            base_output_path: The root directory for processed statements.
            statement_info: The extracted information for the file.
            strategy: The BankStrategy object used (needed for path/name).
            dry_run: If True, only log actions without moving/copying.

        Returns:
            Tuple (success: bool, details: Dict[str, Any] | str).
            If dry_run is True and successful, details is a dictionary:
            {'original_filename': str, 'relative_destination': str, 'bank_type': str, 'status': str}
            Otherwise, details is a message string.
        """
        original_filename = os.path.basename(source_filepath)

        if not statement_info:
            message = f"Skipping {original_filename}: No statement info extracted."
            logging.warning(message)
            self._log_processed_file(source_filepath, "N/A", "Unknown", "Skipped (No Info)", dry_run)
            return False, message # Return message string on failure

        try:
            # 1. Get subfolder and filename from strategy
            relative_subfolder = strategy.get_subfolder_path(statement_info)
            desired_filename = strategy.get_filename(statement_info)

            # 2. Construct full destination path
            full_output_folder = os.path.join(base_output_path, relative_subfolder)

            # 3. Ensure destination folder exists
            if not self.ensure_folder_exists(full_output_folder, dry_run):
                message = f"Failed to create destination folder: {full_output_folder}"
                self._log_processed_file(source_filepath, "Error", statement_info.bank_type, f"Error (Folder Fail)", dry_run)
                return False, message

            # 4. Check for filename conflicts
            final_filename = self._get_non_conflicting_filename(full_output_folder, desired_filename)
            destination_filepath = os.path.join(full_output_folder, final_filename)
            relative_destination = os.path.join(relative_subfolder, final_filename).replace('\\\\', '/') # For logging and consistency

            # Prepare log details (even if dry run or error, to capture intent)
            log_account_name = statement_info.account_name
            log_account_number = statement_info.account_number
            log_statement_date = statement_info.date.strftime("%Y-%m-%d") if statement_info.date else "N/A"
            log_match_status = statement_info.match_status # Get from statement_info

            # --- ADD DEBUG LOGGING HERE ---
            logging.debug(f"FileManager.process_file - Logging for {original_filename}: Name='{log_account_name}', Num='{log_account_number}', Date='{log_statement_date}', MatchStatus='{log_match_status}'")
            # --- END DEBUG LOGGING ---

            if os.path.exists(destination_filepath) and not self.config.get("overwrite_duplicates_in_output", False):
                message = f"skip processing {original_filename}: Destination file already exists and overwrite is disabled: {destination_filepath}"
                self._log_processed_file(source_filepath, "Error", statement_info.bank_type, f"Error (Duplicate)", dry_run)
                return False, message # Return message string on failure

            # 5. Perform action (copy/move or log)
            if dry_run:
                status = "Would Process"
                message = f"Dry Run: Would copy '{original_filename}' to '{relative_destination}'"
                logging.info(message)
                self._log_processed_file(source_filepath, relative_destination, statement_info.bank_type, status, dry_run)
                # Return structured data on dry run success
                return True, {
                    "original_filename": original_filename,
                    "relative_destination": relative_destination,
                    "bank_type": statement_info.bank_type,
                    "status": status,
                    "message": message # Optional: include the log message too
                }
            else:
                try:
                    # Use copy2 to preserve metadata
                    shutil.copy2(source_filepath, destination_filepath)
                    message = f"Copied '{original_filename}' to '{relative_destination}'"
                    logging.info(message)

                    # Delete original if configured
                    if self.config.get("delete_originals", False):
                         try:
                              os.remove(source_filepath)
                              logging.info(f"Deleted original file: {source_filepath}")
                              message += " (Original Deleted)"
                              self._log_processed_file(source_filepath, relative_destination, statement_info.bank_type, "Processed (Original Deleted)", dry_run)
                         except Exception as del_err:
                              logging.error(f"Failed to delete original file {source_filepath}: {del_err}")
                              message += " (Delete Failed)"
                              self._log_processed_file(source_filepath, relative_destination, statement_info.bank_type, "Processed (Delete Failed)", dry_run)
                    else:
                         self._log_processed_file(source_filepath, relative_destination, statement_info.bank_type, "Processed", dry_run)

                    return True, message # Return message string on actual success

                except Exception as e:
                    message = f"Error copying file {original_filename} to {destination_filepath}: {e}"
                    logging.error(message, exc_info=True)
                    self._log_processed_file(source_filepath, relative_destination, statement_info.bank_type, f"Error (Copy Fail)", dry_run)
                    return False, message # Return message string on failure

        except Exception as e:
             message = f"Unexpected error processing file {original_filename}: {e}"
             logging.error(message, exc_info=True)
             self._log_processed_file(source_filepath, "Error", statement_info.bank_type if statement_info else "Unknown", "Error (Unexpected)", dry_run)
             return False, message # Return message string on failure

    def _log_processed_file(self, original_path: str, dest_path: str, bank_type: str, status: str, dry_run: bool,
                            account_name: Optional[str] = "N/A",
                            account_number: Optional[str] = "N/A",
                            statement_date: Optional[str] = "N/A",
                            match_status: Optional[str] = "N/A"):
        """Adds an entry to the internal log for checklist generation."""
        log_entry = {
            "Original File": os.path.basename(original_path),
            "Original Path": original_path,
            "New Filename": os.path.basename(dest_path) if dest_path and dest_path != "N/A" else "N/A",
            "New Path": dest_path,
            "Bank Type": bank_type or "Unknown",
            "Account Name": account_name or "N/A",
            "Account Number": account_number or "N/A",
            "Statement Date": statement_date or "N/A",
            "Match Status": match_status or "N/A",
            "Status": status,
            "Processed Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Dry Run": dry_run
        }
        self.processed_files_log.append(log_entry)
        logging.debug(f"Logged for checklist: {log_entry}")

    def generate_checklist(self, checklist_dir: Optional[str], dry_run: bool) -> Optional[str]:
        """Generates a CSV checklist of all processed files."""
        if not self.processed_files_log:
            logging.info("No files were processed or logged. Checklist not generated.")
            return None
        
        if not checklist_dir:
            checklist_dir = os.path.join(os.getcwd(), "checklists") 
            logging.info(f"Checklist directory not specified, defaulting to: {checklist_dir}")

        self._ensure_dir(checklist_dir)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = "DRYRUN_" if dry_run else ""
        checklist_filename = f"{prefix}processing_checklist_{timestamp}.csv"
        checklist_filepath = os.path.join(checklist_dir, checklist_filename)

        try:
            with open(checklist_filepath, 'w', newline='', encoding='utf-8') as csvfile:
                # Corrected and comprehensive fieldnames list
                fieldnames = [
                    "Original File", "Original Path", 
                    "New Filename", "New Path", 
                    "Bank Type", "Account Name", "Account Number", "Statement Date", 
                    "Match Status", "Status", 
                    "Processed Timestamp", "Dry Run"
                ]
                # Add 'Verified' if you still intend to use it for manual checks later
                # fieldnames.append("Verified") 
                
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore') # extrasaction='ignore' is safer
                writer.writeheader()
                for entry in self.processed_files_log:
                    writer.writerow(entry) # No need to pre-filter keys if using extrasaction='ignore'
            logging.info(f"Successfully generated checklist: {checklist_filepath}")
            return checklist_filepath
        except IOError as e:
            logging.error(f"Error writing checklist CSV to {checklist_filepath}: {e}", exc_info=True)
            return None
        except Exception as e:
            logging.error(f"An unexpected error occurred during checklist generation: {e}", exc_info=True)
            return None 