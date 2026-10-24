# EscalateIQ run guide

Your environment is already set up, so this only covers adding EscalateIQ and running the demo.

## 1. Copy the files into your repo

Paths are relative to the repo root (`neuro-san-hackathon`).

| Delivered path | Goes to |
| --- | --- |
| `neuro_san/registries/escalation_iq.hocon` | `neuro_san/registries/escalation_iq.hocon` |
| `neuro_san/registries/manifest.hocon` | `neuro_san/registries/manifest.hocon` (replaces the file, see step 2) |
| `neuro_san/coded_tools/escalation_iq/` (whole folder, including `domain_packs/`) | `neuro_san/coded_tools/escalation_iq/` |
| `scripts/smoke_test_escalation_iq.py` | `scripts/smoke_test_escalation_iq.py` |
| `docs/escalation_iq/` | `docs/escalation_iq/` |

The coded tools folder name must equal the hocon file name (`escalation_iq`). Both MigrationBoard and EscalateIQ can
live in the same repo.

## 2. Manifest

Either replace your `manifest.hocon` with the delivered one, or just add these lines to yours:

```hocon
"escalation_iq.hocon": true,
```

(The delivered file also lists `migration_board.hocon`. Delete that line if you did not copy that network.)
Add `reports/` to `.gitignore`.

## 3. Environment (same terminal as the demo)

PowerShell:

```powershell
$env:GOOGLE_API_KEY = "your-gemini-key"
$env:AGENT_TOOL_PATH = "./neuro_san/coded_tools"
$env:PYTHONPATH = "."
```

macOS / Linux:

```bash
export GOOGLE_API_KEY="your-gemini-key"
export AGENT_TOOL_PATH="./neuro_san/coded_tools"
export PYTHONPATH="."
```

Never commit the key. If Gemini is not installed: `pip install "langchain-google-genai>=4.1.2,<5.0"`.

## 4. Verify before using any API quota

```bash
python -m neuro_san.client.hocon_validator_cli neuro_san/registries/escalation_iq.hocon --verbose
python scripts/smoke_test_escalation_iq.py
python scripts/smoke_test_escalation_iq.py show
```

Expected smoke test decisions (deterministic):

| Scenario | Priority | Decision | Target |
| --- | --- | --- | --- |
| Mobile app login failing (complaint) | P2 | ESCALATE, score about 71 | Problem Management |
| Checkout API slow (IT incident) | P1 | URGENT_ESCALATION, about 84 | Incident Commander |
| Vendor API late (project) | P2 | ESCALATE, about 68 | PMO Risk Board |
| Disputed 40 dollar fee | P4 | RESOLVE_AT_L1, 0 | Front line |
| Interest rate mismatch | P2 | RESOLVE_AT_L1_WITH_MONITORING, about 49 | Front line |

The last lines show the what-if: adding a legal threat flips the first case to URGENT_ESCALATION to
Compliance and Legal. The run ends with `SMOKE TEST PASSED` and writes reports under `reports/`.

## 5. Run

Library mode:

```bash
python -m neuro_san.client.agent_cli --agent escalation_iq
```

Client and server mode:

```bash
python -m neuro_san.service.main_loop.server_main_loop          # terminal 1
python -m neuro_san.client.agent_cli --http --agent escalation_iq   # terminal 2
```

Press Enter on an empty line to send. Run `python -m neuro_san.client.agent_cli --help` to find the option that
shows intermediate agent messages, and turn it on for the demo.

Prompts to try are in [DEMO_SCRIPT.md](DEMO_SCRIPT.md).

## 6. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `429` / `RESOURCE_EXHAUSTED` | Free-tier quota. Wait a minute and retry. The network retries 5 times and falls back to flash-lite. |
| Model not found | Copy the `llm_config` block from your repo's `music_nerd_pro_llm_gemini.hocon` into `escalation_iq.hocon`. |
| `Error: cannot load domain pack` | Check that `neuro_san/coded_tools/escalation_iq/domain_packs/<domain>/config.json` exists, or set `ESCALATION_IQ_PACKS_DIR`. |
| Coded tool class not found | Check `AGENT_TOOL_PATH`, the folder name `escalation_iq`, and that `PYTHONPATH` is the repo root. |
| `DECISION BLOCKED. Missing evidence` | A specialist skipped its tool. Ask the chair to re-run that step. |
| Agent skips steps | Lower `temperature` to 0.1, or use a stronger model (for example `"class": "openai"` with `gpt-4o`). |
| Edited a pack but nothing changed | Packs are cached; restart the server or client. |

## 7. Commit

```bash
git checkout -b feature/escalation-iq
git add neuro_san/registries neuro_san/coded_tools/escalation_iq scripts docs/escalation_iq .gitignore
git commit -m "Add EscalateIQ agent network"
git push origin feature/escalation-iq
```

Run `git status` first and confirm no key or `.env` file is staged.
