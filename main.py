# c:\Users\Christian\OneDrive - Arctaris Michigan Partners, LLC\Desktop\Bank Automation\Codes\Bank Statements\main.py
import os
import sys
import time
import logging
from typing import List, Dict, Tuple, Any, Optional
import concurrent.futures # Keep for potential future parallelization
import argparse
from config_manager import ConfigManager
from pdf_processor import PDFProcessor
from file_manager import FileManager
from utils import setup_logging, parse_arguments, PDFVerifier, ErrorRecovery, EnhancedJSONEncoder
from bank_strategies import BankStrategy, UnlabeledStrategy
from statement_info import StatementInfo
import json
from collections import defaultdict
import traceback # Added for detailed exception logging
import subprocess # Added for dependency check
import pkg_resources # Added for dependency check

# --- Dependency Check Logic ---
# NOTE: Auto-installing dependencies is generally discouraged.
# It\'s better to use virtual environments and install manually via `pip install -r requirements.txt`
# This function attempts to check and install if key packages are missing.
def check_and_install_dependencies(requirements_file='requirements.txt'):
    """Checks if required packages are installed and tries to install them if not."""
    required = []
    try:
        with open(requirements_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Basic parsing: get package name before version specifiers
                    match = re.match(r'^([a-zA-Z0-9_-]+)\s*[=<>~!]?.*', line)
                    if match:
                        required.append(match.group(1))
    except FileNotFoundError:
        logging.error(f"'{requirements_file}' not found. Cannot check dependencies.")
        return
    except Exception as e:
        logging.error(f"Error reading '{requirements_file}': {e}")
        return

    missing = []
    for package in required:
        try:
            pkg_resources.get_distribution(package)
            logging.debug(f"Package '{package}' found.")
        except pkg_resources.DistributionNotFound:
            logging.warning(f"Required package '{package}' not found.")
            missing.append(package)
        except Exception as e:
            logging.error(f"Error checking package '{package}': {e}. Assuming it might be missing.")
            missing.append(package) # Assume missing if check fails

    if missing:
        logging.warning(f"Missing required packages: {', '.join(missing)}. Attempting installation...")
        try:
            # Use sys.executable to ensure pip from the correct environment is used
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', requirements_file])
            logging.info(f"Successfully installed packages from '{requirements_file}'. Please restart the script if needed.")
            # Optional: Re-check after installation, or just exit/inform user to restart
        except subprocess.CalledProcessError as e:
            logging.critical(f"Failed to install dependencies using pip: {e}. Please install manually: pip install -r {requirements_file}")
            sys.exit(1) # Exit if dependencies cannot be installed
        except FileNotFoundError:
             logging.critical(f"'pip' command not found. Cannot install dependencies. Please ensure Python and pip are correctly installed and in PATH.")
             sys.exit(1)
    else:
        logging.info("All required dependencies are installed.")

# --- Main Application Logic ---

class PdfRenamerApp:
    """Orchestrates the PDF renaming process."""

    def __init__(self):
        self.args = parse_arguments() # 1. Parse arguments first
        
        # --- Setup Logging EARLY --- 
        # Use arg log level if provided, otherwise default to INFO for now
        # We need logging set up *before* ConfigManager initialization to capture its internal logs
        initial_log_level = self.args.log_level or "INFO" 
        log_file = setup_logging(initial_log_level, self.args.log_file) # Setup logging BEFORE ConfigManager
        logging.info(f"Initial logging setup complete (Level: {initial_log_level}, File: {log_file})")
        # --- Logging Setup Done ---
        
        # 2. Initialize Config Manager (NOW its internal logs should be captured)
        self.config_manager = ConfigManager(self.args.config)

        # 3. Optionally refine log level based on loaded config 
        # (This might be redundant if initial_log_level is sufficient, but keeps existing logic)
        final_log_level = self.args.log_level or self.config_manager.get("log_level", "INFO")
        if final_log_level != initial_log_level:
             logging.info(f"Adjusting log level based on config/args to: {final_log_level}")
             # Re-getting the logger and setting level might be needed depending on setup_logging implementation
             # For simplicity, let's assume setup_logging handles this or the initial level is sufficient.
             # If necessary, add: logging.getLogger().setLevel(final_log_level.upper())
             pass # Placeholder if re-configuration needed
        else:
             log_level = final_log_level # Assign for consistency with later code

        # Initialize other core components
        self.pdf_verifier = PDFVerifier()
        self.error_recovery = ErrorRecovery(self.config_manager) # Pass config
        self.pdf_processor = PDFProcessor(self.config_manager)
        self.file_manager = FileManager(self.config_manager)

        # Determine effective input/output paths
        self.input_folder = self.args.input or self.config_manager.get("input_folder")
        self.processed_folder = self.args.output or self.config_manager.get("processed_folder")
        self.checklist_dir = self.args.checklist_dir

        # Validate paths
        if not self.input_folder or not os.path.isdir(self.input_folder):
            logging.critical(f"Invalid or missing input folder: {self.input_folder}")
            sys.exit(1) # Exit if input is invalid

        logging.info("=" * 40)
        logging.info(f"PDF Renamer Initialized (Dry Run: {self.args.dry_run})")
        logging.info(f"Input Folder: {self.input_folder}")
        logging.info(f"Output Folder: {self.processed_folder}")
        logging.info(f"Config File: {self.args.config}")
        logging.info(f"Log File: {log_file}")
        logging.info("=" * 40)

        self.files_to_process: List[str] = []
        self.processing_results: Dict[str, Any] = {"success": 0, "skipped": 0, "error": 0}


    def _collect_files(self) -> List[str]:
        """Collects and filters initial PDF files from the input folder."""
        try:
            all_files = [
                f for f in os.listdir(self.input_folder)
                if os.path.isfile(os.path.join(self.input_folder, f)) and f.lower().endswith('.pdf')
            ]
            # Filter out already repaired files to avoid processing them directly
            original_files = [f for f in all_files if not f.lower().endswith('.repaired.pdf')]
            repaired_files_count = len(all_files) - len(original_files)
            if repaired_files_count > 0:
                 logging.info(f"Ignoring {repaired_files_count} existing '.repaired.pdf' file(s).")

            pdf_files = [os.path.join(self.input_folder, f) for f in original_files]
            logging.info(f"Found {len(pdf_files)} PDF file(s) in input folder.")
            return pdf_files
        except FileNotFoundError:
            logging.critical(f"Input directory not found: '{self.input_folder}'")
            sys.exit(1)
        except PermissionError:
            logging.critical(f"Permission denied when trying to read directory: '{self.input_folder}'")
            sys.exit(1)
        except OSError as e: # Catch other potential OS errors related to reading directory
            logging.critical(f"Error reading input directory '{self.input_folder}': {e}", exc_info=True)
            sys.exit(1)


    def _handle_duplicates(self, pdf_files: List[str]) -> List[str]:
        """Identifies duplicates and filters list if not processing them."""
        if not self.config_manager.get("check_duplicates", True):
            return pdf_files

        logging.info("Checking for duplicate files...")
        duplicate_groups = self.pdf_verifier.find_duplicate_files(pdf_files)

        if not duplicate_groups:
            logging.info("No duplicate files found.")
            return pdf_files

        logging.warning(f"Found {len(duplicate_groups)} group(s) of duplicate files:")
        files_to_skip = set()
        for i, (hash_val, paths) in enumerate(duplicate_groups.items()):
            logging.warning(f"  Duplicate Group {i+1} (Hash: {hash_val[:8]}..., {len(paths)} files):")
            # Log all files in the group
            for p in paths: logging.warning(f"    - {os.path.basename(p)}")
            # Mark all but the first one for skipping (unless --process-duplicates is set)
            if not self.args.process_duplicates:
                files_to_skip.update(paths[1:])

        if files_to_skip:
             logging.warning(f"Skipping {len(files_to_skip)} duplicate file(s). Use --process-duplicates to process all.")
             return [f for f in pdf_files if f not in files_to_skip]
        else:
             logging.info("Processing all files including duplicates (--process-duplicates specified or only one file per hash).")
             return pdf_files


    def _verify_and_repair_files(self, pdf_files: List[str]) -> List[str]:
        """Verifies files and attempts repair if enabled."""
        if not self.config_manager.get("file_verification", True):
            return pdf_files

        logging.info("Verifying PDF files...")
        verified_files = []
        failed_verification: List[Tuple[str, str]] = [] # (filepath, message)

        for file_path in pdf_files:
            is_valid, message = self.pdf_verifier.verify_pdf(file_path)
            if is_valid:
                verified_files.append(file_path)
            else:
                logging.warning(f"Verification failed for {os.path.basename(file_path)}: {message}")
                failed_verification.append((file_path, message))
                self.error_recovery.record_error("verification_failed", os.path.basename(file_path))

        if not failed_verification:
             logging.info("All files passed verification.")
             return verified_files

        logging.warning(f"{len(failed_verification)} file(s) failed verification.")

        # Attempt repair if enabled
        if self.config_manager.get("auto_recovery", True):
            logging.info("Attempting repairs for failed files...")
            repaired_count = 0
            for file_path, reason in failed_verification:
                 success, repaired_path = self.error_recovery.attempt_pdf_repair(file_path)
                 if success and repaired_path:
                      # Verify the *repaired* file before adding it
                      is_repaired_valid, msg = self.pdf_verifier.verify_pdf(repaired_path)
                      if is_repaired_valid:
                           logging.info(f"Successfully repaired and verified: {os.path.basename(repaired_path)}")
                           # Replace original with repaired path in the list to process
                           verified_files.append(repaired_path)
                           repaired_count += 1
                           # Should we remove the original bad file now? Configurable?
                           # os.remove(file_path)
                      else:
                           logging.error(f"Repaired file {os.path.basename(repaired_path)} failed verification: {msg}. Skipping.")
                           self.error_recovery.record_error("repair_verification_failed", os.path.basename(repaired_path))
                 else:
                     logging.error(f"Repair failed for {os.path.basename(file_path)}.")
                     self.error_recovery.record_error("repair_failed", os.path.basename(file_path))

            if repaired_count > 0:
                logging.info(f"Added {repaired_count} successfully repaired file(s) to the processing list.")
        else:
             logging.info("Auto-recovery disabled, skipping repair attempts.")


        logging.info(f"Proceeding with {len(verified_files)} verified/repaired file(s).")
        return verified_files


    def _run_preview(self, files_to_process: List[str]):
        """Runs the processing logic in dry-run mode and gathers results."""
        logging.info("\n=== DRY RUN PREVIEW ===")
        # Store tuples of (original_path, statement_info, strategy, preview_details_dict)
        preview_data: List[Tuple[str, Optional[StatementInfo], Optional[BankStrategy], Optional[Dict[str, Any]]]] = []

        total_files = len(files_to_process)
        for i, file_path in enumerate(files_to_process):
            filename = os.path.basename(file_path)
            logging.info(f"[{i+1}/{total_files}] Previewing: {filename}")

            statement_info, strategy = self.pdf_processor.process_pdf(file_path)

            if statement_info and strategy:
                # Call file manager in dry-run to get structured details
                success, details = self.file_manager.process_file(
                     file_path, self.processed_folder, statement_info, strategy, dry_run=True
                )
                if success:
                     # Store the dictionary 'details' instead of the old message string
                     preview_data.append((file_path, statement_info, strategy, details))
                else:
                     # details is the error message string in this case
                     logging.error(f"Dry run simulation failed for {filename}: {details}")
                     self.processing_results["error"] += 1
                     preview_data.append((file_path, statement_info, strategy, None)) # Add entry even on failure for counts?
            else:
                 logging.warning(f"Skipping preview for {filename}: Failed to extract info or determine strategy.")
                 self.file_manager._log_processed_file(file_path, "N/A", "Unknown", "Skipped (Extraction/Strategy Fail)", True)
                 self.processing_results["skipped"] += 1
                 preview_data.append((file_path, None, None, None)) # Add entry even on failure for counts?

        # Display detailed preview if requested
        if self.args.show_preview:
            logging.info("\n--- Detailed Preview by Bank ---")
            preview_by_bank = defaultdict(list)
            # Iterate through the updated preview_data structure
            for _, info, _, details_dict in preview_data:
                 # Ensure details_dict is not None and contains expected keys
                 if details_dict and isinstance(details_dict, dict):
                     bank_type = details_dict.get('bank_type', 'Unknown')
                     original_file = details_dict.get('original_filename', 'N/A')
                     dest_path = details_dict.get('relative_destination', 'Error')
                     preview_by_bank[bank_type].append(f"  From: {original_file} -> To: {dest_path}")
                 elif info: # Fallback if details dict failed but we have info
                      preview_by_bank[info.bank_type].append(f"  From: {os.path.basename(_)} -> To: Error/Skipped")
                 # else: Skip if no info and no details

            if not preview_by_bank:
                 print("PREVIEW_SUMMARY: No files would be processed.")
            else:
                print(f"PREVIEW_SUMMARY: Found statements from {len(preview_by_bank)} bank type(s).")
                for bank, files in sorted(preview_by_bank.items()):
                    print(f"BANK_COUNT: {bank} {len(files)}") # Marker for batch file
                    for file_info in files:
                         print(file_info)
            print("-" * 30) # End of preview marker for batch

        # Generate preview checklist
        # checklist_path = self.file_manager.generate_checklist(self.checklist_dir, dry_run=True) # <-- Temporarily commented out to test performance
        # if checklist_path:
        #    logging.info(f"Preview checklist saved to: {checklist_path}")
        #    print(f"CHECKLIST_PATH: {checklist_path}") # Marker for batch file

        # Calculate count based on successful previews (where details_dict is present)
        num_processed = sum(1 for _, _, _, d in preview_data if d is not None)
        logging.info(f"\nDry run complete. {num_processed} file(s) would be processed.")
        print(f"PROCESSED_COUNT: {num_processed}") # Marker for batch file

        return preview_data


    def _run_processing(self, preview_data: List[Tuple[str, Optional[StatementInfo], Optional[BankStrategy], Optional[Dict[str, Any]]]]):
        """Runs the actual file processing based on previewed data."""
        # Filter out entries where preview failed (details_dict is None)
        valid_preview_data = [(fp, info, strat, det) for fp, info, strat, det in preview_data if info and strat and det]

        if not valid_preview_data:
             logging.warning("No files with successful preview data to process.")
             return

        total_to_process = len(valid_preview_data)
        logging.info(f"\n=== PROCESSING {total_to_process} FILES ===")

        # Confirmation is handled by --auto-confirm argument. If not set and not a dry run, 
        # the script should ideally have already exited or handled it earlier.
        # We proceed if --auto-confirm is True OR if it's not set but we reached here (implied confirmation).
        if not self.args.auto_confirm and not self.args.dry_run:
            # This check might be redundant if entry point logic prevents non-interactive without --auto-confirm
            logging.warning("Running without --auto-confirm. Assuming confirmation as script is interactive.")
            # If we *really* wanted to block non-interactive without the flag, we could check sys.stdin.isatty()
            # but relying on the argument is cleaner.

        logging.info("Starting file processing...")
        # Reset results for actual run
        self.processing_results = {"success": 0, "skipped": 0, "error": 0}

        # --- Optional: Parallel Processing ---
        # max_workers = self.config_manager.get("max_workers", 1)
        # if max_workers > 1:
        #     logging.info(f"Using parallel processing with {max_workers} workers.")
        #     with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        #         futures = [
        #             executor.submit(self._process_single_file, file_path, info, strategy)
        #             for file_path, info, strategy, _ in preview_data
        #         ]
        #         for future in concurrent.futures.as_completed(futures):
        #             # Handle results/exceptions if needed, logging is done in the worker
        #             try: future.result()
        #             except Exception as exc: logging.error(f"Error in parallel task: {exc}")
        # else: # Sequential processing
        #     logging.info("Using sequential processing.")
        #     for i, (file_path, info, strategy, _) in enumerate(preview_data):
        #          logging.info(f"[{i+1}/{total_to_process}] Processing: {os.path.basename(file_path)}")
        #          self._process_single_file(file_path, info, strategy)
        # --- End Optional Parallel ---

        # --- Start Sequential Processing (Simpler for now) ---
        logging.info("Using sequential processing.")
        # The valid_preview_data contains the already instantiated strategy and file info
        for i, (file_path, info, strategy, details_dict) in enumerate(valid_preview_data):
            logging.info(f"[{i+1}/{total_to_process}] Processing: {os.path.basename(file_path)}")
            # We already have the statement_info and strategy from the preview_data tuple
            # Check info and strategy again just in case, although filtering should handle this
            if info and strategy:
                 self._process_single_file(file_path, info, strategy)
            # else: This case should ideally not happen due to filtering

        # --- End Sequential Processing ---

        # Generate final checklist
        checklist_path = self.file_manager.generate_checklist(self.checklist_dir, dry_run=False)
        if checklist_path:
             print(f"CHECKLIST_PATH: {checklist_path}") # Marker for batch file

        logging.info(f"\nProcessing Summary: Success={self.processing_results['success']}, Skipped={self.processing_results['skipped']}, Error={self.processing_results['error']}")
        # Log detailed error summary
        error_summary = self.error_recovery.get_summary()
        if error_summary["total_errors_recorded"] > 0:
             logging.info(f"Error Details: {error_summary}")

        # Optionally generate checklist
        if self.checklist_dir:
             checklist_path = self.file_manager.generate_checklist(self.checklist_dir, dry_run=self.args.dry_run)
             if checklist_path:
                  logging.info(f"Processing checklist generated: {checklist_path}")
             else:
                  logging.error("Failed to generate checklist.")

        # --- Generate and Display Summary ---
        logging.info("\n" + "=" * 20 + " Processing Summary " + "=" * 20)
        print("\n" + "=" * 20 + " Processing Summary " + "=" * 20)

        # Get stats from PDFProcessor
        final_stats = self.pdf_processor.get_extraction_stats()

        # Get total files processed/attempted from FileManager log
        total_attempted = len(self.file_manager.processed_files_log)
        summary_lines = [f"Total files attempted: {total_attempted}"]

        # Combine PDFProcessor stats with FileManager log counts for a comprehensive view
        # Note: FileManager log might have entries for files skipped *before* PDFProcessor stage (e.g., duplicates)
        processed_count = 0
        skipped_count = 0
        error_count = 0
        for log_entry in self.file_manager.processed_files_log:
            status = log_entry.get("Status", "").lower()
            if "processed" in status or "would process" in status:
                processed_count += 1
            elif "skipped" in status:
                skipped_count += 1
            elif "error" in status:
                error_count += 1
            # Add other status checks if needed

        summary_lines.append(f"Files processed successfully: {processed_count}")
        summary_lines.append(f"Files skipped: {skipped_count}")
        summary_lines.append(f"Files with errors: {error_count}")

        # Add detailed stats from PDFProcessor if available
        if final_stats:
             summary_lines.append("-" * 20)
             summary_lines.append("Detailed PDF Processor Stats:")
             for key, value in sorted(final_stats.items()):
                  summary_lines.append(f"  - {key.replace('_', ' ').title()}: {value}")

        # Log and print the summary
        summary_output = "\n".join(summary_lines)
        logging.info(summary_output)
        print(summary_output)

        logging.info("=" * 58) # Match length of title line
        print("=" * 58)

        logging.info("PDF Renamer finished.")


    def _process_single_file(self, file_path: str, statement_info: StatementInfo, strategy: BankStrategy):
        """Wrapper to process a single file (used by sequential/parallel execution)."""
        try:
            success, message = self.file_manager.process_file(
                file_path, self.processed_folder, statement_info, strategy, dry_run=False
            )
            if success:
                 self.processing_results["success"] += 1
            else:
                 self.processing_results["error"] += 1
                 self.error_recovery.record_error("file_manager_error", os.path.basename(file_path))

        except Exception as e:
            logging.error(f"Critical error processing {os.path.basename(file_path)}: {e}", exc_info=True)
            self.processing_results["error"] += 1
            self.error_recovery.record_error("critical_processing_error", os.path.basename(file_path))
            # Ensure it's logged for checklist even on critical failure
            # Check if already logged by file_manager before adding again
            is_logged = any(item['Original File'] == os.path.basename(file_path) for item in self.file_manager.processed_files_log)
            if not is_logged:
                self.file_manager._log_processed_file(
                    file_path, "Error", statement_info.bank_type, "Error (Critical)", False
                )

    def run(self):
        """Execute the main application workflow."""
        start_time = time.time()

        # 1. Collect files
        pdf_files = self._collect_files()
        if not pdf_files:
            logging.warning("No PDF files found to process.")
            return 0 # Success exit code if no files

        # 2. Handle duplicates
        unique_files = self._handle_duplicates(pdf_files)
        if not unique_files:
             logging.warning("No unique files left to process after duplicate removal.")
             return 0

        # 3. Verify and repair
        self.files_to_process = self._verify_and_repair_files(unique_files)
        if not self.files_to_process:
             logging.warning("No files remaining after verification and repair attempts.")
             return 0

        # --- Process files in batches ---
        batch_size = 50
        total_files = len(self.files_to_process)
        logging.info(f"Processing {total_files} files in batches of {batch_size}...")

        # Accumulate overall results across batches
        overall_preview_data = []

        for i in range(0, total_files, batch_size):
            batch_files = self.files_to_process[i:min(i + batch_size, total_files)]
            batch_start_num = i + 1
            batch_end_num = min(i + batch_size, total_files)
            logging.info(f"\n--- Processing Batch {batch_start_num}-{batch_end_num}/{total_files} ---")

            # 4. Run Preview for the current batch
            batch_preview_data = self._run_preview(batch_files)
            overall_preview_data.extend(batch_preview_data) # Collect for final summary

            # 5. Process Files for the current batch (if not dry run)
            if not self.args.dry_run:
                 # Note: Confirmation prompt (if needed) will happen in the first batch
                 self._run_processing(batch_preview_data)

            logging.info(f"--- Finished Batch {batch_start_num}-{batch_end_num}/{total_files} ---")
            # Optional: Add a small delay between batches if needed
            # time.sleep(1) 

        # --- End Batch Processing ---

        # 6. Finish (Summary generation uses overall state managed by FileManager/PDFProcessor)
        elapsed_time = time.time() - start_time
        logging.info(f"\nApplication finished processing all batches in {elapsed_time:.2f} seconds.")

        # Return exit code based on errors? (0 for success, 1 for errors)
        return 1 if self.processing_results["error"] > 0 else 0


# --- Script Entry Point ---

if __name__ == "__main__":
    try:
        app = PdfRenamerApp()
        exit_code = app.run()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logging.warning("\nOperation interrupted by user (Ctrl+C).")
        sys.exit(130) # Standard exit code for Ctrl+C
    except Exception as e:
        # Catch-all for unexpected errors during initialization or run
        logging.critical(f"Unhandled exception occurred: {e}", exc_info=True)
        sys.exit(1) 