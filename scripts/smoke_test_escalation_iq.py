import asyncio
import os
import sys
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

from neuro_san.coded_tools.escalation_iq.case_intake import CaseIntake
from neuro_san.coded_tools.escalation_iq.case_report_writer import CaseReportWriter
from neuro_san.coded_tools.escalation_iq.escalation_scorer import EscalationScorer
from neuro_san.coded_tools.escalation_iq.policy_checker import PolicyChecker
from neuro_san.coded_tools.escalation_iq.priority_calculator import PriorityCalculator
from neuro_san.coded_tools.escalation_iq.resolution_playbook import ResolutionPlaybook
from neuro_san.coded_tools.escalation_iq.similar_case_search import SimilarCaseSearch
from neuro_san.coded_tools.escalation_iq.taxonomy_lookup import TaxonomyLookup


class SmokeTestEscalationIq:
    """
    Runs the deterministic EscalateIQ tool chain WITHOUT any LLM call for one scenario per domain
    pack and then re-runs the first scenario with changed facts (what-if). Use it to verify your
    install and the domain packs before spending any API quota.

    Usage from the repo root:
        python scripts/smoke_test_escalation_iq.py [show]
    Pass "show" to print every tool output; otherwise only the decisions are printed.
    """

    SCENARIOS: List[Tuple[str, Dict[str, Any], Dict[str, str]]] = [
        ("customer_complaints", {
            "domain": "customer_complaints",
            "description": "Customer cannot log in to the mobile banking app since the latest update and the OTP is not arriving",
            "stakeholder_tier": "key", "value_at_risk": "0", "hours_open": "20", "prior_contacts": "3",
            "frustration_level": "high"},
         {"category": "service_outage", "severity": "high"}),
        ("it_incidents", {
            "domain": "it_incidents",
            "description": "Checkout API is slow and timing out since the new deployment, users are abandoning carts",
            "stakeholder_tier": "strategic", "value_at_risk": "30000", "hours_open": "2", "prior_contacts": "1",
            "frustration_level": "high"},
         {"category": "performance_degradation", "severity": "high"}),
        ("project_delivery", {
            "domain": "project_delivery",
            "description": "Vendor still has not delivered the payments API and it is blocking the integration milestone",
            "stakeholder_tier": "strategic", "value_at_risk": "900000", "hours_open": "30", "prior_contacts": "2",
            "frustration_level": "medium"},
         {"category": "vendor_delay", "severity": "high"}),
        ("customer_complaints", {
            "domain": "customer_complaints",
            "description": "Customer disputes a 40 dollar annual card fee that was promised to be free",
            "stakeholder_tier": "standard", "value_at_risk": "40", "hours_open": "3", "prior_contacts": "0",
            "frustration_level": "low"},
         {"category": "fees_and_charges", "severity": "low"}),
        ("customer_complaints", {
            "domain": "customer_complaints",
            "description": "Interest on the loan statement does not match the agreed rate and the customer wants it corrected",
            "stakeholder_tier": "key", "value_at_risk": "1500", "hours_open": "20", "prior_contacts": "2",
            "frustration_level": "high"},
         {"category": "billing_error", "severity": "medium"}),
    ]

    async def run_case(self, label: str, intake: Dict[str, Any], classification: Dict[str, str],
                       sly_data: Dict[str, Any], verbose: bool) -> Dict[str, Any]:
        """
        Runs the full tool chain for one scenario.

        :param label: The scenario name.
        :param intake: The case_intake arguments.
        :param classification: The category and severity the classifier agent would choose.
        :param sly_data: The shared sly_data dictionary.
        :param verbose: True to print every tool output.
        :return: The escalation evidence dictionary.
        """
        steps: List[Tuple[str, Any, Dict[str, Any]]] = [
            ("case_intake", CaseIntake(), intake),
            ("taxonomy_lookup", TaxonomyLookup(), {}),
            ("priority_calculator", PriorityCalculator(), classification),
            ("similar_case_search", SimilarCaseSearch(), {}),
            ("resolution_playbook", ResolutionPlaybook(), {}),
            ("policy_checker", PolicyChecker(), {}),
            ("escalation_scorer", EscalationScorer(), {}),
        ]
        outputs: Dict[str, str] = {}
        name: str
        tool: Any
        tool_args: Dict[str, Any]
        # Run each tool in order against the shared sly_data
        for name, tool, tool_args in steps:
            result: str = str(await tool.async_invoke(tool_args, sly_data))
            outputs[name] = result
            if verbose:
                print(f"\n----- {name} -----\n{result}")
            if result.startswith("Error") or "BLOCKED" in result:
                raise RuntimeError(f"{label}: {name} failed: {result}")
        report: str = await CaseReportWriter().async_invoke(
            {"title": f"Smoke test {label}", "body_markdown": "## Summary\nGenerated by the smoke test."}, sly_data)
        if verbose:
            print(f"\n----- case_report_writer -----\n{report}")
        decision: Dict[str, Any] = sly_data.get("case_evidence", {}).get("escalation", {})
        print(f"[{label}] priority {decision.get('priority')} | {decision.get('decision')} | "
              f"score {decision.get('score')} | target {decision.get('target_team')} | "
              f"confidence {decision.get('confidence')} | systemic {decision.get('systemic')}")
        return decision

    async def run(self, verbose: bool) -> int:
        """
        Runs every scenario and a what-if re-run.

        :param verbose: True to print every tool output.
        :return: Process exit code, 0 on success.
        """
        os.environ["ESCALATION_IQ_REPORT_DIR"] = os.environ.get("ESCALATION_IQ_REPORT_DIR", "reports")
        scenario: Tuple[str, Dict[str, Any], Dict[str, str]]
        # One independent request per scenario
        for scenario in self.SCENARIOS:
            await self.run_case(scenario[0], scenario[1], scenario[2], {}, verbose)

        print("\n===== WHAT-IF: same session, the customer now threatens legal action =====")
        shared: Dict[str, Any] = {}
        first: Tuple[str, Dict[str, Any], Dict[str, str]] = self.SCENARIOS[0]
        await self.run_case(first[0], first[1], first[2], shared, False)
        changed: Dict[str, Any] = dict(first[1])
        changed["legal_or_media_threat"] = "true"
        await self.run_case(first[0] + " (what-if)", changed, first[2], shared, False)
        print(shared.get("case_evidence", {}).get("escalation", {}).get("pivotal_factors"))
        print("\nSMOKE TEST PASSED")
        return 0


if __name__ == "__main__":
    SHOW: bool = len(sys.argv) > 1 and sys.argv[1] == "show"
    sys.exit(asyncio.run(SmokeTestEscalationIq().run(SHOW)))
