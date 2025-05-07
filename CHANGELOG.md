# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- End-of-run summary printed to console and logged, showing total files attempted, processed, skipped, and errored, plus detailed `PDFProcessor` stats.
- Support for loading sensitive account data (name, number) from `sensitive_accounts.yaml` (file itself is gitignored).
- Helper methods in `BankStrategy` base class for matching sensitive data (`_find_sensitive_match_by_number`, `_find_sensitive_match_by_name`).
- Logic in `config_manager.py` to safely load `sensitive_accounts.yaml` if present.
- `python-Levenshtein` and `PyYAML` to `requirements.txt`.
- Standard Python entries and `sensitive_accounts.yaml` to `.gitignore`.
- Experimental auto-dependency check on startup in `main.py`.
- Integrated `PyMuPDF` as a fallback text extraction library in `PDFProcessor` if `pdfplumber` fails.

### Changed
- Temporarily limited processing in `main.py` to the first 50 files for testing.
- Modified `PDFProcessor` (`process_pdf`) to return `None` for `StatementInfo` if `UnlabeledStrategy` is used, preventing renaming/moving.
- Refactored `main.py` preview logic (`_run_preview`) to use structured data from `file_manager`.
- Modified `file_manager.py` (`process_file`) to return structured dictionary on dry run success.
- Updated PNC bank statement filename format to: `[Account name] statement_[account number]_YYYY_MM_DD.pdf`.
- Updated BankUnited bank statement filename format to match Cambridge Savings: `[Account Name] [Account Number] BankUnited [Month] [Year].pdf`.
- Updated `UnlabeledStrategy.get_filename` to return the original filename, preserving it for manual review.
- Simplified `PNCStrategy` to always place files directly in the `PNC` output folder (removed date subfolder) and prepend the matched account name to the original filename.
- Simplified `PNCStrategy.get_filename` to prepend account name to original filename.
- Corrected PNC date extraction logic by adjusting loop control flow in `PNCStrategy.extract_info`.
- Updated `PNCStrategy.get_subfolder_path` to use `YYYY/Month` format (e.g., `PNC/2025/April`).
- Implemented batch processing in `main.py`'s `run` method to handle files in chunks of 50.
- Confirmed successful end-to-end processing run with all recent PNC and batching changes; output duplicate handling overwrites existing files with a warning as intended.

### Removed
- Deleted unused script `Arctaris rename_statements.py`.
- Deleted unused helper scripts `simplified_bank_statements.bat`, `simplified_script.vbs`, `BankStatements.vbs`.
- Removed interactive `input()` confirmation from `main.py`, relying solely on `--auto-confirm` flag for non-dry runs.
- Removed redundant `BANK_STRATEGIES` dictionary definition from the end of `bank_strategies.py`.

### Fixed
- Prevented incorrect date fallback (`datetime.now()`) in all strategies; uses `None` date with appropriate filename/path fallbacks (`NODATE`/`UnknownDate`) instead.
- Corrected `config.json` structure and ensured `delete_originals: true` is loaded correctly, fixing issue where originals were not deleted.
- Removed date requirement from `is_successful` check in `PDFProcessor`, preventing files with failed date parsing from being incorrectly skipped.
- Prevented `UnlabeledStrategy` files from being moved or renamed; they are now skipped by `FileManager` and left in the input folder.
- Corrected various `IndentationError` issues within `bank_strategies.py`.
- Resolved `TypeError` in `pdf_processor.py` caused by incorrect `StatementInfo` initialization (passing `original_filename` to `__init__`).
- Corrected `AttributeError` typo in `pdf_processor.py` (called `_extract_text_with_plumber` instead of `_extract_text_with_pdfplumber`).
- Resolved `TypeError` in `pdf_processor.py` by adding the missing `filename` argument to the `_extract_text_with_pdfplumber` call.
- Improved exception handling in `main.py` (`_collect_files`) to catch specific `FileNotFoundError` and `PermissionError` instead of generic `Exception`.
- Corrected `re.error: nothing to repeat` in `BerkshireStrategy` (and preventatively in `CambridgeStrategy`) by removing an erroneous `?` after `$` in several regex patterns.
- **CambridgeStrategy Date Extraction:** Resolved issue where dates were not extracted due to statement period information being split across lines. Implemented a landmark-based search (looking near "Statement Period"/"Statement Date") to reliably find and parse the correct statement end date.

### Investigated & Decided
- **Berkshire PDF Processing:** Encountered issues with certain Berkshire PDF statements being image-based, preventing text extraction by both `pdfplumber` and `PyMuPDF`.
    - Due to environmental restrictions on installing system-level OCR tools (like Tesseract) and limitations with available PDF editing software for on-the-fly OCR, the decision has been made to handle these specific image-based Berkshire PDFs manually.
    - The script will currently process them using filename-based heuristics and default values if text extraction fails, which may not be ideal for these image-based files.
    - Future improvement could involve isolating these to a "manual review" folder.
- **Minor Issue:** Observed a transient "file in use" error during the deletion of an original PDF after processing. This might require making file closing in `PDFProcessor` more robust (e.g., using `finally` blocks).

### Notes
- Attempting processing run on limited batch (50 files) to verify recent fixes.

## [Next Steps]
- Address and implement bank statement processing strategy for Berkshire. 