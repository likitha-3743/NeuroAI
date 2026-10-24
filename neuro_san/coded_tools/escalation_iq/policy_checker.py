from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing import List

from neuro_san.interfaces.coded_tool import CodedTool
from typing_extensions import override

from neuro_san.coded_tools.escalation_iq.evidence_ledger import EvidenceLedger
from neuro_san.coded_tools.escalation_iq.pack_repository import PackRepository
from neuro_san.coded_tools.escalation_iq.rule_evaluator import RuleEvaluator


class PolicyChecker(CodedTool):
    """
    Evaluates the pack's escalation policy rules against the case facts. Mandatory rules force an
    escalation; other rules add weighted evidence to the escalation score.
    """

    @override
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Finds the policy rules that trigger for the case.

        :param args: Optional "note": free text, ignored by the evaluation.
        :param sly_data: Provides the classified case; receives the "policy" evidence.
        :return: A text list of triggered rules with their targets.
        """
        logger: Logger = getLogger(self.__class__.__name__)
        case: Dict[str, Any] = EvidenceLedger.get_case(sly_data)
        if not case or not case.get("priority"):
            return "Error: classify the case first (priority_calculator) and run similar_case_search."
        try:
            config: Dict[str, Any] = PackRepository.load_config(str(case.get("domain")))
        except (OSError, ValueError) as exc:
            logger.error("Cannot load domain pack: %s", exc)
            return f"Error: cannot load domain pack: {exc}"

        triggered: List[Dict[str, Any]] = []
        not_triggered: List[str] = []
        rule: Dict[str, Any]
        # Test each policy rule against the case facts
        for rule in config.get("rules", []):
            if RuleEvaluator.evaluate_rule(rule, case):
                triggered.append({
                    "id": rule.get("id"), "description": rule.get("description"),
                    "escalate_to": rule.get("escalate_to"), "weight": int(rule.get("weight", 0)),
                    "mandatory": bool(rule.get("mandatory", False)), "level": rule.get("level", "L2"),
                    "condition": RuleEvaluator.describe_conditions(rule),
                })
            else:
                not_triggered.append(str(rule.get("id")))
        triggered.sort(key=self.weight_of, reverse=True)

        mandatory_count: int = 0
        total_weight: int = 0
        item: Dict[str, Any]
        # Sum the weights and count mandatory rules
        for item in triggered:
            total_weight = total_weight + int(item.get("weight", 0))
            if item.get("mandatory"):
                mandatory_count = mandatory_count + 1
        evidence: Dict[str, Any] = {
            "triggered": triggered, "mandatory_count": mandatory_count, "total_weight": total_weight,
            "not_triggered": not_triggered,
        }
        EvidenceLedger.record(sly_data, "policy", evidence)
        logger.info("%s rules triggered, %s mandatory", len(triggered), mandatory_count)

        lines: List[str] = [f"POLICY CHECK: {len(triggered)} rule(s) triggered, {mandatory_count} mandatory"]
        # One line per triggered rule
        for item in triggered:
            flag: str = "MANDATORY" if item.get("mandatory") else "advisory"
            lines.append(
                f"- {item.get('id')} [{flag}, weight {item.get('weight')}, {item.get('level')}] "
                f"{item.get('description')} -> {item.get('escalate_to')} (when {item.get('condition')})"
            )
        if not triggered:
            lines.append("No policy rule requires or suggests escalation.")
        return "\n".join(lines)

    @staticmethod
    def weight_of(item: Dict[str, Any]) -> int:
        """
        Sort key for triggered rules.

        :param item: A triggered rule.
        :return: Its weight, mandatory rules sorting first.
        """
        return int(item.get("weight", 0)) + (1000 if item.get("mandatory") else 0)
