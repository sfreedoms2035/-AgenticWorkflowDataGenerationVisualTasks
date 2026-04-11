# Agent Configuration

## Environment
- **OS:** Windows 11
- **Python:** Conda (base)
- **Browser Automation:** Playwright (persistent profile in `.playwright_profile/`)

## Project Paths
- **Project Root:** `C:\Users\User\VS_Projects\Helpers\Antigravity\AgenticWorkflowPlaywright_Tooling`
- **Input PDFs:** `Input/` (relative to project root)
- **Output JSON:** `Output/json/`
- **Output Thinking:** `Output/thinking/`
- **QA & Eval:** `Eval/`
- **Scripts:** `.agent/scripts/`
- **Prompts:** `.agent/prompts/`

## Core Pipeline Entry Point
```
python pipeline.py                    # Process all PDFs
python pipeline.py --pdf "file.pdf"   # Process one PDF
python pipeline.py --resume           # Resume from checkpoint
python pipeline.py --validate-only    # Validate existing outputs
python pipeline.py --pdf "file.pdf" --turn 3 --task 2  # Start from specific point
python pipeline.py --no-dashboard     # Skip dashboard generation
python pipeline.py --render-preview   # Auto-open rendered visuals in browser after each task
```

## Scripts (`.agent/scripts/`)
| Script | Purpose |
|--------|---------|
| `validate_task.py` | Full quality gate validation (JSON, structure, richness, CoT, immersion, visual code volume) |
| `auto_repair.py` | Unified local repair engine (merged content, markdown→JSON, turn padding, think tags) |
| `render_preview.py` | Render visual code (PlantUML/Mermaid/HTML/SVG/D2/DOT) to temp HTML and open in browser |
| `json_aggregator.py` | Post-processing: normalize training_data_id fields |
| `generate_dashboard.py` | Generate HTML dashboard with pipeline stats |

## Playwright Automation (`run_gemini_playwright_v2.py`)
| Feature | Detail |
|---------|--------|
| Model Selection | Always selects Gemini Pro automatically |
| Manual Steps | Zero — escalating timeouts with smart fallbacks |
| JSON Validation | Validates JSON before writing, attempts surgical repair if invalid |
| Exit Codes | 0 = valid JSON saved, 1 = failure |
| Logging | All output to stderr, stdout reserved for machine-readable data |

## Retry Logic
- **Max 3 Gemini attempts** per task
- Between each attempt, the pipeline decides:
  - **Locally fixable** (JSON structure, missing tags, turn padding) → `auto_repair.py`
  - **Needs regeneration** (volume, CoT, immersion) → Gemini re-prompt with targeted repair prompt
- Dashboard generates once per completed PDF (every 8 tasks)

## PDF Classification
PDFs are auto-classified as **Technical** or **Regulatory** based on keyword scoring:
- Keywords: `iso`, `regulation`, `compliance`, `standard`, `directive`, `sae`, `vda`, `unece`, etc.
- Score ≥ 2 → **REGULATORY** (uses regulatory variation schema)
- Score < 2 → **TECHNICAL** (uses technical variation schema)

## Visual Task Types
| Task Type | Rendering Paradigm | Min Lines |
|-----------|-------------------|-----------|
| `html_tool` | Interactive HTML/JS/CSS Dashboard | 400 |
| `html_presentation` | Reveal.js-style Slide Deck | 400 |
| `plantuml_diagram` | PlantUML (Class, State, Gantt, Activity) | 200 |
| `graphviz_dot` | Graphviz DOT (GSN, Attack Trees, Networks) | 200 |
| `d2_diagram` | D2 Declarative Diagrams (Nested Architectures) | 150 |
| `tikz_pgfplots` | LaTeX TikZ/PGFPlots (Math Plots, Kinematics) | 100 |
| `mermaid_diagram` | Mermaid (Flowcharts, Sequences, PERT) | 200 |
| `svg_generation` | Raw SVG (Geometric Layouts, Sensor FOV) | 100 |

## Quality Gates (validate_task.py)
| Gate | Threshold |
|------|-----------|
| CoT length | ≥ 9,000 chars |
| Answer length | ≥ 12,000 chars |
| Visual code volume | Dynamic by task type (see table above) |
| Conversation turns | Exactly 6 |
| CoT sub-elements | All 31 present |
| Self-containment | No banned vocabulary |
| Structured answer | 3 mandatory JSON keys |
| FMEA table | ≥ 10 rows in CoT |
| Copyright header | `// Copyright by 4QDR.AI` |

## File Naming Convention
```
{DocShort}_Turn{N}_Task{K}.json      # Output JSON
{DocShort}_Turn{N}_Task{K}.txt       # Thinking trace
{DocShort}_Turn{N}_Task{K}_Prompt.txt # Generation prompt
{DocShort}_Turn{N}_Task{K}_QA.json   # QA validation report
```
