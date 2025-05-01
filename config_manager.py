import os
import json
import logging
from typing import Dict, Any, Optional

class ConfigManager:
    """Manages configuration settings for the application."""

    DEFAULT_CONFIG_STRUCTURE = {
        "base_config": {
            "input_folder": "C:\\Users\\Christian\\OneDrive - Arctaris Michigan Partners, LLC\\Desktop\\Bank Automation\\input_statements",
            "processed_folder": "C:\\Users\\Christian\\OneDrive - Arctaris Michigan Partners, LLC\\Desktop\\Bank Automation\\processed_statements",
            "log_level": "INFO",
            "backup_files": True,
            "max_workers": 4,
            "batch_size": 20,
            "file_verification": True,
            "auto_recovery": True,
            "check_duplicates": True,
            "delete_originals": False,
            "patterns": {
                "period_marker": "FOR THE PERIOD",
                "stop_markers": ["STE"],
                "skip_starters": [
                    "Number", "Tax ID", "For Client",
                    "Visit", "For 24-hour", "PNC Bank"
                ]
            }
        },
        "account_mappings": {
            "pnc": {},
            "pnc_arc_impact_last4": {},
            "berkshire_last4": {},
            "cambridge": {},
            "cambridge_online_statements_numbered": {},
            "bank_united_dxweb": {}
            # Add empty placeholders for bank mappings
        }
    }

    def __init__(self, config_path: str = "config.json"):
        """Initialize with path to config file."""
        self.config_path = config_path
        self.config = self._load_config()
        self._validate_config()

    def _load_config(self) -> Dict:
        """Load configuration from file or create with defaults."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    loaded_config = json.load(f)
                # Validate and merge with defaults for missing keys/sections
                return self._deep_merge(self.DEFAULT_CONFIG_STRUCTURE.copy(), loaded_config)
            except json.JSONDecodeError as e:
                logging.error(f"Error decoding JSON from {self.config_path}: {e}. Using default structure.")
                return self.DEFAULT_CONFIG_STRUCTURE.copy()
            except Exception as e:
                logging.error(f"Unexpected error loading config: {e}. Using default structure.")
                return self.DEFAULT_CONFIG_STRUCTURE.copy()
        else:
            logging.warning(f"Config file not found at {self.config_path}. Creating with default structure.")
            # Create default config file
            self.save_config(self.DEFAULT_CONFIG_STRUCTURE) # Save the default structure immediately
            return self.DEFAULT_CONFIG_STRUCTURE.copy()

    def _validate_config(self):
        """Ensure the loaded config has the expected structure."""
        # Ensure top-level keys exist
        if "base_config" not in self.config:
            logging.warning("Missing 'base_config' section in config. Restoring from default.")
            self.config["base_config"] = self.DEFAULT_CONFIG_STRUCTURE["base_config"].copy()
        if "account_mappings" not in self.config:
            logging.warning("Missing 'account_mappings' section in config. Restoring from default.")
            self.config["account_mappings"] = self.DEFAULT_CONFIG_STRUCTURE["account_mappings"].copy()

        # You could add more specific validation here if needed

    def _deep_merge(self, source: Dict, destination: Dict) -> Dict:
        """Deep merge two dictionaries, ensuring destination structure."""
        for key, value in source.items():
            if key not in destination:
                destination[key] = value # Add missing keys from source
            elif isinstance(value, dict) and isinstance(destination.get(key), dict):
                # Recursively merge dictionaries
                self._deep_merge(value, destination[key])
            # else: destination value takes precedence if types differ or not dict
        return destination

    def save_config(self, config_data: Optional[Dict] = None):
        """Save the provided configuration data or the current config to file."""
        data_to_save = config_data if config_data is not None else self.config
        try:
            with open(self.config_path, 'w') as f:
                json.dump(data_to_save, f, indent=4, sort_keys=True)
            if config_data is None: # Only update internal state if saving current config
                 self.config = data_to_save
        except Exception as e:
            logging.error(f"Error saving config to {self.config_path}: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value from the 'base_config' section.
        Uses dot notation for nested keys (e.g., 'patterns.period_marker').
        """
        try:
            keys = key.split('.')
            result = self.config.get("base_config", {}) # Start search within base_config
            for k in keys:
                if not isinstance(result, dict): # Check if intermediate key exists and is a dict
                    return default
                result = result[k] # This will raise KeyError if k is not found
            return result
        except (KeyError, TypeError):
            # Log a warning if a key is accessed but not found? Optional.
            # logging.debug(f"Config key '{key}' not found, returning default.")
            return default

    def get_account_mappings(self, bank_key: str) -> Dict:
        """Get the account mapping dictionary for a specific bank key."""
        return self.config.get("account_mappings", {}).get(bank_key, {})

    def get_all_mappings(self) -> Dict:
        """Get the entire account_mappings dictionary."""
        return self.config.get("account_mappings", {}) 