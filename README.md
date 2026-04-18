# Agentic Workflow Data Generation: Visual Tasks Pipeline

Automated pipeline for generating massive datasets of Visual Training Tasks strictly guided by complex Problem Formulation and LLM interaction via Playwright Automation.

This repository orchestrates the end-to-end generation of structural and visual tasks using Gemini over a browser-based workflow, guaranteeing deep logical reasoning (CoT), structural JSON compliance, and scalable data-synthesis.

## Features
- **Visual Output Engines**: Full autonomous orchestration for generating D2 Diagrams, PlantUML, Mermaid, Graphviz DOT, TikZ/PGFPlots, SVG native rendering, and raw HTML tools.
- **Agentic Playwright Engine**: Navigates the Google Gemini UI to sidestep API rate limits and exploit native Web UI features (while effectively suppressing Canvas mode interference).
- **Auto-Repair Subsystems**: Deploys localized AST and Regex repairing pipelines to salvage incomplete/malformed metadata.
- **Intelligent Previews**: Secure local rendering using `Kroki.io` backend to visualize generated PlantUML, D2, and TikZ graphs autonomously during batch processing.

## Installation Guideline

1. **Clone the repository:**
   ```bash
   git clone https://github.com/sfreedoms2035/-AgenticWorkflowDataGenerationVisualTasks.git
   cd -AgenticWorkflowDataGenerationVisualTasks
   ```

2. **Setup your environment:**
   We strongly recommend using a dedicated virtual environment or Conda environment.
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Requirements:**
   Install pip dependencies specifically tuned for the Playwright engine and JSON manipulation (including `json-repair` for robust parsing).
   ```bash
   pip install -r requirements.txt
   ```

   **Manual Installation:**
   If you need to install the core JSON repair library manually:
   ```bash
   pip install json-repair
   ```

4. **Initialize Playwright:**
   Install the required Chromium binaries required by Playwright to navigate the Gemini Web UI.
   ```bash
   playwright install chromium
   ```

## Pipeline Execution

The primary entry point is the Pipeline Orchestrator. 

To start the pipeline generation tasks (placing PDFs into the `Input/` folder):
```bash
python pipeline.py
```

To resume the pipeline where it left off, and securely render visual tasks dynamically in your browser:
```bash
python pipeline.py --resume --render-preview
```

### Folder Structure
- `Input/`: Place your source PDF datasets here.
- `Output/json/`: Pipeline drops final validated Agentic Datasets here compliant with internal schemas.
- `Output/previews/`: Stores localized HTML previews of Visual Tasks.
- `.agent/scripts/`: Tooling, repair heuristics, SVG rendering workflows, and validation gates.

## Disclaimer & Terms
Internal Agentic Toolkit. Designed for robust visual task dataset synthesis via generative AI endpoints.


### Terms Mode and Deep Think Mode

**To use Terms Mode (generates tasks based on autonomous driving terms instead of PDFs):**
Place your terms list in `Input_terms/Terms.md`.
```bash
python pipeline.py --terms-mode
```

**To enable the Deep Think model (e.g., Gemini 2.0 Flash Thinking / Gemini Thinking):**
Can be combined with any mode to enable advanced reasoning capabilities.
```bash
python pipeline.py --deep-think
python pipeline.py --terms-mode --deep-think
```
