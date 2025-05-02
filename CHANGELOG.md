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

### Changed
- Modified `PDFProcessor` (`process_pdf`) to return `None` for `StatementInfo` if `UnlabeledStrategy` is used, preventing renaming/moving.
- Refactored `main.py` preview logic (`_run_preview`) to use structured data from `file_manager`.
- Modified `file_manager.py` (`process_file`) to return structured dictionary on dry run success.
- Updated PNC bank statement filename format to: `[Account name] statement_[account number]_YYYY_MM_DD.pdf`.
- Updated BankUnited bank statement filename format to match Cambridge Savings: `[Account Name] [Account Number] BankUnited [Month] [Year].pdf`.
- Updated `UnlabeledStrategy.get_filename` to return the original filename, preserving it for manual review.

### Removed
- Deleted unused script `Arctaris rename_statements.py`.
- Deleted unused helper scripts `simplified_bank_statements.bat`, `simplified_script.vbs`, `BankStatements.vbs`.
- Removed interactive `input()` confirmation from `main.py`, relying solely on `--auto-confirm` flag for non-dry runs.
- Removed redundant `BANK_STRATEGIES` dictionary definition from the end of `bank_strategies.py`.

### Fixed
- Prevented `UnlabeledStrategy` files from being moved or renamed; they are now skipped by `FileManager` and left in the input folder.
- Corrected various `IndentationError` issues within `bank_strategies.py`.
- Resolved `TypeError` in `pdf_processor.py` caused by incorrect `StatementInfo` initialization (passing `original_filename` to `__init__`).
- Corrected `AttributeError` typo in `pdf_processor.py` (called `_extract_text_with_plumber` instead of `_extract_text_with_pdfplumber`).
- Resolved `TypeError` in `pdf_processor.py` by adding the missing `filename` argument to the `_extract_text_with_pdfplumber` call.
- Improved exception handling in `main.py` (`_collect_files`) to catch specific `FileNotFoundError` and `PermissionError` instead of generic `Exception`. 