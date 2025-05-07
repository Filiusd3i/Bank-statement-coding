from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class StatementInfo:
    """Stores extracted information about a bank statement."""
    original_filename: Optional[str] = None
    bank_type: Optional[str] = None  # e.g., 'PNC', 'Cambridge', 'Unlabeled'
    account_name: Optional[str] = None
    account_number: Optional[str] = None # Store full number if available, otherwise masked
    date: Optional[datetime] = None
    match_status: Optional[str] = None # NEW: Tracks confidence/method ('Success!', 'Fallback', etc.)

    # Optional: Add fields for start/end date if needed
    # start_date: Optional[datetime] = None
    # end_date: Optional[datetime] = None

    def is_complete(self) -> bool:
        """Check if essential information has been extracted."""
        return bool(self.bank_type != "Unlabeled" and self.account_name and self.date)

    def __repr__(self) -> str:
        """Provide a helpful representation for debugging."""
        return (
            f"StatementInfo(bank='{self.bank_type}', "
            f"name='{self.account_name}', "
            f"acc_num='{self.account_number}', "
            f"date='{self.date.strftime('%Y-%m-%d') if self.date else 'None'}', "
            f"orig_file='{self.original_filename}')"
        ) 