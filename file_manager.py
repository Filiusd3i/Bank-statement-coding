# c:\Users\Christian\OneDrive - Arctaris Michigan Partners, LLC\Desktop\Bank Automation\Codes\Bank Statements\file_manager.py
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
        self.processed_files_log: List[Dict[str, str]] = [] # Log for checklist

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

    def _log_processed_file(self, original_path: str, dest_path: str, bank_type: str, status: str, dry_run: bool):
        """Adds an entry to the internal log for checklist generation."""
        self.processed_files_log.append({
            'Original File': os.path.basename(original_path),
            'Destination File': dest_path.replace('\\', '/'), # Use consistent slashes
            'Bank Type': bank_type,
            'Status': status,
            'Verified': '' # Placeholder for manual verification
        })

    def generate_checklist(self, checklist_dir: str, dry_run: bool = False) -> Optional[str]:
        """
        Generate a CSV checklist of processed files.

        Args:
            checklist_dir: Path to save the checklist CSV.
            dry_run: Whether this was a dry run (affects filename).

        Returns:
            Path to the generated CSV file, or None on error.
        """
        if not self.ensure_folder_exists(checklist_dir, dry_run=dry_run):
             logging.error(f"Cannot create checklist directory: {checklist_dir}")
             return None
        if dry_run and not os.path.exists(checklist_dir):
             logging.info(f"Dry Run: Checklist would be saved in {checklist_dir}")
             return os.path.join(checklist_dir, "dry_run_checklist.csv") # Placeholder path

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        prefix = "preview_" if dry_run else ""
        csv_filename = f"{prefix}checklist_{timestamp}.csv"
        csv_path = os.path.join(checklist_dir, csv_filename)

        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Original File', 'Destination File', 'Bank Type', 'Status', 'Verified']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                # Sort log entries for consistency (optional, but nice)
                sorted_log = sorted(self.processed_files_log, key=lambda x: x.get('Original File', ''))
                writer.writerows(sorted_log)

            logging.info(f"Checklist generated: {csv_path}")
            return csv_path
        except Exception as e:
            logging.error(f"Failed to write checklist file {csv_path}: {e}", exc_info=True)
            return None 