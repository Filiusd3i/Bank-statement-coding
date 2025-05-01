from datetime import datetime
from typing import Optional

class StatementInfo:
    """Class to hold extracted statement information."""
    def __init__(self):
        self.bank_type: str = "Unlabeled" # Default to Unlabeled
        self.account_name: Optional[str] = None
        self.account_number: Optional[str] = None
        self.date: Optional[datetime] = None
        self.original_filename: Optional[str] = None
        self.fund_name: Optional[str] = None # Keep for potential use by strategies

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