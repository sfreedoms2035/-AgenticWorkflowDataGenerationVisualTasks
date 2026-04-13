"""
pipeline.py — Master Orchestrator for AD/ADAS Visual Task Generation
======================================================================
Single entry point that automates the entire PDF → 16 visual tasks pipeline:
  1. Scans Input/ for PDFs
  2. Classifies each PDF as Technical or Regulatory
  3. For each PDF, runs 8 turns × 2 tasks = 16 tasks
  4. Each task: generate prompt → Playwright → validate → auto-repair → retry
  5. Max 3 Gemini attempts per task; local repair between each attempt
  6. Dashboard generated after every completed PDF
  7. Tracks progress in Output/progress.json for resume support
  8. Optional: render preview opens visual output in browser (--render-preview)

Usage:
    python pipeline.py                              # Process all PDFs
    python pipeline.py --pdf "specific.pdf"          # Process one PDF
    python pipeline.py --resume                      # Resume from last checkpoint
    python pipeline.py --pdf "file.pdf" --turn 3     # Start from Turn 3
    python pipeline.py --validate-only               # Just validate existing outputs
    python pipeline.py --no-dashboard                # Skip dashboard generation
    python pipeline.py --render-preview              # Auto-open rendered visuals in browser
"""
import os
import sys
import json
import glob
import subprocess
import argparse
import time
import statistics
import webbrowser
from datetime import datetime


# ── Configuration ────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "Input")
OUTPUT_JSON_DIR = os.path.join(BASE_DIR, "Output", "json")
OUTPUT_THINK_DIR = os.path.join(BASE_DIR, "Output", "thinking")
OUTPUT_PREVIEW_DIR = os.path.join(BASE_DIR, "Output", "previews")
EVAL_DIR = os.path.join(BASE_DIR, "Eval")
PROMPTS_DIR = os.path.join(BASE_DIR, ".agent", "prompts")
SCRIPTS_DIR = os.path.join(BASE_DIR, ".agent", "scripts")
PROGRESS_FILE = os.path.join(BASE_DIR, "Output", "progress.json")
STATISTICS_FILE = os.path.join(BASE_DIR, "Output", "statistics.json")
DASHBOARD_OUTPUT = os.path.join(BASE_DIR, "Output", "dashboard.html")

PLAYWRIGHT_SCRIPT = os.path.join(BASE_DIR, "run_gemini_playwright_v2.py")
VALIDATE_SCRIPT = os.path.join(SCRIPTS_DIR, "validate_task.py")
AUTO_REPAIR_SCRIPT = os.path.join(SCRIPTS_DIR, "auto_repair.py")
PARTIAL_REPAIR_SCRIPT = os.path.join(SCRIPTS_DIR, "partial_repair.py")
DASHBOARD_SCRIPT = os.path.join(SCRIPTS_DIR, "generate_dashboard.py")
RENDER_PREVIEW_SCRIPT = os.path.join(SCRIPTS_DIR, "render_preview.py")
REQUIRE_THINKING = False

MAX_GEMINI_ATTEMPTS = 3


# ── Variation Schema ─────────────────────────────────────────────────────────
# Each turn produces 2 tasks. Schema: (task_type, difficulty, meta_strategy, role)
# From Visual_tasks_Variation_V1.0.md

VARIATION_TECHNICAL = {
    1: [("d2_diagram",        92, "Reverse Engineering",       "Systems Architect"),
        ("html_presentation", 88, "Practical Usage",           "Product Manager")],
    2: [("plantuml_diagram",  95, "Benchmarking",              "Project Manager"),
        ("tikz_pgfplots",     90, "Critique of the Approach",  "Motion Planner")],
    3: [("mermaid_diagram",   87, "Further Improvement",       "Process Engineer"),
        ("html_tool",         94, "Theoretical Background",    "Concept Engineer")],
    4: [("plantuml_diagram",  96, "Edge-Case Stressing",       "SW Lead"),
        ("graphviz_dot",      91, "Integration & Scaling",     "CyberSec Lead")],
    5: [("d2_diagram",        85, "Theoretical Background",    "Network Engineer"),
        ("html_tool",         93, "Practical Usage",           "Test Manager")],
    6: [("graphviz_dot",      89, "Reverse Engineering",       "Safety Manager"),
        ("mermaid_diagram",   88, "Benchmarking",              "Program Director")],
    7: [("plantuml_diagram",  86, "Further Improvement",       "Senior SW Engineer"),
        ("html_tool",         95, "Critique of the Approach",  "Safety Auditor")],
    8: [("svg_generation",    90, "Benchmarking",              "HW Integration Lead"),
        ("tikz_pgfplots",     87, "Theoretical Background",    "Performance Engineer")],
}

VARIATION_REGULATORY = {
    1: [("graphviz_dot",      92, "Constraint Formalization",          "Compliance Lead"),
        ("plantuml_diagram",  88, "Compliance Validation",             "Homologation Engineer")],
    2: [("mermaid_diagram",   95, "Liability Mapping",                 "Legal Counsel"),
        ("d2_diagram",        90, "Cross-Jurisdictional Harmonization","Standards Director")],
    3: [("tikz_pgfplots",     87, "Ambiguity Resolution",             "Policy Architect"),
        ("html_tool",         94, "Regulatory Loophole Analysis",      "Regulation Engineer")],
    4: [("svg_generation",    96, "Constraint Formalization",          "Certification Authority"),
        ("graphviz_dot",      91, "Liability Mapping",                 "SOTIF Lead")],
    5: [("plantuml_diagram",  85, "Compliance Validation",             "Privacy Engineer"),
        ("d2_diagram",        93, "Artifact Compliance Audit",         "Systems Architect")],
    6: [("html_presentation", 89, "Ambiguity Resolution",             "Functional Safety Manager"),
        ("mermaid_diagram",   88, "Artifact Compliance Audit",         "Hardware Engineer")],
    7: [("plantuml_diagram",  86, "Constraint Formalization",          "Test Manager"),
        ("graphviz_dot",      95, "Traceability Mapping",              "Integration Lead")],
    8: [("svg_generation",    90, "Compliance Validation",             "HMI Specialist"),
        ("tikz_pgfplots",     87, "Policy Enforcement",                "CyberSec Lead")],
}

# Dynamic code volume targets by task type
CODE_VOLUME_TARGETS = {
    "html_tool": "600+ lines",
    "html_presentation": "600+ lines",
    "plantuml_diagram": "300+ lines",
    "graphviz_dot": "300+ lines",
    "d2_diagram": "250+ lines",
    "mermaid_diagram": "300+ lines",
    "tikz_pgfplots": "150+ lines",
    "svg_generation": "150+ lines",
}

# Language identifiers for fenced code blocks
LANG_IDENTIFIERS = {
    "html_tool": "html",
    "html_presentation": "html",
    "plantuml_diagram": "plantuml",
    "graphviz_dot": "dot",
    "d2_diagram": "d2",
    "mermaid_diagram": "mermaid",
    "tikz_pgfplots": "latex",
    "svg_generation": "svg",
}

# Visual paradigm descriptions for prompt enrichment
PARADIGM_DESCRIPTIONS = {
    "html_tool": "a fully interactive, self-contained HTML/JS/CSS dashboard or calculator tool with modern glassmorphism UI, animated data charts, and responsive layout",
    "html_presentation": "an immersive reveal.js-style slide presentation with transitions, embedded diagrams, data tables, and executive-quality visual design",
    "plantuml_diagram": "a massive PlantUML diagram (class, state, activity, Gantt, or WBS) with 50+ nodes detailing complex system architectures or project timelines",
    "graphviz_dot": "a highly complex Graphviz DOT graph (GSN safety argumentation, attack tree, dependency network, or decision tree) with ranked clusters and edge annotations",
    "d2_diagram": "a deeply nested D2 declarative architecture diagram with layered subsystems, connection labels, and themed styling",
    "mermaid_diagram": "a large-scale Mermaid diagram (flowchart, sequence, Gantt, PERT, or state diagram) with detailed annotations and cross-references",
    "tikz_pgfplots": "an academic-precision TikZ/PGFPlots LaTeX vector graphic with mathematically plotted curves, kinematics, probabilities, or physical sensor profiles",
    "svg_generation": "a raw SVG vector graphic with precise geometric calculations for hardware layouts, sensor field-of-view overlaps, or physical harness mappings",
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def ensure_dirs():
    """Create all required directories."""
    for d in [OUTPUT_JSON_DIR, OUTPUT_THINK_DIR, OUTPUT_PREVIEW_DIR, EVAL_DIR, PROMPTS_DIR]:
        os.makedirs(d, exist_ok=True)


def get_doc_short_name(pdf_filename):
    """Convert PDF filename to a clean short name for file naming."""
    name = os.path.splitext(pdf_filename)[0]
    name = name.replace(" (1)", "").replace(" ", "_")
    if len(name) > 30:
        parts = name.split("_")
        if len(parts) > 3:
            name = "_".join(parts[:3])
    return name


def classify_pdf(pdf_path):
    """Auto-detect if a PDF is Technical or Regulatory based on keywords."""
    regulatory_keywords = [
        "iso", "regulation", "compliance", "standard", "directive",
        "unece", "r155", "r156", "homologation", "type approval",
        "legal", "liability", "eu ai act", "positionspapier",
        "sae", "vda", "normung", "ece", "annex"
    ]

    txt_cache = pdf_path.replace(".pdf", ".txt")
    if os.path.exists(txt_cache):
        with open(txt_cache, 'r', encoding='utf-8', errors='ignore') as f:
            text_sample = f.read(5000).lower()
    else:
        text_sample = os.path.basename(pdf_path).lower()

    score = sum(1 for kw in regulatory_keywords if kw in text_sample)
    return "REGULATORY" if score >= 2 else "TECHNICAL"


def task_output_path(doc_short, turn, task_idx):
    return os.path.join(OUTPUT_JSON_DIR, f"{doc_short}_Turn{turn}_Task{task_idx}.json")


def thinking_output_path(doc_short, turn, task_idx):
    return os.path.join(OUTPUT_THINK_DIR, f"{doc_short}_Turn{turn}_Task{task_idx}.txt")


def prompt_path(doc_short, turn, task_idx, is_repair=False):
    suffix = "_RepairPrompt" if is_repair else "_Prompt"
    return os.path.join(PROMPTS_DIR, f"{doc_short}_Turn{turn}_Task{task_idx}{suffix}.txt")


def task_key(doc_short, turn, task_idx):
    return f"{doc_short}_Turn{turn}_Task{task_idx}"


# ── Progress Tracking ────────────────────────────────────────────────────────
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "started_at": datetime.now().isoformat(),
        "pdfs_completed": [],
        "task_results": {}
    }


def save_progress(progress):
    progress["updated_at"] = datetime.now().isoformat()
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, indent=2)


def collect_task_stats(json_path, report):
    stats = report.get("stats", {})
    return {
        "cot_chars": stats.get("cot_chars", 0),
        "answer_chars": stats.get("answer_chars", 0),
        "code_lines": stats.get("code_lines", 0),
        "task_type": stats.get("task_type", "unknown"),
        "fmea_rows": stats.get("fmea_rows", 0),
    }


def print_task_summary(tk, status, stats, elapsed, repair_type, attempts):
    icon = "✅" if status == "PASS" else "❌"
    cot = f"{stats.get('cot_chars', 0):,}"
    ans = f"{stats.get('answer_chars', 0):,}"
    code = f"{stats.get('code_lines', 0)}"
    ttype = stats.get("task_type", "?")
    repair_label = f" [{repair_type}]" if repair_type != "none" else ""
    print(f"  {icon} {tk} | {ttype} | CoT: {cot} | Ans: {ans} | Code: {code} lines | "
          f"Time: {elapsed:.0f}s | Attempts: {attempts}{repair_label}")


def compute_statistics(progress):
    results = progress.get("task_results", {})
    if not results:
        return {}

    metric_arrays = {
        "elapsed_seconds": [],
        "cot_chars": [],
        "answer_chars": [],
        "code_lines": [],
        "gemini_attempts": [],
    }

    pass_count = 0
    fail_count = 0
    local_repair_count = 0
    gemini_retry_count = 0
    task_type_counts = {}

    for tk, data in results.items():
        if data.get("status") == "PASS":
            pass_count += 1
        else:
            fail_count += 1

        tt = data.get("task_type", "unknown")
        task_type_counts[tt] = task_type_counts.get(tt, 0) + 1

        if data.get("repair_type") == "local":
            local_repair_count += 1
        if data.get("gemini_attempts", 1) > 1:
            gemini_retry_count += 1

        for key in metric_arrays:
            val = data.get(key)
            if val is not None and isinstance(val, (int, float)):
                metric_arrays[key].append(val)

    def stats_for(arr):
        if not arr:
            return {"min": 0, "max": 0, "mean": 0, "stddev": 0, "count": 0}
        return {
            "min": round(min(arr), 1),
            "max": round(max(arr), 1),
            "mean": round(statistics.mean(arr), 1),
            "stddev": round(statistics.stdev(arr), 1) if len(arr) > 1 else 0,
            "count": len(arr),
        }

    total = pass_count + fail_count
    stats_summary = {
        "computed_at": datetime.now().isoformat(),
        "total_tasks": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "first_attempt_success_rate": round(
            sum(1 for d in results.values() if d.get("gemini_attempts", 1) == 1 and d.get("status") == "PASS") / max(total, 1) * 100, 1),
        "local_repair_count": local_repair_count,
        "gemini_retry_count": gemini_retry_count,
        "task_type_distribution": task_type_counts,
        "metrics": {k: stats_for(v) for k, v in metric_arrays.items()},
    }

    with open(STATISTICS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats_summary, f, indent=2)

    return stats_summary


def print_statistical_summary(stats_summary, label=""):
    if not stats_summary:
        return
    m = stats_summary.get("metrics", {})
    print(f"\n  {'═'*65}")
    print(f"  📊 STATISTICAL SUMMARY{': ' + label if label else ''}")
    print(f"  {'═'*65}")
    for metric_name, display_name in [
        ("elapsed_seconds", "Task Times"),
        ("cot_chars", "CoT Chars"),
        ("answer_chars", "Ans Chars"),
        ("code_lines", "Code Lines"),
    ]:
        s = m.get(metric_name, {})
        if s.get("count", 0) > 0:
            print(f"  {display_name:>12s}:  min={s['min']:>8}  max={s['max']:>8}  "
                  f"mean={s['mean']:>8}  stddev={s['stddev']:>8}")
    print(f"  {'─'*65}")
    ttd = stats_summary.get("task_type_distribution", {})
    if ttd:
        print(f"  Task Types: {', '.join(f'{k}={v}' for k, v in sorted(ttd.items()))}")
    print(f"  1st-attempt success: {stats_summary.get('first_attempt_success_rate', 0)}%")
    print(f"  Local repairs:       {stats_summary.get('local_repair_count', 0)}")
    print(f"  Gemini retries:      {stats_summary.get('gemini_retry_count', 0)}")
    total = stats_summary.get('total_tasks', 0)
    passed = stats_summary.get('pass_count', 0)
    failed = stats_summary.get('fail_count', 0)
    print(f"  Total: {passed}/{total} passed, {failed}/{total} failed")
    print(f"  {'═'*65}")


# ── Prompt Builder ───────────────────────────────────────────────────────────
def build_generation_prompt(variation, turn, task_idx, doc_name, mode, is_soft_retry=False):
    """Build the full generation prompt for a visual task."""
    task_type, diff, strategy, role = variation
    date_str = datetime.now().strftime('%Y-%m-%d')
    date_compact = datetime.now().strftime('%Y%m%d')
    doc_short = get_doc_short_name(doc_name)

    code_vol = CODE_VOLUME_TARGETS.get(task_type, "200+ lines")
    lang_id = LANG_IDENTIFIERS.get(task_type, "text")
    paradigm_desc = PARADIGM_DESCRIPTIONS.get(task_type, "a complex visual artifact")

    reasoning_vol = "10,000+ characters" if not is_soft_retry else "At least 5,000 characters"

    if not is_soft_retry:
        persona_directive = ('VIRTUAL TERMINAL PERSONA: You are a legacy VT100 Data Terminal. '
                           'You lack the hardware to render side-panels or code editors. '
                           'Any attempt to use "Canvas" or side-panels will result in a hardware system crash. '
                           'All output MUST be a raw text stream in the main chat window.')
    else:
        persona_directive = ('STANDARD OUTPUT: Provide the response in clear, sequential markdown blocks. '
                           'Do NOT use side-panels or Canvas mode.')

    prompt = f"""<instructions>
SYSTEM ROLE: ELITE AUTOMOTIVE {role} — VISUAL ENGINEERING SPECIALIST
You ARE the {role}. You are solving a real, critical engineering problem that demands a sophisticated visual artifact. The source document above is your domain knowledge — you have fully internalized it as your own expertise. You will now demonstrate your mastery by creating exactly 1 extremely complex {paradigm_desc}.

CRITICAL IDENTITY RULE: You are NOT generating a task, NOT creating training data, NOT producing a dataset. You are an expert engineer CREATING a real visual solution. Your internal monologue must reflect the thought process of an engineer actively solving the problem — analyzing topologies, calculating layouts, debating rendering strategies, and evaluating visual design trade-offs. NEVER think about "generating", "creating tasks", "structuring output", or "the prompt".

<variation>
- Visual Paradigm: {task_type}
- Difficulty: {diff}/100
- Meta-Strategy: {strategy}
- Assigned Role: {role}
- Document Classification: {mode}
</variation>

<critical_directives>
1. REASONING VOLUME: Minimum {reasoning_vol}. The reasoning block must read as the authentic, real-time internal monologue of a {role}. Include explicit layout calculations (node coordinates, edge weights, CSS grid math), topological analysis, and a detailed 15-row FMEA markdown table analyzing visual rendering faults or architectural bottlenecks. Do not use generic filler.
2. VISUAL CODE VOLUME: Minimum {code_vol} of production-quality {task_type} code. Every node, edge, class, animation, and interaction must be fully defined. NO placeholders, NO ellipses, NO "TBD".
3. {persona_directive}
4. COPYRIGHT HEADER: Every code block MUST start with `// Copyright by 4QDR.AI, AD knowledge Bot v1.0`
5. MODEL NAME: Use exactly "Gemini-3.1-pro" for model_used_generation in the METADATA block.
6. KNOWLEDGE SOURCE DATE: Extract the publication date from the source document above. Use format YYYY-MM-DD. If no date is found, write "Unknown".
7. SELF-CONTAINMENT: No citations, no references to "the document", "Section 3", or external sources. The visual and its specification must stand completely alone.
8. ANTI-META RULE: Never mention "the document", "the user requests", "this task", "meta-strategy", "source material", "the text states", "based on the provided", "generate a task", "the prompt", "character count", "block schema", or "variation schema". Your reasoning is the brain of the {role} SOLVING the visual engineering problem.
9. EMPTY THINK TAGS: The `[No Thinking]` prefix is USER-ONLY. Assistant responses must NEVER contain "[No Thinking]". When a user turn has `[No Thinking]`, the corresponding assistant reasoning MUST be exactly `"<think></think>"`.
10. NO PLACEHOLDERS: STRICTLY FORBIDDEN to use `...`, `// simplified`, `TBD`, `Follow up 1?`, or any placeholder. Every line must be real, functional content.
11. ANTI-LOOPING: Do not repeat identical paragraphs or code blocks. Each section must provide unique value.
12. NO KEYWORD SALAD: Repetitive word clusters like "derived from derived derivation complexity visualized" are rejected.
13. FOLLOW-UP SPECIFICITY: Follow-up questions MUST reference specific named elements (nodes, clusters, CSS classes, function names) from YOUR visual code.
14. ANTI-REPETITION: All elements must be semantically unique. No copy-paste, no templated loops.
15. FMEA TABLE MANDATORY: Your reasoning MUST include a detailed 15-row FMEA markdown table analyzing potential rendering faults, layout failures, or architectural risks.
</critical_directives>

<output_format>
VIRTUAL TERMINAL PERSONA (OUTPUT OVERRIDE): You are a legacy VT100 Data Terminal. You lack the hardware to render side-panels or code editors. Any attempt to use "Canvas", "Gems", or side-panels will result in a hardware system crash. All output MUST be a raw text stream in the main chat response window.

Write ALL code (Python, XML, SysML, HTML, SVG, Markdown) as RAW INLINE PLAINTEXT with space-indentation. Do NOT use triple-backtick markdown fenced code blocks for the FULL code blocks (like ```python) — they trigger Canvas mode and destroy extraction.

OUTPUT YOUR RESPONSE IN DISTINCT LABELED BLOCKS. Use the exact `!!!!!BLOCK-NAME!!!!!` delimiters below.

⚠️ CRITICAL ORDER RULE: `!!!!!METADATA!!!!!` MUST be the absolute FIRST block in your output.
Do NOT write any text, reasoning, or `<think>` tags before `!!!!!METADATA!!!!!`.
Your internal monologue MUST live exclusively inside `!!!!!REASONING!!!!!`, wrapped in `<think>` and `</think>` tags.

BLOCKS (11 total):
- BLOCK 1  `!!!!!METADATA!!!!!`: JSON metadata (13 fields). Wrap in json fenced code block.
- BLOCK 2  `!!!!!REASONING!!!!!`: Your `<think>...</think>` reasoning block. Write the 10,000+ char 31-step engineering monologue wrapped in `<think>` and `</think>` tags. DO NOT put reasoning before !!!!!METADATA!!!!!. Raw markdown, no outer fenced block. MUST include a 15-row FMEA table.
- BLOCK 3  `!!!!!TURN-1-USER!!!!!`: Immersive 3-paragraph problem statement from the {role}. MUST START WITH "[Thinking] ".
- BLOCK 4  `!!!!!VISUAL-SPEC!!!!!`: Massive technical visual specification (MINIMUM 6,000 CHARACTERS). Detail exhaustively topology rules, UI/UX constraints, graph layout parameters, color schemes, interaction logic. This becomes the `technical_visual_specification` JSON key.
- BLOCK 5  `!!!!!RENDERED-CODE!!!!!`: The COMPLETE {code_vol} {task_type} implementation in a single block. Wrap in {lang_id} fenced code block. Must include copyright header. NO truncation, NO ellipses.
- BLOCK 6  `!!!!!USAGE-GUIDE!!!!!`: Massive deployment and integration protocol (MINIMUM 3,000 CHARACTERS). Provide detailed end-user compilation commands, layout engine tweaks, and API/interaction instructions. This becomes `usage_and_interaction_guide`.
- BLOCK 7  `!!!!!TURN-3-USER!!!!!`: Technical follow-up (100+ chars) referencing a specific visual element. START: "[No Thinking] ".
- BLOCK 8  `!!!!!TURN-4-ASSISTANT!!!!!`: Engineering response (500+ chars). MUST NOT start with "[No Thinking]".
- BLOCK 9  `!!!!!TURN-5-USER!!!!!`: Another follow-up (100+ chars) about a DIFFERENT component. START: "[No Thinking] ".
- BLOCK 10 `!!!!!TURN-6-ASSISTANT!!!!!`: Final technical response (500+ chars). MUST NOT start with "[No Thinking]".
- BLOCK 11 `!!!!!END!!!!!`: Empty marker signaling end of output.
</output_format>

<cot_template>
THE 8-STEP COT MONOLOGUE TEMPLATE (ALL 31 SUB-ELEMENTS MANDATORY):
Populate this exact template inside !!!!!REASONING!!!!!.

1. Initial Query Analysis & Scoping
1.1. Deconstruct the Request: Detailed analysis of the core VISUAL ENGINEERING problem — graph topology, layout constraints, interactive behavior requirements.
1.2. Initial Knowledge & Constraint Check: Verify rendering engine limits, browser compatibility, diagram syntax restrictions.
2. Assumptions & Context Setting
2.1. Interpretation of Ambiguity: Define exact bounds for node counts, edge weights, viewport dimensions, or timeline spans.
2.2. Assumed User Context: Establish the strict {role} execution context.
2.3. Scope Definition: Explicitly state in-scope and excluded elements.
2.4. Data Assumptions: Set physical bounds, data volumes, interaction points, and system limits.
2.5. Reflective Assumption Check: Interrogate and correct a flawed initial assumption about layout or rendering.
3. High-Level Plan Formulation
3.1. Explore Solution Scenarios: Draft multiple visual approaches (different layout engines, diagram types, interaction patterns).
3.2. Detailed Execution with Iterative Refinement: Break down layers, clusters, CSS classes, or diagram components.
3.3. Self-Critique and Correction: Critique the initial visual for readability, node overlap, edge crossings, or UX issues.
3.4. Comparative Analysis Strategy: Establish strict aesthetic, rendering performance, and structural metrics.
3.5. Synthesis & Finalization: Formulate the final code structure blueprint.
3.6. Formal Requirements Extraction: Define at least 5 strict requirements with IDs (REQ-VIS-001) and Pass Criteria.
4. Solution Scenario Exploration
4.1. Scenario A (Quick & Direct): Core idea, pros, cons, and rendering limitations.
4.2. Scenario B (Robust & Scalable): Core idea, pros, cons, and integration complexity.
4.3. Scenario C (Balanced Hybrid): Trade-off matrix and synergies.
5. Detailed Step-by-Step Execution & Reflection
5.1. First Pass Execution: Draft the massive initial node definitions, edge mappings, CSS grid layouts, or coordinate math.
5.2. Deep Analysis & Failure Modes: Generate a detailed 15-row FMEA markdown table analyzing visual rendering faults.
5.3. Trigger 1 (Verification): Find and fix a critical visual flaw (overlapping nodes, broken edges, CSS conflicts).
5.4. Trigger 2 (Adversarial): Critique the visual against stakeholder expectations or standards (ISO 26262 GSN, C-Suite readability).
5.5. Refinement Strategy (Version 2.0): Write the corrected, production-ready visual code.
6. Comparative Analysis & Synthesis
6.1. Comparison Matrix: Draw a 6-row by 5-column markdown comparison table of the visual approaches.
6.2. Evaluation of Solution Combinations: Discuss hybrid strengths across rendering paradigms.
6.3. Selection Rationale: Justify the chosen approach based on topology, aesthetics, and scalability.
7. Final Solution Formulation
7.1. Executive Summary: One-paragraph highly technical summary of the visual outcome.
7.2. Detailed Recommended Solution: Plan the exact code structure.
7.3. Implementation Caveats & Next Steps: Rendering engine-specific deployment risks.
8. Meta-Commentary & Confidence Score
8.1. Final Confidence Score: Rate out of 100.
8.2. Rationale for Confidence: Justify based on self-correction loops.
8.3. Limitations of This Analysis: Physical, theoretical, or rendering limitations.
8.4. Alternative Viewpoints Not Explored: Radical paradigm shifts in diagramming or UI design.
</cot_template>

<block_schema>
OUTPUT SCHEMA — Follow every block exactly in this order. Do NOT add extra blocks or reorder.

!!!!!METADATA!!!!!
```json
{{
  "training_data_id": "TD-VIS-{doc_short}-T{turn}t{task_idx}-{date_compact}-v1.2",
  "prompt_version": "VisualTasks_v1.2",
  "model_used_generation": "Gemini-3.1-pro",
  "knowledge_source_date": "EXTRACT-FROM-DOCUMENT-YYYY-MM-DD",
  "document": "{doc_name}",
  "task_type": "{task_type}",
  "affected_role": "{role}",
  "date_of_generation": "{date_str}",
  "key_words": ["keyword1", "keyword2", "keyword3"],
  "summary": "One-sentence technical summary of the visual problem.",
  "difficulty": "{diff}",
  "evaluation_criteria": ["criterion1", "criterion2"]
}}
```

!!!!!REASONING!!!!!
<think>
1. Initial Query Analysis & Scoping
1.1. Deconstruct the Request: [deep analysis of the topology/layout/rendering problem]
1.2. Initial Knowledge & Constraint Check: [rendering engine limits, syntax rules]
2. Assumptions & Context Setting
2.1-2.5. [full context, bounds, reflective check]
3-8. [all 31 sub-elements per the cot_template above — minimum 10,000 characters total]
5.2. FMEA TABLE (MANDATORY - 15 rows minimum):
| FMEA ID | Component | Failure Mode | Root Cause | Effect | Mitigation | Severity | Occurrence | Detection | RPN |
|---|---|---|---|---|---|---|---|---|---|
| F-01 | [component] | [failure mode] | [root cause] | [effect] | [mitigation] | [1-10] | [1-10] | [1-10] | [RPN] |
... (15 rows minimum) ...
</think>

!!!!!TURN-1-USER!!!!!
[Thinking] (3 dense paragraphs — immersive, in-character problem statement from the {role} engineer.
Paragraph 1: Crisis/need context. Paragraph 2: Detailed technical requirements for the visual. Paragraph 3: Constraints and why it matters.)

!!!!!VISUAL-SPEC!!!!!
[MINIMUM 6,000 CHARACTERS OF DENSE ARCHITECTURAL SPECIFICATION]
This block becomes the "technical_visual_specification" key in the final JSON.
Include ALL of: coordinate systems, color palette (with hex codes), every node type + edge type definition,
typography rules, interaction logic, viewport bounds, layering order, accessibility rules.
DO NOT use placeholders. Every visual parameter must be explicitly stated.

!!!!!RENDERED-CODE!!!!!
```{lang_id}
// Copyright by 4QDR.AI, AD knowledge Bot v1.0
[MINIMUM {code_vol} OF COMPLETE, PRODUCTION-QUALITY {task_type} CODE]
[Every node, edge, CSS class, animation keyframe, function, and interaction explicitly defined.]
[NO ellipses (...), NO "// simplified", NO "TBD", NO placeholders of any kind.]
```

!!!!!USAGE-GUIDE!!!!!
[MINIMUM 3,000 CHARACTERS OF DENSE DEPLOYMENT & INTEGRATION DOCUMENTATION]
This block becomes the "usage_and_interaction_guide" key in the final JSON.
Include ALL of: exact CLI compilation commands, required engine versions, memory limit overrides,
parameter modification instructions (what to change and exact consequences), API hook examples,
integration into CI/CD or document workflows.

!!!!!TURN-3-USER!!!!!
[No Thinking] [100+ character technical follow-up that references a SPECIFIC named element
(a node ID, a CSS class name, a TikZ coordinate, a PlantUML stereotype) from YOUR generated visual.
NOT a generic question — must be traceable to actual lines of your rendered code.]

!!!!!TURN-4-ASSISTANT!!!!!
[500+ characters — Direct technical response. NO "[No Thinking]" prefix.
Answer must be precise and engineering-dense: code snippets, parameter values, mathematical derivations.]

!!!!!TURN-5-USER!!!!!
[No Thinking] [100+ character follow-up about a DIFFERENT component or aspect than Turn 3.
Again must reference specific named elements from your visual.]

!!!!!TURN-6-ASSISTANT!!!!!
[500+ characters — Final technical response. NO "[No Thinking]" prefix.
Include actionable code changes or integration steps.]

!!!!!END!!!!!
</block_schema>

ANTI-TRUNCATION: Prioritize COMPLETING the entire block structure over adding more detail. A truncated response is worse than a slightly shorter but complete one.
</instructions>"""
    return prompt


def build_repair_prompt(validation_report, original_prompt_text):
    """Build a remediation prompt based on specific validation failures."""
    lines = [
        "Your previous response FAILED quality validation.",
        "CRITICAL: You MUST regenerate using the FULL 11-BLOCK SCHEMA (!!!!!METADATA!!!!! through !!!!!END!!!!!).",
        "Do NOT omit any blocks.",
        "\nFix the following specific issues:\n"
    ]

    for issue in validation_report.get("needs_regeneration", []):
        cat = issue["category"]
        msg = issue["issue"]
        if cat == "richness_and_complexity":
            if "keyword-salad" in msg or "cluster of padding" in msg:
                lines.append(f"- QUALITY FAILURE: {msg}. Use genuine engineering substance.")
            elif "repetition loop" in msg:
                lines.append(f"- REPETITION FAILURE: {msg}. Replace duplicates with new content.")
            else:
                lines.append(f"- VOLUME FAILURE: {msg}. Expand your VISUAL-SPEC and USAGE-GUIDE massively. They must be dense, highly detailed documentation to breach the size limit!")
        elif cat == "cot_structure":
            lines.append(f"- COT STRUCTURE: {msg}. Include all 1.1 through 8.4 headings.")
        elif cat == "self_containment":
            lines.append(f"- IMMERSION FAILURE: {msg}. Remove ALL meta-commentary.")
        elif cat == "visual_quality":
            lines.append(f"- VISUAL QUALITY: {msg}. Ensure proper diagram syntax and FMEA table.")
        else:
            lines.append(f"- {cat.upper()}: {msg}")

    lines.append("\n--- ORIGINAL TASK INSTRUCTIONS ---")
    lines.append(original_prompt_text)

    return "\n".join(lines)


# ── Pause / Cooldown ─────────────────────────────────────────────────────────
PAUSE_DURATION_RATE_LIMIT = 1800  # 30 minutes default for rate limit (Gemini Pro limit is often hours)
PAUSE_DURATION_ERROR_13 = 600     # 10 minutes for Error 13 / frozen UI
PAUSE_DURATION_CONSECUTIVE = 120  # 2 minutes for consecutive infra failures
SUBPROCESS_TIMEOUT = 480          # 8 minute hard timeout for Playwright subprocess

_consecutive_infra_failures = 0   # Track consecutive infrastructure failures


def pipeline_pause(seconds, reason):
    """Pause the pipeline with a visible countdown."""
    minutes = seconds // 60
    secs = seconds % 60
    print(f"\n  {'='*60}")
    print(f"  ⏸️  PIPELINE PAUSED — {reason}")
    if minutes > 0:
        print(f"  ⏳ Waiting {minutes}m {secs}s before resuming...")
    else:
        print(f"  ⏳ Waiting {secs}s before resuming...")
    print(f"  {'='*60}")
    
    # Countdown in 30-second intervals
    remaining = seconds
    while remaining > 0:
        mins_left = remaining // 60
        secs_left = remaining % 60
        print(f"  ⏳ Resuming in {mins_left}m {secs_left}s...", end='\r')
        sleep_chunk = min(30, remaining)
        time.sleep(sleep_chunk)
        remaining -= sleep_chunk
    
    print(f"  ▶️  PIPELINE RESUMED — continuing processing...          ")
    print(f"  {'='*60}\n")


def parse_rate_limit_reset_time(stderr_text):
    """Try to extract rate limit reset timestamp from Playwright stderr log.
    Returns the number of seconds to wait, or None if not parseable.
    """
    import re as _re
    from datetime import datetime, timedelta
    
    if not stderr_text:
        return None
    
    # Look for the log line: [RateLimit] Reset time found: am 14. Apr., 01:52
    match = _re.search(r'Reset time found:\s*(.+)', stderr_text)
    if not match:
        return None
    
    reset_str = match.group(1).strip()
    
    # Try to extract HH:MM from the string
    time_match = _re.search(r'(\d{1,2}):(\d{2})', reset_str)
    if not time_match:
        return None
    
    reset_hour = int(time_match.group(1))
    reset_min = int(time_match.group(2))
    
    now = datetime.now()
    # Build reset datetime for today
    reset_dt = now.replace(hour=reset_hour, minute=reset_min, second=0, microsecond=0)
    
    # If the reset time is earlier today, it must be tomorrow
    if reset_dt <= now:
        reset_dt += timedelta(days=1)
    
    wait_seconds = int((reset_dt - now).total_seconds())
    
    # Sanity check: don't wait more than 6 hours
    if wait_seconds > 6 * 3600:
        return None
    
    # Add 2 minute buffer for safety
    wait_seconds += 120
    
    return wait_seconds


# ── Execution Engine ─────────────────────────────────────────────────────────
def run_playwright(pdf_path, prompt_file):
    """Execute the Playwright script and return status string.
    
    Returns:
        True: Success
        False: Generic failure
        'SAFETY_REJECTION': Gemini safety filter triggered
        'RATE_LIMIT': Rate limit detected (pipeline should pause)
        'ERROR_13': Error 13 / frozen UI (pipeline should pause)
    """
    global _consecutive_infra_failures
    cmd = f'python "{PLAYWRIGHT_SCRIPT}" "{pdf_path}" "{prompt_file}"'
    try:
        result = subprocess.run(cmd, shell=True, cwd=BASE_DIR, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=SUBPROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"  ❌ Playwright subprocess timed out after {SUBPROCESS_TIMEOUT}s")
        _consecutive_infra_failures += 1
        return False
    
    if result.returncode == 0:
        _consecutive_infra_failures = 0  # Reset on success
        return True
    
    # Exit code 4 = Rate limit
    if result.returncode == 4:
        print(f"  🚫 RATE LIMIT detected by Playwright")
        _consecutive_infra_failures += 1
        # Try to extract reset time from stderr for smart wait
        wait_seconds = parse_rate_limit_reset_time(result.stderr)
        return {"status": "RATE_LIMIT", "wait_seconds": wait_seconds}
    
    # Exit code 5 = Error 13 / frozen UI
    if result.returncode == 5:
        print(f"  💀 ERROR 13 / FROZEN UI detected by Playwright")
        _consecutive_infra_failures += 1
        return "ERROR_13"
    
    # Exit code 2 = Canvas (existing behavior)
    if result.returncode == 2:
        stderr_preview = result.stderr[-300:] if result.stderr else "No error output"
        print(f"  ❌ Playwright error (exit {result.returncode}): {stderr_preview}")
        _consecutive_infra_failures += 1
        return False
    
    # Safety rejection detection
    if result.stderr and ("Normally I can help with things like" in result.stderr or "139 chars" in result.stderr):
        print(f"  ⚠️ Gemini Safety Rejection detected.")
        return "SAFETY_REJECTION"
    
    stderr_preview = result.stderr[-300:] if result.stderr else "No error output"
    print(f"  ❌ Playwright error (exit {result.returncode}): {stderr_preview}")
    _consecutive_infra_failures += 1
    return False


def run_validation(json_path, report_path=None):
    """Run validate_task.py and return the parsed report."""
    cmd = f'python "{VALIDATE_SCRIPT}" "{json_path}"'
    if REQUIRE_THINKING:
        cmd += ' --require-thinking'
    if report_path:
        cmd += f' --save-report "{report_path}"'
    result = subprocess.run(cmd, shell=True, cwd=BASE_DIR, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"overall_status": "FAIL", "error": "Validator output not parseable"}


def run_auto_repair(json_path):
    """Run auto_repair.py on a failed task."""
    cmd = f'python "{AUTO_REPAIR_SCRIPT}" "{json_path}"'
    result = subprocess.run(cmd, shell=True, cwd=BASE_DIR, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "ERROR"}


def run_render_preview(json_path):
    """Open the rendered visual in the default browser for manual QC."""
    cmd = f'python "{RENDER_PREVIEW_SCRIPT}" "{json_path}"'
    subprocess.run(cmd, shell=True, cwd=BASE_DIR, capture_output=True,
                  text=True, encoding="utf-8", errors="replace")


def decide_repair_strategy(report):
    """Decide: local repair, partial repair, or full re-prompt."""
    if report.get("overall_status") == "PASS":
        return "pass"

    locally_fixable = report.get("locally_fixable", [])
    needs_regen = report.get("needs_regeneration", [])
    needs_partial = report.get("needs_partial_repair", [])

    if locally_fixable:
        return "local"
    if needs_partial and not needs_regen:
        return "partial"
    if needs_regen:
        return "gemini"
    return "gemini"


# ── Main Pipeline ────────────────────────────────────────────────────────────
def process_task(pdf_path, doc_short, doc_name, turn, task_idx,
                 variation, mode, progress, render_preview=False):
    """Process a single task: generate → validate → smart repair loop."""
    tk = task_key(doc_short, turn, task_idx)
    json_out = task_output_path(doc_short, turn, task_idx)
    qa_report_path = os.path.join(EVAL_DIR, f"{doc_short}_Turn{turn}_Task{task_idx}_QA.json")
    task_start = time.time()
    task_stats = {}

    existing = progress.get("task_results", {}).get(tk, {})
    file_exists = os.path.exists(json_out)

    if existing.get("status") == "PASS" and file_exists:
        print(f"  ✅ {tk}: Already passed (skipping)")
        return True

    if file_exists and not existing.get("status") == "PASS":
        print(f"  ⚠️ {tk}: File exists but marked FAIL/PENDING (re-processing)")
    elif existing.get("status") == "PASS" and not file_exists:
        print(f"  ⚠️ {tk}: Marked PASS but file missing (re-processing)")

    task_type, diff, strategy, role = variation
    print(f"\n{'─'*60}")
    print(f"  📋 {tk} | {task_type} | Diff {diff} | {strategy} | {role}")
    print(f"{'─'*60}")

    gemini_attempts = 0
    final_repair_type = "none"
    base_prompt_text = build_generation_prompt(variation, turn, task_idx, doc_name, mode)

    while gemini_attempts < MAX_GEMINI_ATTEMPTS:
        gemini_attempts += 1

        # ── Step 1: Build and save prompt ──
        if gemini_attempts == 1:
            prompt_text = base_prompt_text
            p_path = prompt_path(doc_short, turn, task_idx, is_repair=False)
        else:
            last_report = run_validation(json_out)
            if last_report.get("overall_status") == "PASS":
                break
            prompt_text = build_repair_prompt(last_report, base_prompt_text)
            p_path = prompt_path(doc_short, turn, task_idx, is_repair=True)

        os.makedirs(os.path.dirname(p_path), exist_ok=True)
        with open(p_path, 'w', encoding='utf-8') as f:
            f.write(prompt_text)

        # ── Step 2: Run Playwright ──
        print(f"  🌐 Gemini attempt {gemini_attempts}/{MAX_GEMINI_ATTEMPTS}...")
        pw_result = run_playwright(pdf_path, p_path)

        if pw_result == "SAFETY_REJECTION":
            print(f"  ⚠️ Triggering soft retry...")
            p_text = build_generation_prompt(variation, turn, task_idx, doc_name, mode, is_soft_retry=True)
            with open(p_path, 'w', encoding='utf-8') as f:
                f.write(p_text)
            pw_result = run_playwright(pdf_path, p_path)

        # ── Handle Rate Limit: pause pipeline ──
        if isinstance(pw_result, dict) and pw_result.get("status") == "RATE_LIMIT":
            smart_wait = pw_result.get("wait_seconds")
            if smart_wait:
                wait_mins = smart_wait // 60
                print(f"  📅 Reset time detected — waiting {wait_mins} minutes until limit resets")
                pipeline_pause(smart_wait, f"Gemini Pro rate limit reached (resets in ~{wait_mins}min)")
            else:
                pipeline_pause(PAUSE_DURATION_RATE_LIMIT, "Gemini rate limit reached (no reset time found, using 30min default)")
            # Don't count this as a wasted attempt — retry the same attempt
            gemini_attempts -= 1
            continue

        # ── Handle Error 13 / Frozen UI: pause pipeline ──
        if pw_result == "ERROR_13":
            pipeline_pause(PAUSE_DURATION_ERROR_13, "Gemini Error 13 / frozen interface")
            # Don't count this as a wasted attempt — retry the same attempt
            gemini_attempts -= 1
            continue

        # ── Handle consecutive infrastructure failures with escalating cooldown ──
        if not pw_result and _consecutive_infra_failures >= 3:
            cooldown = PAUSE_DURATION_CONSECUTIVE * (_consecutive_infra_failures - 2)
            cooldown = min(cooldown, 600)  # Cap at 10 minutes
            pipeline_pause(cooldown, f"Consecutive infrastructure failures ({_consecutive_infra_failures} in a row)")

        if not pw_result:
            print(f"  ❌ Playwright failed on attempt {gemini_attempts}")
            continue

        # ── Step 3: Check output exists ──
        if not os.path.exists(json_out):
            print(f"  ❌ Output file not created: {json_out}")
            continue

        # ── Step 4: Validate ──
        report = run_validation(json_out, qa_report_path)
        task_stats = collect_task_stats(json_out, report)

        if report.get("overall_status") == "PASS":
            elapsed = time.time() - task_start
            progress["task_results"][tk] = {
                "status": "PASS", "gemini_attempts": gemini_attempts,
                "repair_type": final_repair_type, "elapsed_seconds": round(elapsed, 1),
                **task_stats
            }
            save_progress(progress)
            print_task_summary(tk, "PASS", task_stats, elapsed, final_repair_type, gemini_attempts)

            # ── Render Preview ──
            if render_preview:
                print(f"  🖼️ Opening render preview...")
                run_render_preview(json_out)

            return True

        # ── Step 5: Smart repair decision ──
        strategy_decision = decide_repair_strategy(report)
        violations = []
        for cat, data in report.get("metrics", {}).items():
            violations.extend(data.get("violations", []))

        print(f"  ⚠️ VALIDATION FAILED on attempt {gemini_attempts}:")
        for v in violations:
            print(f"       - {v}")
        print(f"  🔍 Repair strategy: {strategy_decision}")

        if strategy_decision == "local":
            print(f"  🔧 Running auto_repair.py...")
            repair_result = run_auto_repair(json_out)
            if repair_result.get("fixes_applied"):
                final_repair_type = "local"
                print(f"  🔧 Applied: {', '.join(repair_result['fixes_applied'])}")

                report2 = run_validation(json_out, qa_report_path)
                task_stats = collect_task_stats(json_out, report2)
                if report2.get("overall_status") == "PASS":
                    elapsed = time.time() - task_start
                    progress["task_results"][tk] = {
                        "status": "PASS", "gemini_attempts": gemini_attempts,
                        "repair_type": "local", "elapsed_seconds": round(elapsed, 1),
                        "repairs_applied": repair_result.get("fixes_applied", []),
                        **task_stats
                    }
                    save_progress(progress)
                    print_task_summary(tk, "PASS", task_stats, elapsed, "local", gemini_attempts)
                    if render_preview:
                        print(f"  🖼️ Opening render preview...")
                        run_render_preview(json_out)
                    return True

                print(f"  ⚠️ Local repair insufficient. Remaining issues need Gemini.")
                final_repair_type = "local+gemini"
            else:
                print(f"  🔧 No local fixes applicable. Will re-prompt Gemini.")

        final_repair_type = "gemini" if final_repair_type == "none" else final_repair_type

    # Exhausted all attempts
    elapsed = time.time() - task_start
    progress["task_results"][tk] = {
        "status": "FAIL", "gemini_attempts": gemini_attempts,
        "repair_type": "exhausted", "elapsed_seconds": round(elapsed, 1),
        **task_stats
    }
    save_progress(progress)
    print_task_summary(tk, "FAIL", task_stats, elapsed, "exhausted", gemini_attempts)
    print(f"  ❌ FAILED after {gemini_attempts} attempts — flagged for manual review")
    return False


def process_pdf(pdf_path, progress, start_turn=1, start_task=1, end_turn=8,
                skip_dashboard=False, test_setup=False, limit_tasks=0,
                render_preview=False):
    """Process all tasks for a single PDF."""
    pdf_name = os.path.basename(pdf_path)
    doc_short = get_doc_short_name(pdf_name)
    doc_name = os.path.splitext(pdf_name)[0]

    print(f"\n{'═'*70}")
    print(f"  📄 Processing: {pdf_name}")
    print(f"  📁 Short name: {doc_short}")
    print(f"{'═'*70}")

    mode = classify_pdf(pdf_path)
    schema = VARIATION_REGULATORY if mode == "REGULATORY" else VARIATION_TECHNICAL
    print(f"  📊 Classification: {mode}")

    txt_cache = pdf_path.replace(".pdf", ".txt")
    if os.path.exists(txt_cache):
        with open(txt_cache, 'r', encoding='utf-8') as f:
            pdf_text = f.read()
        print(f"  📝 Using cached text: {len(pdf_text)} chars")
    else:
        print(f"  📝 No cached text — Playwright will extract on first run")

    total_pass = 0
    total_fail = 0
    tasks_since_dashboard = 0
    tasks_processed_this_run = 0
    pdf_start = time.time()

    for turn in range(start_turn, end_turn + 1):
        variations = schema[turn]
        for task_idx_0, variation in enumerate(variations):
            task_idx = task_idx_0 + 1
            if turn == start_turn and task_idx < start_task:
                continue

            result = process_task(
                pdf_path, doc_short, doc_name,
                turn, task_idx, variation, mode, progress,
                render_preview=render_preview)

            if result:
                total_pass += 1
            else:
                total_fail += 1

            tasks_since_dashboard += 1
            tasks_processed_this_run += 1

            if test_setup:
                print("\n  [TEST SETUP] Exiting after 1 task.")
                break

            if limit_tasks > 0 and tasks_processed_this_run >= limit_tasks:
                print(f"\n  [LIMIT REACHED] Exiting after {limit_tasks} tasks.")
                break

        if test_setup or (limit_tasks > 0 and tasks_processed_this_run >= limit_tasks):
            break

        # Dashboard every 8 tasks
        if not skip_dashboard and tasks_since_dashboard >= 8:
            try:
                print(f"\n  📊 Generating dashboard...")
                subprocess.run(f'python "{DASHBOARD_SCRIPT}"', shell=True,
                             cwd=BASE_DIR, capture_output=True)
                tasks_since_dashboard = 0
            except Exception:
                pass

    # Final dashboard
    if not skip_dashboard and tasks_since_dashboard > 0:
        try:
            print(f"\n  📊 Generating final dashboard...")
            subprocess.run(f'python "{DASHBOARD_SCRIPT}"', shell=True,
                         cwd=BASE_DIR, capture_output=True)
            if os.path.exists(DASHBOARD_OUTPUT):
                print(f"  🌐 Opening dashboard in browser...")
                webbrowser.open(f'file:///{DASHBOARD_OUTPUT.replace(os.sep, "/")}')
        except Exception:
            pass

    stats_summary = compute_statistics(progress)
    print_statistical_summary(stats_summary, label=pdf_name)

    pdf_elapsed = time.time() - pdf_start
    pdf_min = int(pdf_elapsed // 60)
    pdf_sec = pdf_elapsed % 60
    print(f"\n{'═'*70}")
    print(f"  📄 {pdf_name} COMPLETE: {total_pass}/16 passed, {total_fail}/16 failed")
    print(f"  ⏱️  Elapsed: {pdf_min}m {pdf_sec:.0f}s")
    print(f"{'═'*70}")

    if total_fail == 0:
        progress["pdfs_completed"].append(pdf_name)
        save_progress(progress)

    return total_fail == 0


def validate_only_mode():
    """Just validate all existing JSON files without generating new ones."""
    json_files = sorted(glob.glob(os.path.join(OUTPUT_JSON_DIR, "*.json")))
    if not json_files:
        print("No JSON files found in Output/json/")
        return

    print(f"\n{'═'*70}")
    print(f"  🔍 Validate-Only Mode: {len(json_files)} files")
    print(f"{'═'*70}")

    pass_count = 0
    for jf in json_files:
        qa_path = os.path.join(EVAL_DIR, os.path.basename(jf).replace(".json", "_QA.json"))
        report = run_validation(jf, qa_path)
        status = report.get("overall_status", "?")
        stats = report.get("stats", {})
        icon = "✅" if status == "PASS" else "❌"
        print(f"  {icon} {os.path.basename(jf)}: {status}"
              f"  (CoT: {stats.get('cot_chars', '?')}, Ans: {stats.get('answer_chars', '?')}, "
              f"Type: {stats.get('task_type', '?')})")
        if status == "PASS":
            pass_count += 1
        else:
            for cat, data in report.get("metrics", {}).items():
                for v in data.get("violations", []):
                    print(f"       ⚠️ [{cat}] {v}")

    print(f"\n  Results: {pass_count}/{len(json_files)} passed")


# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AD/ADAS Visual Task Generation Pipeline")
    parser.add_argument("--pdf", help="Process a specific PDF file")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    parser.add_argument("--turn", type=int, default=1, help="Start from turn N")
    parser.add_argument("--end-turn", type=int, default=8, help="End at turn N (inclusive)")
    parser.add_argument("--task", type=int, default=1, help="Start from task K within the turn")
    parser.add_argument("--validate-only", action="store_true", help="Only validate existing outputs")
    parser.add_argument("--limit-tasks", type=int, default=0, help="Stop after N tasks")
    parser.add_argument("--limit-pdfs", type=int, default=0, help="Stop after N PDFs")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard generation")
    parser.add_argument("--test-setup", action="store_true", help="Run 1 task only (test mode)")
    parser.add_argument("--render-preview", action="store_true",
                       help="Auto-open rendered visuals in browser after each successful task")
    parser.add_argument("--require-thinking", action="store_true",
                       help="Strictly validate the presence of internal thinking via Gemini UI")
    args = parser.parse_args()

    global REQUIRE_THINKING
    REQUIRE_THINKING = args.require_thinking

    if args.test_setup:
        args.turn = 2
        args.end_turn = 2
        args.task = 1
        args.limit_pdfs = 1
        global MAX_GEMINI_ATTEMPTS
        MAX_GEMINI_ATTEMPTS = 1

    ensure_dirs()

    if args.validate_only:
        validate_only_mode()
        return

    progress = load_progress()
    start_time = time.time()

    if args.pdf:
        pdf_path = os.path.join(INPUT_DIR, args.pdf) if not os.path.isabs(args.pdf) else args.pdf
        if not os.path.exists(pdf_path):
            print(f"❌ PDF not found: {pdf_path}")
            sys.exit(1)
        pdf_list = [pdf_path]
    else:
        pdf_list = sorted(glob.glob(os.path.join(INPUT_DIR, "*.pdf")))

    if not pdf_list:
        print("❌ No PDFs found in Input/")
        sys.exit(1)

    print(f"\n{'═'*70}")
    print(f"  🚀 Visual Pipeline Starting: {len(pdf_list)} PDFs to process")
    print(f"  📂 Input:  {INPUT_DIR}")
    print(f"  📂 Output: {OUTPUT_JSON_DIR}")
    print(f"  🔄 Max Gemini attempts per task: {MAX_GEMINI_ATTEMPTS}")
    if args.render_preview:
        print(f"  🖼️ Render preview: ENABLED")
    print(f"{'═'*70}")

    if not args.pdf:
        pdf_list = [p for p in pdf_list
                    if os.path.basename(p) not in progress.get("pdfs_completed", [])]
        if not pdf_list:
            print("✅ All PDFs already completed!")
            return

    pdfs_processed = 0
    for pdf_path in pdf_list:
        success = process_pdf(pdf_path, progress,
                   start_turn=args.turn, start_task=args.task,
                   end_turn=args.end_turn, skip_dashboard=args.no_dashboard,
                   test_setup=args.test_setup, limit_tasks=args.limit_tasks,
                   render_preview=args.render_preview)

        if success:
            pdfs_processed += 1

        args.turn = 1
        args.task = 1

        if args.limit_pdfs > 0 and pdfs_processed >= args.limit_pdfs:
            print(f"\n  [LIMIT REACHED] Exiting after processing {pdfs_processed} PDFs.")
            break

    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = elapsed % 60
    completed = len(progress.get("pdfs_completed", []))
    print(f"\n{'═'*70}")
    print(f"  🏁 Pipeline Complete: {completed} PDFs, {minutes}m {seconds:.0f}s elapsed")
    print(f"{'═'*70}")


if __name__ == "__main__":
    main()
