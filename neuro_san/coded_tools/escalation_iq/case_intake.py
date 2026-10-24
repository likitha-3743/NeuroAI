import hashlib
from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing import List

from neuro_san.interfaces.coded_tool import CodedTool
from typing_extensions import override

from neuro_san.coded_tools.escalation_iq.arg_reader import ArgReader
from neuro_san.coded_tools.escalation_iq.evidence_ledger import EvidenceLedger
from neuro_san.coded_tools.escalation_iq.pack_repository import PackRepository


class CaseIntake(CodedTool):
    """
    Registers a case from any domain: picks the domain pack, normalizes the facts, notes which
    facts were assumed, and starts a fresh evidence ledger (keeping the previous decision so a
    what-if re-run can be compared).
    """

    TIERS: List[str] = ["standard", "key", "strategic"]
    FRUSTRATION: List[str] = ["low", "medium", "high"]

    @override
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Builds and stores the normalized case.

        :param args: domain, description (required), title, stakeholder_tier, value_at_risk, hours_open,
                     prior_contacts, regulated, legal_or_media_threat, safety_or_data_risk, frustration_level.
        :param sly_data: Receives "case_facts" and a fresh evidence ledger.
        :return: A text summary of the registered case and the assumed facts.
        """
        logger: Logger = getLogger(self.__class__.__name__)
        domain: str = PackRepository.resolve_domain(args.get("domain"))
        try:
            config: Dict[str, Any] = PackRepository.load_config(domain)
        except (OSError, ValueError) as exc:
            logger.error("Cannot load domain pack %s: %s", domain, exc)
            return f"Error: cannot load domain pack '{domain}': {exc}"

        description: str = str(args.get("description") or "").strip()
        if not description:
            return "Error: description is required. Ask the client to describe the case."

        assumed: List[str] = []
        tier: str = ArgReader.to_choice(args.get("stakeholder_tier"), self.TIERS, "standard")
        if ArgReader.to_token(args.get("stakeholder_tier")) != tier:
            assumed.append("stakeholder_tier")
        frustration: str = ArgReader.to_choice(args.get("frustration_level"), self.FRUSTRATION, "medium")
        if ArgReader.to_token(args.get("frustration_level")) != frustration:
            assumed.append("frustration_level")
        value: float = ArgReader.to_float(args.get("value_at_risk"), 0.0)
        if args.get("value_at_risk") is None:
            assumed.append("value_at_risk")
        hours_open: float = ArgReader.to_float(args.get("hours_open"), 0.0)
        if args.get("hours_open") is None:
            assumed.append("hours_open")
        prior: int = ArgReader.to_int(args.get("prior_contacts"), 0)
        if args.get("prior_contacts") is None:
            assumed.append("prior_contacts")

        title: str = str(args.get("title") or description[:60]).strip()
        digest: str = hashlib.sha1(description.encode("utf-8")).hexdigest()[:6].upper()
        case: Dict[str, Any] = {
            "case_id": f"CASE-{digest}",
            "domain": domain,
            "title": title,
            "description": description,
            "stakeholder_tier": tier,
            "value_at_risk": value,
            "hours_open": hours_open,
            "prior_contacts": prior,
            "regulated": ArgReader.to_bool(args.get("regulated"), False),
            "legal_or_media_threat": ArgReader.to_bool(args.get("legal_or_media_threat"), False),
            "safety_or_data_risk": ArgReader.to_bool(args.get("safety_or_data_risk"), False),
            "frustration_level": frustration,
            "repeat_similar_count": 0,
            "assumed_fields": assumed,
        }
        EvidenceLedger.start_new_case(sly_data, case)
        EvidenceLedger.record(sly_data, "intake", case)
        logger.info("Registered %s in domain %s", case.get("case_id"), domain)

        categories: List[str] = list(config.get("taxonomy", {}).get("categories", {}).keys())
        assumed_text: str = ", ".join(assumed) if assumed else "none"
        return (
            f"CASE REGISTERED: {case.get('case_id')}\n"
            f"Domain: {config.get('display_name')} (noun: {config.get('case_noun')})\n"
            f"Title: {title}\n"
            f"Stakeholder tier: {tier}, value at risk: {value:,.0f}, hours open: {hours_open}, "
            f"prior contacts: {prior}\n"
            f"Regulated: {case.get('regulated')}, legal or media threat: {case.get('legal_or_media_threat')}, "
            f"safety or data risk: {case.get('safety_or_data_risk')}, frustration: {frustration}\n"
            f"Available categories: {', '.join(categories)}\n"
            f"Assumed (not provided): {assumed_text}"
        )
