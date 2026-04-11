"""
json_aggregator.py — Training Data ID Normalizer (Visual Tasks)
================================================================
Post-processing script that normalizes training_data_id fields
across all generated visual task JSON files.

Format: TD-VIS-{STD_CODE}-T{N}t{K}-{DATE}-v{VER}

Usage:
    python json_aggregator.py
    python json_aggregator.py --output-dir Output/json
"""
import os
import sys
import json
import re
import datetime
import glob


# Standard code mapping from document patterns
STD_CODE_MAP = {
    r"iso.?pas.?8800": "PAS8800",
    r"iso.?sae.?21434": "SAE21434",
    r"iso.?21448": "SOTIF21448",
    r"iso.?26262": "FUSI26262",
    r"iso.?8855": "VD8855",
    r"iso.?4804": "RSDL4804",
    r"iso.?34502": "SCEN34502",
    r"ul.?4600": "UL4600",
    r"sae.?j3016": "SAEJ3016",
    r"vda": "VDA",
    r"unece": "UNECE",
    r"nist": "NIST",
}


def get_std_code(doc_name):
    """Extract ISO/standard short code from document name."""
    doc_lower = doc_name.lower()
    for pattern, code in STD_CODE_MAP.items():
        if re.search(pattern, doc_lower):
            return code
    # Fallback: use first word after cleaning
    clean = re.sub(r'[^a-zA-Z0-9]', '', doc_name)
    return clean[:10] if clean else "UNKNOWN"


def get_model_name():
    """Resolve model name from environment or use default."""
    return os.environ.get("MODEL_NAME", "Gemini-3.1-pro")


def normalize_ids(output_dir=None):
    """Walk all JSON files and normalize training_data_id."""
    if output_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.dirname(os.path.dirname(script_dir))
        output_dir = os.path.join(project_dir, "Output", "json")

    json_files = glob.glob(os.path.join(output_dir, "*.json"))
    print(f"Found {len(json_files)} JSON files in {output_dir}")

    updated_count = 0
    for filepath in json_files:
        filename = os.path.basename(filepath)

        # Parse Turn and Task from filename
        match = re.search(r'(.+)_Turn(\d+)_Task(\d+)\.json', filename)
        if not match:
            print(f"  Skipping (no match): {filename}")
            continue

        doc_short = match.group(1)
        turn = int(match.group(2))
        task = int(match.group(3))

        std_code = get_std_code(doc_short)
        today = datetime.date.today().strftime("%Y%m%d")

        new_id = f"TD-VIS-{std_code}-T{turn}t{task}-{today}-v1.2"

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, list) and len(data) > 0:
                task_obj = data[0]
                old_id = task_obj.get("training_data_id", "")
                task_obj["training_data_id"] = new_id
                task_obj["prompt_version"] = "VisualTasks_v1.2"
                task_obj["model_used_generation"] = get_model_name()

                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)

                print(f"  ✅ {filename}: {old_id} → {new_id}")
                updated_count += 1
        except Exception as e:
            print(f"  ❌ {filename}: {e}")

    print(f"\nUpdated {updated_count}/{len(json_files)} files.")


if __name__ == "__main__":
    output_dir = None
    if "--output-dir" in sys.argv:
        idx = sys.argv.index("--output-dir")
        if idx + 1 < len(sys.argv):
            output_dir = sys.argv[idx + 1]
    normalize_ids(output_dir)
