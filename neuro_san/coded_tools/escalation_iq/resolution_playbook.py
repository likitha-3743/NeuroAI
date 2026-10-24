from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing import List

from neuro_san.interfaces.coded_tool import CodedTool
from typing_extensions import override

from neuro_san.coded_tools.escalation_iq.evidence_ledger import EvidenceLedger
from neuro_san.coded_tools.escalation_iq.pack_repository import PackRepository


class ResolutionPlaybook(CodedTool):
    """
    Ranks the pack's resolution options for the case using how each option performed on similar
    historical cases, and checks whether front-line (L1) authority is enough for the case's value.
    """

    NEUTRAL_SUCCESS: float = 0.5
    L1_BONUS: float = 0.05

    @override
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Ranks the applicable resolution options.

        :param args: Optional "note": free text, ignored by the ranking.
        :param sly_data: Provides the case and the "similar" evidence; receives the "playbook" evidence.
        :return: A text ranking with authority checks and next steps for the best option.
        """
        logger: Logger = getLogger(self.__class__.__name__)
        case: Dict[str, Any] = EvidenceLedger.get_case(sly_data)
        if not case or not case.get("category"):
            return "Error: classify the case first (priority_calculator must run before this tool)."
        try:
            config: Dict[str, Any] = PackRepository.load_config(str(case.get("domain")))
        except (OSError, ValueError) as exc:
            logger.error("Cannot load domain pack: %s", exc)
            return f"Error: cannot load domain pack: {exc}"

        similar: Dict[str, Any] = EvidenceLedger.fetch(sly_data, "similar") or {}
        stats: Dict[str, Any] = similar.get("resolution_stats", {})
        category: str = str(case.get("category"))
        value: float = float(case.get("value_at_risk", 0.0))

        options: List[Dict[str, Any]] = []
        playbook: Dict[str, Any] = config.get("playbook", {})
        name: str
        # Evaluate every playbook option that applies to the category
        for name in playbook:
            entry: Dict[str, Any] = playbook.get(name, {})
            applies_to: List[str] = list(entry.get("categories", []))
            if "all" not in applies_to and category not in applies_to:
                continue
            history: Dict[str, Any] = stats.get(name, {})
            support: int = int(history.get("support", 0))
            success: float = float(history.get("success", self.NEUTRAL_SUCCESS)) if support else self.NEUTRAL_SUCCESS
            within_l1: bool = entry.get("authority_level") == "L1" and value <= float(entry.get("max_value", 0))
            rank_score: float = success + (self.L1_BONUS if within_l1 else 0.0)
            options.append({
                "name": name, "description": entry.get("description"), "authority_level": entry.get("authority_level"),
                "max_value": entry.get("max_value"), "within_l1_authority": within_l1,
                "value_within_limit": value <= float(entry.get("max_value", 0)),
                "historical_success": round(success, 2), "support": support, "rank_score": rank_score,
                "steps": entry.get("steps", []),
            })
        if not options:
            return "No playbook option applies to this category; treat it as a novel case and escalate for guidance."
        options.sort(key=self.rank_of, reverse=True)
        best: Dict[str, Any] = options[0]

        evidence: Dict[str, Any] = {
            "ranked": options[:4], "best": best.get("name"), "best_success": best.get("historical_success"),
            "best_support": best.get("support"), "best_within_l1": best.get("within_l1_authority"),
            "best_authority_level": best.get("authority_level"),
        }
        EvidenceLedger.record(sly_data, "playbook", evidence)
        logger.info("Best resolution option: %s", best.get("name"))

        lines: List[str] = ["RESOLUTION OPTIONS (ranked by historical success on similar cases)"]
        option: Dict[str, Any]
        # One line per top option
        for option in options[:4]:
            authority: str = "within L1 authority" if option.get("within_l1_authority") else (
                f"needs {option.get('authority_level')} approval or value is above the L1 limit")
            basis: str = f"{option.get('support')} similar case(s)" if option.get("support") else "no history, neutral prior"
            lines.append(
                f"- {option.get('name')}: success {option.get('historical_success')} ({basis}); "
                f"{authority}. {option.get('description')}"
            )
        lines.append(f"BEST OPTION: {best.get('name')}. Steps: " + "; ".join(best.get("steps", [])))
        return "\n".join(lines)

    @staticmethod
    def rank_of(option: Dict[str, Any]) -> float:
        """
        Sort key for options.

        :param option: A ranked option.
        :return: The rank score.
        """
        return float(option.get("rank_score", 0.0))
