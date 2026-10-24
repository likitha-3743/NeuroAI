from typing import Any
from typing import Dict
from typing import Optional


class EvidenceLedger:
    """
    Bulletin board over sly_data. The registered case lives under "case_facts" and every
    deterministic tool publishes its result in the "case_evidence" ledger, so numbers reach the
    scorer and the report without passing through an LLM's chat stream.
    """

    LEDGER_KEY: str = "case_evidence"
    CASE_KEY: str = "case_facts"
    PREVIOUS_KEY: str = "previous_escalation"

    @staticmethod
    def start_new_case(sly_data: Dict[str, Any], case: Dict[str, Any]) -> None:
        """
        Registers a case, keeping the previous decision (if any) so a what-if re-run can be compared.

        :param sly_data: The private sly_data dictionary shared by all tools of the request.
        :param case: The normalized case facts.
        """
        old_ledger: Dict[str, Any] = sly_data.get(EvidenceLedger.LEDGER_KEY) or {}
        previous: Optional[Dict[str, Any]] = old_ledger.get("escalation")
        if previous is not None:
            sly_data[EvidenceLedger.PREVIOUS_KEY] = previous
        sly_data[EvidenceLedger.LEDGER_KEY] = {}
        sly_data[EvidenceLedger.CASE_KEY] = case

    @staticmethod
    def get_case(sly_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Returns the registered case facts.

        :param sly_data: The private sly_data dictionary shared by all tools of the request.
        :return: A copy of the case dictionary, empty when no case is registered.
        """
        case: Optional[Dict[str, Any]] = sly_data.get(EvidenceLedger.CASE_KEY)
        if case is None:
            return {}
        return dict(case)

    @staticmethod
    def update_case(sly_data: Dict[str, Any], changes: Dict[str, Any]) -> None:
        """
        Merges derived facts (category, priority, recurrence...) into the registered case.

        :param sly_data: The private sly_data dictionary shared by all tools of the request.
        :param changes: The facts to add or overwrite.
        """
        case: Optional[Dict[str, Any]] = sly_data.get(EvidenceLedger.CASE_KEY)
        if case is None:
            case = {}
            sly_data[EvidenceLedger.CASE_KEY] = case
        case.update(changes)

    @staticmethod
    def record(sly_data: Dict[str, Any], key: str, value: Any) -> None:
        """
        Publishes one piece of evidence.

        :param sly_data: The private sly_data dictionary shared by all tools of the request.
        :param key: The evidence name, for example "similar" or "policy".
        :param value: The JSON-friendly evidence value.
        """
        ledger: Optional[Dict[str, Any]] = sly_data.get(EvidenceLedger.LEDGER_KEY)
        if ledger is None:
            ledger = {}
            sly_data[EvidenceLedger.LEDGER_KEY] = ledger
        ledger[key] = value

    @staticmethod
    def fetch(sly_data: Dict[str, Any], key: str) -> Any:
        """
        Reads one piece of evidence.

        :param sly_data: The private sly_data dictionary shared by all tools of the request.
        :param key: The evidence name.
        :return: The evidence value, or None when it has not been published yet.
        """
        ledger: Dict[str, Any] = sly_data.get(EvidenceLedger.LEDGER_KEY) or {}
        return ledger.get(key)

    @staticmethod
    def get_ledger(sly_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Returns a shallow copy of the whole ledger.

        :param sly_data: The private sly_data dictionary shared by all tools of the request.
        :return: A dictionary of all evidence published so far.
        """
        ledger: Dict[str, Any] = sly_data.get(EvidenceLedger.LEDGER_KEY) or {}
        return dict(ledger)
