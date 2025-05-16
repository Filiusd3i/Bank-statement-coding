import os
import json
import logging
from typing import Dict, Any, Optional
import yaml

class ConfigManager:
    """Manages configuration settings for the application."""

    DEFAULT_CONFIG_STRUCTURE = {
        "base_config": {
            "input_folder": "input_statements",
            "processed_folder": "processed_statements",
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
            "pnc_special_mapping_last4": {},
            "berkshire_last4": {},
            "cambridge": {},
            "cambridge_online_statements_numbered": {},
            "bank_united_dxweb": {}
            # Add empty placeholders for bank mappings
        }
    }

    def __init__(self, config_path: str = "config.yaml", sensitive_config_path: str = "sensitive_accounts.yaml"):
        """
        Initializes the ConfigManager by loading the main config and optionally
        the sensitive accounts config.

        Args:
            config_path (str): Path to the main configuration file (e.g., config.yaml).
            sensitive_config_path (str): Path to the sensitive accounts file (e.g., sensitive_accounts.yaml).
        """
        self.config_path = config_path
        self.sensitive_config_path = sensitive_config_path
        self.config = self._load_yaml(self.config_path)
        logging.info(f"Loaded main config from {self.config_path}: {json.dumps(self.config)}")
        self.sensitive_config = self._load_yaml(self.sensitive_config_path)

        if self.config is None:
            logging.critical(f"Main configuration file '{self.config_path}' not found or could not be loaded. Exiting.")
            # In a real app, might raise an exception or exit
            self.config = {} # Initialize empty to prevent errors downstream, though critical log exists

        if self.sensitive_config is None:
            logging.warning(f"Sensitive accounts file '{self.sensitive_config_path}' not found or empty. Account matching will rely solely on mappings and regex.")
            self.sensitive_config = {'accounts': {}} # Ensure 'accounts' key exists even if file missing

        self._validate_config()

    def _load_yaml(self, file_path):
        """Safely loads a YAML file."""
        if not os.path.exists(file_path):
            logging.info(f"Configuration file not found: {file_path}")
            return None
        try:
            with open(file_path, 'r') as f:
                data = yaml.safe_load(f)
                # Handle empty file case
                return data if data is not None else {}
        except yaml.YAMLError as e:
            logging.error(f"Error parsing YAML file {file_path}: {e}", exc_info=True)
            return None
        except Exception as e:
            logging.error(f"Error reading file {file_path}: {e}", exc_info=True)
            return None

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
                yaml.dump(data_to_save, f)
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

    def get_sensitive_accounts(self, bank_key=None):
        """
        Gets the list of sensitive account details, optionally filtered by bank.

        Args:
            bank_key (str, optional): The key for the bank (e.g., 'PNC') to filter by.
                                      Case-insensitive comparison is used.

        Returns:
            list: A list of account dictionaries (e.g., [{'name': '...', 'number': '...'}]).
                  Returns an empty list if the sensitive config is not loaded,
                  the 'accounts' key is missing, or the bank_key is not found.
        """
        if not self.sensitive_config or 'accounts' not in self.sensitive_config:
            return []

        all_bank_accounts_data = self.sensitive_config['accounts']

        if bank_key:
            # Find the bank key case-insensitively
            for config_bank_key, accounts in all_bank_accounts_data.items():
                if config_bank_key.lower() == bank_key.lower():
                    # Ensure the value is a list of dictionaries
                    if isinstance(accounts, list):
                        # Basic validation of list items
                        valid_accounts = [acc for acc in accounts if isinstance(acc, dict) and 'name' in acc and 'number' in acc]
                        if len(valid_accounts) != len(accounts):
                             logging.warning(f"Some account entries for bank '{config_bank_key}' in '{self.sensitive_config_path}' are malformed.")
                        return valid_accounts
                    else:
                        logging.warning(f"Expected a list of accounts for bank '{config_bank_key}' in '{self.sensitive_config_path}', but found type {type(accounts)}.")
                        return []
            return [] # Bank key not found
        else:
            # Return all accounts flattened (less common use case)
            all_flat = []
            for bank_accounts in all_bank_accounts_data.values():
                if isinstance(bank_accounts, list):
                    valid_accounts = [acc for acc in bank_accounts if isinstance(acc, dict) and 'name' in acc and 'number' in acc]
                    all_flat.extend(valid_accounts)
            return all_flat 