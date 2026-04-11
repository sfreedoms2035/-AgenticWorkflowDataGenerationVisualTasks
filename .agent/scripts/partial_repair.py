"""
partial_repair.py — Targeted Follow-Up Turn Repair (Visual Tasks)
===================================================================
Regenerates only the follow-up turns (indices 2-5) when the main answer
(Turn 1 Q&A) is valid but the follow-up turns have issues.

Sends a focused prompt to Gemini with context from the valid Turn 1,
asking it to generate only the 4 follow-up turns.

Usage:
    python partial_repair.py <json_filepath>
"""
import sys
import json
import os
import subprocess
import re
import tempfile


def log(msg):
    print(f"  [PartialRepair] {msg}", file=sys.stderr)


def build_partial_repair_prompt(task):
    """Build a focused prompt to regenerate only follow-up turns."""
    convs = task.get("conversations", [])
    if len(convs) < 2:
        return None

    # Extract context from valid Turn 1
    user_prompt = convs[0].get("content", "")
    assistant_content = convs[1].get("content", "")
    task_type = task.get("task_type", "visual_task")
    role = task.get("affected_role", "Senior Engineer")

    # Extract a short summary of the visual solution
    try:
        parsed = json.loads(assistant_content)
        spec = parsed.get("technical_visual_specification", "")[:500]
    except (json.JSONDecodeError, TypeError):
        spec = assistant_content[:500]

    prompt = f"""You are a {role} in a real-world engineering conversation. You have already received 
a complex visual/architectural task and provided a comprehensive solution.

CONTEXT — The original problem:
{user_prompt[:1000]}

CONTEXT — Summary of your solution:
{spec}

NOW: Generate exactly 4 follow-up conversation turns to complete this dialogue.
The turns must follow this exact structure:

Turn 3 (User, [No Thinking]): A highly technical follow-up question referencing SPECIFIC named 
components, nodes, clusters, or code identifiers from the solution above. Must be ≥100 characters.

Turn 4 (Assistant, reasoning="<think></think>"): A detailed technical response addressing the 
specific question. Must be genuine engineering content, not a placeholder.

Turn 5 (User, [No Thinking]): Another technical follow-up probing scalability, rendering limits, 
integration, or edge cases of the visual solution. Must be ≥100 characters.

Turn 6 (Assistant, reasoning="<think></think>"): A detailed technical response. Must be genuine.

CRITICAL RULES:
- Write ONLY the 4 turns, NOT the full task JSON
- Follow-up questions MUST reference specific named elements from the solution
- Do NOT echo any template text or placeholders
- Do NOT use banned vocabulary: "the user requests", "the document says", "source material"
- Write in-character as senior engineers having a real technical discussion

Output format — raw JSON array of exactly 4 objects:
[
  {{"role": "user", "content": "[No Thinking] Your specific question..."}},
  {{"role": "assistant", "reasoning": "<think></think>", "content": "Your detailed response..."}},
  {{"role": "user", "content": "[No Thinking] Your second question..."}},
  {{"role": "assistant", "reasoning": "<think></think>", "content": "Your detailed response..."}}
]
"""
    return prompt


def apply_partial_repair(filepath, new_turns):
    """Replace turns 2-5 in the JSON with new follow-up turns."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        log(f"Cannot read JSON: {e}")
        return False

    if not isinstance(data, list) or len(data) == 0:
        return False

    task = data[0]
    convs = task.get("conversations", [])
    if len(convs) < 2:
        return False

    # Keep turns 0-1 (original Q&A), replace 2-5
    convs = convs[:2] + new_turns[:4]

    # Ensure we have exactly 6 turns, pad if needed
    while len(convs) < 6:
        if len(convs) % 2 == 0:
            convs.append({
                "role": "user",
                "content": "[No Thinking] How does this handle edge-case rendering?"
            })
        else:
            convs.append({
                "role": "assistant",
                "reasoning": "<think></think>",
                "content": "The architecture handles this through hierarchical clustering."
            })

    task["conversations"] = convs
    data[0] = task

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    log(f"Applied partial repair to {os.path.basename(filepath)}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        log("Usage: python partial_repair.py <json_filepath>")
        sys.exit(1)

    filepath = sys.argv[1]
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        task = data[0]
        prompt = build_partial_repair_prompt(task)
        if prompt:
            log(f"Partial repair prompt length: {len(prompt)} chars")
            log("Prompt built. Use pipeline.py to execute via Playwright.")
        else:
            log("Cannot build partial repair prompt — insufficient data")
    except Exception as e:
        log(f"Error: {e}")
        sys.exit(1)
