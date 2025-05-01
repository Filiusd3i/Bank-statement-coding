# Bank Statement PDF Renamer and Organizer

This project automatically processes PDF bank statements, extracts key information, renames the files according to a standardized format, and organizes them into subfolders based on bank and date.

## How it Works

The script (`main.py`) serves as the entry point and orchestrates the workflow:

1.  **Collects PDF files** from a specified input folder.
2.  **Handles Duplicates:** Identifies and optionally skips processing duplicate files based on content hash.
3.  **Verifies & Repairs:** Checks if PDFs are valid and attempts to repair corrupted files (using external tools like `pikepdf` if configured, although the repair logic might need review/implementation).
4.  **Extracts Text:** Uses the `pdfplumber` library for robust text extraction from PDF pages.
5.  **Identifies Bank:** Determines the bank based first on filename patterns and then by analyzing the extracted text content using keyword scoring.
6.  **Applies Strategy:** Selects the appropriate bank-specific strategy (`bank_strategies.py`) to extract detailed information like account name, account number (or last 4 digits), and statement date.
7.  **Renames & Organizes:** Uses the extracted information and the corresponding strategy to generate a standardized filename (e.g., `BANK_YYYYMMDD_ACCOUNTNAME_LAST4.pdf`) and moves the processed file to an organized subfolder structure (e.g., `OutputFolder/BankName/YYYY-MM/`).
8.  **Generates Checklist:** Creates a CSV checklist (`processed_files_checklist_*.csv`) detailing the original filename, the new filename, the identified bank, and the processing status.

## Key Features

*   **Modular Design:** Code is organized into separate modules for better maintainability (`main.py`, `pdf_processor.py`, `bank_strategies.py`, `file_manager.py`, `config_manager.py`, `utils.py`).
*   **Robust PDF Parsing:** Utilizes `pdfplumber` for improved text extraction compared to basic methods.
*   **Intelligent Bank Identification:** Combines filename pattern matching and content analysis for better bank detection.
*   **Bank-Specific Logic:** Uses dedicated strategy classes for different banks (PNC, Berkshire, BankUnited, Cambridge) allowing for tailored data extraction.
*   **Configurable Mappings:** Account names/numbers can be mapped to specific identifiers using the `config.json` file.
*   **Automated Organization:** Creates a structured output directory based on Bank and Statement Date (Year-Month).
*   **Duplicate Detection:** Prevents processing the same file multiple times.
*   **File Verification & Repair (Optional):** Includes stubs for verifying PDF integrity and attempting repairs.
*   **Checklist Generation:** Provides a CSV log of processed files.
*   **Dry Run Mode:** Allows previewing all changes without modifying any files.

## Setup

1.  **Clone the repository (if applicable):**
    ```bash
    git clone https://github.com/Filiusd3i/Bank-statement-coding.git
    cd Bank-statement-coding
    ```
2.  **Install Dependencies:** Make sure you have Python 3 installed. Then, install the required libraries:
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: If PDF repair functionality is desired, `pikepdf` might need to be added to `requirements.txt` and its usage implemented in `utils.py`'s `ErrorRecovery` class.)*

## Configuration

The main configuration is handled by the `config.json` file. If it doesn't exist, the script will create one with default values upon first run.

Key settings to review/modify in `config.json`:

*   `input_folder`: Path to the directory containing the raw PDF statements.
*   `processed_folder`: Path where the renamed and organized statements will be saved.
*   `log_level`: Set the logging verbosity (e.g., "INFO", "DEBUG").
*   `pdf_scan_max_pages`: Maximum number of pages to scan for text extraction (default: 10).
*   `bank_id_min_score`: Minimum keyword score required for content-based bank identification (default: 2).
*   `account_mappings`: Contains nested dictionaries for mapping account numbers or other identifiers to desired account names for each bank (e.g., `pnc`, `berkshire_last4`, `cambridge_name_substring`).

**Example Account Mapping Structure:**

```json
{
  "account_mappings": {
    "pnc": {
      "FULL_ACCOUNT_NUMBER_1": "Your Desired Operating Account Name",
      "FULL_ACCOUNT_NUMBER_2": "Your Desired Savings Account Name"
    },
    "pnc_arc_impact_last4": {
       "LAST4_1": "Mapped Fund Name ABC"
    },
    "berkshire_last4": {
      "LAST4_2": "Mapped Fund Name XYZ",
      "LAST4_3": "Another Mapped Name"
    },
    // ... other banks use similar structures (e.g., 'bankunited_last4', 'cambridge_name_substring')
  },
  // ... other config settings
}
```

## Usage

Run the main script from your terminal in the project directory:

```bash
python main.py [OPTIONS]
```

**Common Options:**

*   `--dry-run`: **Recommended for first use.** Runs the entire process (extraction, identification, planning) but *does not* rename or move any files. Creates a `_dry_run_` checklist.
*   `--show-preview`: Use *with* `--dry-run`. Prints a detailed summary of proposed changes to the console, grouped by bank.
*   `--config <path/to/config.json>`: Specify a custom path for the configuration file.
*   `--log-level <LEVEL>`: Override the log level specified in `config.json` (DEBUG, INFO, WARNING, ERROR).
*   `--input <path>`: Override the input folder path from `config.json`.
*   `--output <path>`: Override the output folder path from `config.json`.
*   `--process-duplicates`: Force the script to process all files, even if duplicates are detected.
*   `--checklist-dir <path>`: Specify a different directory to save the checklist CSV files.

**Example Preview Command:**

```bash
python main.py --dry-run --show-preview
```

**Example Processing Command:**

```bash
python main.py
```
*(After verifying the preview looks correct)*

## Project Structure

*   `main.py`: Main script entry point, orchestrates the process.
*   `pdf_processor.py`: Handles PDF text extraction and bank identification.
*   `bank_strategies.py`: Defines the base `BankStrategy` class and specific strategies for each bank.
*   `file_manager.py`: Manages file renaming, moving, and checklist generation.
*   `config_manager.py`: Loads and manages settings from `config.json`.
*   `statement_info.py`: Defines the `StatementInfo` data class.
*   `utils.py`: Contains utility functions like logging setup, argument parsing, PDF verification, and error recovery stubs.
*   `requirements.txt`: Lists Python dependencies.
*   `config.json`: Configuration file (created on first run if missing).
*   `README.md`: This file.
*   `logs/`: Directory where log files are stored (created automatically).
*   `checklists/`: Directory where checklist CSV files are stored (created automatically).

*(Note: `Arctaris rename_statements.py` is an older, monolithic version and should likely be removed or archived to avoid confusion.)* 