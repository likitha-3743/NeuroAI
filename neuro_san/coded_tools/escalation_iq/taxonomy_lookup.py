from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing import List

from neuro_san.interfaces.coded_tool import CodedTool
from typing_extensions import override

from neuro_san.coded_tools.escalation_iq.evidence_ledger import EvidenceLedger
from neuro_san.coded_tools.escalation_iq.pack_repository import PackRepository


class TaxonomyLookup(CodedTool):
    """
    Returns the registered domain's categories, business areas, owning teams and severity
    definitions so the classifier agent labels the case with the pack's own vocabulary.
    """

    @override
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Lists the taxonomy of the case's domain.

        :param args: Optional "focus": free text hint, ignored by the lookup.
        :param sly_data: Provides the registered case.
        :return: The category and severity reference text.
        """
        logger: Logger = getLogger(self.__class__.__name__)
        case: Dict[str, Any] = EvidenceLedger.get_case(sly_data)
        if not case:
            return "Error: no case registered. Call case_intake first."
        try:
            config: Dict[str, Any] = PackRepository.load_config(str(case.get("domain")))
        except (OSError, ValueError) as exc:
            logger.error("Cannot load domain pack: %s", exc)
            return f"Error: cannot load domain pack: {exc}"

        lines: List[str] = [f"TAXONOMY for {config.get('display_name')}", "Categories:"]
        categories: Dict[str, Any] = config.get("taxonomy", {}).get("categories", {})
        name: str
        # One line per category with its owning area, team and hint keywords
        for name in categories:
            entry: Dict[str, Any] = categories.get(name, {})
            regulated: str = " [regulated]" if entry.get("regulated") else ""
            lines.append(
                f"- {name}{regulated} | area: {entry.get('business_area')} | team: {entry.get('team')} | "
                f"keywords: {', '.join(entry.get('keywords', []))} | severity hint: {entry.get('guidance')}"
            )
        lines.append("Severity levels:")
        level: str
        # One line per severity level definition
        for level in config.get("severity_levels", {}):
            lines.append(f"- {level}: {config.get('severity_levels', {}).get(level)}")
        return "\n".join(lines)
