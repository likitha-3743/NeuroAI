import asyncio
import json
import os
import re
from datetime import datetime
from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing import List

from neuro_san.interfaces.coded_tool import CodedTool
from typing_extensions import override

from neuro_san.coded_tools.escalation_iq.evidence_ledger import EvidenceLedger


class CaseReportWriter(CodedTool):
    """
    Saves the Resolution Summary Report as markdown (with the full evidence appendix) and appends a
    one-line decision record to an audit log in JSON Lines format.
    """

    REPORT_DIR_ENV: str = "ESCALATION_IQ_REPORT_DIR"
    DEFAULT_REPORT_DIR: str = "reports"
    AUDIT_FILE: str = "escalation_audit.jsonl"

    @override
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Writes the report and the audit entry.

        :param args: "title" and "body_markdown", the chair's narrative.
        :param sly_data: Provides the case and all evidence for the appendix and audit record.
        :return: A text message with the saved paths, or an error message.
        """
        logger: Logger = getLogger(self.__class__.__name__)
        case: Dict[str, Any] = EvidenceLedger.get_case(sly_data)
        decision: Dict[str, Any] = EvidenceLedger.fetch(sly_data, "escalation") or {}
        if not decision:
            return "Cannot write the report yet: run escalation_scorer first."
        body: str = str(args.get("body_markdown") or "").strip()
        if not body:
            return "Cannot write an empty report. Provide body_markdown."
        title: str = str(args.get("title") or f"Case {case.get('case_id')} Resolution Report").strip()

        banner: str = (
            f"**Case {case.get('case_id')}** | Domain: {case.get('domain')} | Priority: {case.get('priority')} | "
            f"**Decision: {decision.get('decision')}** | Score: {decision.get('score')}/100 | "
            f"Confidence: {decision.get('confidence')}"
        )
        parts: List[str] = [f"# {title}", "", banner, "", body, "", "## Evidence Appendix (deterministic tool outputs)", ""]
        ledger: Dict[str, Any] = EvidenceLedger.get_ledger(sly_data)
        key: str
        # Render each evidence entry as its own JSON block
        for key in ledger:
            parts.extend([f"### {key}", "", "```json", json.dumps(ledger.get(key), indent=2, default=str), "```", ""])
        content: str = "\n".join(parts)

        directory: str = os.environ.get(self.REPORT_DIR_ENV, self.DEFAULT_REPORT_DIR)
        stamp: str = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug: str = re.sub(r"[^a-z0-9]+", "-", str(case.get("case_id", "case")).lower()).strip("-") or "case"
        report_path: str = os.path.join(directory, f"{slug}-{stamp}.md")
        audit_path: str = os.path.join(directory, self.AUDIT_FILE)
        audit_entry: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(timespec="seconds"), "case_id": case.get("case_id"),
            "domain": case.get("domain"), "category": case.get("category"), "priority": case.get("priority"),
            "decision": decision.get("decision"), "score": decision.get("score"),
            "confidence": decision.get("confidence"), "target_team": decision.get("target_team"),
            "systemic": decision.get("systemic"), "report": report_path,
        }
        try:
            await asyncio.to_thread(self.write_files, directory, report_path, content, audit_path, audit_entry)
        except OSError as exc:
            logger.error("Could not write report to %s: %s", report_path, exc)
            return f"Error: could not write report to {report_path}: {exc}"
        logger.info("Report written to %s", report_path)
        return f"Report saved to {report_path}. Audit record appended to {audit_path}."

    @staticmethod
    def write_files(directory: str, report_path: str, content: str, audit_path: str,
                    audit_entry: Dict[str, Any]) -> None:
        """
        Creates the directory, writes the report and appends the audit record.

        :param directory: The target directory.
        :param report_path: The full report file path.
        :param content: The markdown text.
        :param audit_path: The audit log path.
        :param audit_entry: The JSON-friendly audit record.
        """
        os.makedirs(directory, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        with open(audit_path, "a", encoding="utf-8") as audit:
            audit.write(json.dumps(audit_entry, default=str) + "\n")
