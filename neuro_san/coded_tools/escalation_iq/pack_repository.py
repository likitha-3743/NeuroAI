import csv
import json
import os
from typing import Any
from typing import Dict
from typing import List

from neuro_san.coded_tools.escalation_iq.arg_reader import ArgReader


class PackRepository:
    """
    Loads domain packs. A pack is a folder under domain_packs/ holding config.json (taxonomy, SLAs,
    escalation rules, playbook) and history.csv (past cases). Adding a folder adds a new domain.
    Files are cached after the first read, so restart the server after editing a pack.
    """

    PACKS_DIR_ENV: str = "ESCALATION_IQ_PACKS_DIR"
    CONFIG_FILE: str = "config.json"
    HISTORY_FILE: str = "history.csv"
    DEFAULT_DOMAIN: str = "customer_complaints"

    CONFIG_CACHE: Dict[str, Dict[str, Any]] = {}
    HISTORY_CACHE: Dict[str, List[Dict[str, str]]] = {}

    @staticmethod
    def packs_dir() -> str:
        """
        Returns the directory that contains the domain packs.

        :return: The absolute path, honouring the ESCALATION_IQ_PACKS_DIR override.
        """
        override: str = os.environ.get(PackRepository.PACKS_DIR_ENV, "")
        if override:
            return override
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "domain_packs")

    @staticmethod
    def list_domains() -> List[str]:
        """
        Lists the available domain names.

        :return: Sorted folder names that contain a config.json file.
        """
        base: str = PackRepository.packs_dir()
        domains: List[str] = []
        if not os.path.isdir(base):
            return domains
        entry: str
        # Keep only folders that hold a pack configuration
        for entry in sorted(os.listdir(base)):
            if os.path.isfile(os.path.join(base, entry, PackRepository.CONFIG_FILE)):
                domains.append(entry)
        return domains

    @staticmethod
    def resolve_domain(value: Any) -> str:
        """
        Maps loosely worded input such as "incident" or "complaints" to a domain folder name.

        :param value: The raw domain argument.
        :return: A domain name, the default domain when nothing matches.
        """
        token: str = ArgReader.to_token(value)
        domains: List[str] = PackRepository.list_domains()
        if token in domains:
            return token
        if token:
            domain: str
            # Match on the leading letters of each word of the domain name
            for domain in domains:
                part: str
                for part in domain.split("_"):
                    if len(part) >= 4 and part[:5] in token:
                        return domain
        return PackRepository.DEFAULT_DOMAIN

    @staticmethod
    def load_config(domain: str) -> Dict[str, Any]:
        """
        Reads and caches a pack's config.json.

        :param domain: The domain folder name.
        :return: The parsed configuration dictionary.
        :raises OSError: When the file cannot be read.
        :raises ValueError: When the file is not valid JSON.
        """
        cached: Dict[str, Any] = PackRepository.CONFIG_CACHE.get(domain, {})
        if cached:
            return cached
        path: str = os.path.join(PackRepository.packs_dir(), domain, PackRepository.CONFIG_FILE)
        with open(path, "r", encoding="utf-8") as handle:
            config: Dict[str, Any] = json.load(handle)
        PackRepository.CONFIG_CACHE[domain] = config
        return config

    @staticmethod
    def load_history(domain: str) -> List[Dict[str, str]]:
        """
        Reads and caches a pack's history.csv.

        :param domain: The domain folder name.
        :return: A list of row dictionaries.
        :raises OSError: When the file cannot be read.
        """
        cached: List[Dict[str, str]] = PackRepository.HISTORY_CACHE.get(domain, [])
        if cached:
            return cached
        path: str = os.path.join(PackRepository.packs_dir(), domain, PackRepository.HISTORY_FILE)
        rows: List[Dict[str, str]] = []
        with open(path, "r", encoding="utf-8", newline="") as handle:
            reader: csv.DictReader = csv.DictReader(handle)
            row: Dict[str, str]
            # Copy each CSV row into a plain dictionary
            for row in reader:
                rows.append(dict(row))
        PackRepository.HISTORY_CACHE[domain] = rows
        return rows
