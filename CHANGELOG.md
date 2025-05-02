# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Refactored `main.py` preview logic (`_run_preview`) to use structured data from `file_manager`.
- Modified `file_manager.py` (`process_file`) to return structured dictionary on dry run success.
- Updated PNC bank statement filename format to: `[Account name] statement_[account number]_YYYY_MM_DD.pdf`.
- Updated BankUnited bank statement filename format to match Cambridge Savings: `[Account Name] [Account Number] BankUnited [Month] [Year].pdf`.

### Removed
- Deleted unused script `Arctaris rename_statements.py`.
- Deleted unused helper scripts `simplified_bank_statements.bat`, `simplified_script.vbs`, `BankStatements.vbs`.
- Removed interactive `input()` confirmation from `main.py`, relying solely on `--auto-confirm` flag for non-dry runs.
- Removed redundant `BANK_STRATEGIES` dictionary definition from the end of `bank_strategies.py`.

### Fixed
- Corrected various `IndentationError` issues within `bank_strategies.py`.
- Resolved `TypeError` in `pdf_processor.py` caused by incorrect `StatementInfo` initialization (passing `original_filename` to `__init__`).
- Corrected `AttributeError` typo in `pdf_processor.py` (called `_extract_text_with_plumber` instead of `_extract_text_with_pdfplumber`).
- Resolved `TypeError` in `pdf_processor.py` by adding the missing `filename` argument to the `_extract_text_with_pdfplumber` call.
- Improved exception handling in `main.py` (`_collect_files`) to catch specific `FileNotFoundError` and `PermissionError` instead of generic `Exception`. 