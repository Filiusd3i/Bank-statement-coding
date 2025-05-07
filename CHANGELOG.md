# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- End-of-run summary printed to console and logged, showing total files attempted, processed, skipped, and errored, plus detailed `PDFProcessor` stats.
- Detailed file processing log generated as a CSV checklist (`checklists/` folder).
- `--log-level` command-line argument (DEBUG, INFO, WARNING, ERROR, CRITICAL).
- `--show-preview` flag to display detailed dry run output grouped by bank.
- `--auto-confirm` flag to skip interactive confirmation prompt.
- Basic file verification (`verify_pdf`) and optional auto-repair (`attempt_pdf_repair`) using `pikepdf`.
- Duplicate file detection (based on hash) and option to skip or process duplicates (`--process-duplicates`).
- Support for BankUnited statements, including specific mappings for ARC Impact accounts.
- Support for Cambridge Savings Bank statements.
- Experimental auto-dependency check on startup in `main.py`.
- Integrated `PyMuPDF` as a fallback text extraction library in `PDFProcessor` if `pdfplumber` fails.
- **`match_status` field:** Added to `StatementInfo` and checklist output (`Success!`, `Fallback`, `Regex Match (Review)`, etc.) to indicate processing confidence.

### Changed
- Temporarily limited processing in `main.py` to the first 50 files for testing.
- Improved logging detail and clarity across modules.
- Refactored `PDFProcessor` to use strategy instances.
- Refactored `FileManager` for clarity and checklist generation.
- Switched default file operation from move to copy (`delete_originals` config option added, defaults to `False`).
- Renamed main script to `main.py` (from `pdf_renamer.py`).
- Standardized filename generation across strategies.
- Increased fuzzy matching threshold for BankUnited sensitive name checks to 0.95 for more accuracy.

### Fixed
- Prevented incorrect date fallback (`datetime.now()`) in all strategies; uses `None` date with appropriate filename/path fallbacks (`NODATE`/`UnknownDate`) instead.
- Handled potential `FileNotFoundError` during config loading more gracefully.
- Improved exception handling in `main.py` (`_collect_files`) to catch specific `FileNotFoundError` and `PermissionError` instead of generic `Exception`.
- Corrected `re.error: nothing to repeat` in `BerkshireStrategy` (and preventatively in `CambridgeStrategy`) by removing an erroneous `?` after `$` in several regex patterns.
- **CambridgeStrategy Date Extraction:** Resolved issue where dates were not extracted due to statement period information being split across lines. Implemented a landmark-based search (looking near "Statement Period"/"Statement Date") to reliably find and parse the end date.
- Fixed `ValueError` in checklist generation due to mismatched fieldnames.
- **BankUnited Account Number:** Correctly extract masked account numbers (e.g., `******1234`) and differentiate accounts with the same name but different numbers (e.g., Operating vs. MMK) by validating extracted number against sensitive list entry. Resolved filename collision issue.

### Removed
- Deleted unused script `bank_statement_simple.py`.
- Removed old `process_statement` function from `main.py` in favor of `PDFProcessor` class.
- Removed direct dependency on `PyPDF2` in favor of `pdfplumber` and `PyMuPDF`.

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