"""
render_preview.py — Visual Task Render Preview
================================================
Opens a rendered version of the generated visual code in the default browser
for manual quality verification.

Supports: HTML, PlantUML, Graphviz DOT, D2, Mermaid, TikZ, SVG

Usage:
    python render_preview.py <json_filepath>
    python render_preview.py <json_filepath> --task-type html_tool
"""
import sys
import json
import os
import tempfile
import webbrowser
import re
import urllib.request
import urllib.error

def log(msg):
    print(f"  [RenderPreview] {msg}", file=sys.stderr)


def extract_rendered_code(filepath):
    """Extract the rendered_code from the task JSON."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        log(f"Cannot read JSON: {e}")
        return None, None

    if not isinstance(data, list) or len(data) == 0:
        log("Invalid JSON structure")
        return None, None

    task = data[0]
    task_type = task.get("task_type", "unknown")
    convs = task.get("conversations", [])
    if len(convs) < 2:
        log("Not enough conversation turns")
        return None, None

    content = convs[1].get("content", "")
    try:
        parsed = json.loads(content)
        code = parsed.get("rendered_code", "")
    except (json.JSONDecodeError, TypeError):
        # Try to extract code blocks from raw content
        code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', content, re.DOTALL)
        code = max(code_blocks, key=len) if code_blocks else content

    # Unescape the code (JSON string escaping)
    code = code.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')

    return code, task_type


def fetch_kroki_svg(code, diag_type):
    import urllib.request
    try:
        req = urllib.request.Request(
            f"https://kroki.io/{diag_type}/svg", 
            data=code.encode('utf-8'), 
            headers={'User-Agent': 'Mozilla/5.0', 'Content-Type': 'text/plain'}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        return f"<div style='color: #ff6b6b; padding: 1rem; font-family: monospace;'>Kroki Render Error ({diag_type}): {e}<br><br><pre style='color: #a0a0a0; white-space: pre-wrap;'>{code.replace('<', '&lt;').replace('>', '&gt;')}</pre></div>"

def wrap_in_html(code, task_type, title="Visual Preview"):
    """Wrap non-HTML code in an HTML template for browser rendering."""
    
    # 1. Clean up leading garbage (often injected by the VT100 prompt constraint)
    # Remove things like "// Copyright by 4QDR.AI..." and "HTML\n" at the top
    code = re.sub(r'^(?://.*?|#.*?|HTML|SVG|```.*?)\s*[\n\r]', '', code.lstrip(), count=5, flags=re.IGNORECASE | re.MULTILINE)
    code = code.lstrip()

    # 2. Smart type inference if task_type is generic (caused by auto_repair)
    if task_type in ("visual_task", "unknown"):
        if code.lower().startswith("<!doctype html") or code.lower().startswith("<html"):
            task_type = "html_tool"
        elif code.lower().startswith("<svg") or "<svg " in code[:500].lower():
            task_type = "svg_generation"
        elif "digraph " in code[:500] or "graph " in code[:100]:
            task_type = "graphviz_dot"
        elif "@startuml" in code[:500]:
            task_type = "plantuml_diagram"
        elif code.startswith("graph ") or code.startswith("sequenceDiagram") or code.startswith("flowchart"):
            task_type = "mermaid_diagram"
        elif "direction:" in code[:500] or "classes:" in code[:500] or "shape:" in code[:500]:
            task_type = "d2_diagram"

    if task_type in ("html_tool", "html_presentation"):
        # HTML is already renderable
        if "<!doctype html" in code.lower() or "<html" in code.lower():
            # Extract from <!DOCTYPE to the end in case of remaining garbage
            match = re.search(r'(<!DOCTYPE html.*|<html.*)', code, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1), task_type
        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{title}</title></head>
<body>{code}</body>
</html>""", task_type

    if task_type == "svg_generation":
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title} — SVG Preview</title>
<style>
  body {{ background: #1a1a2e; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }}
  .svg-container {{ background: white; padding: 2rem; border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.3); width: 90vw; height: 90vh; overflow: auto; display: flex; justify-content: center; align-items: center; }}
  .svg-container svg {{ width: 100%; height: 100%; max-width: 100%; max-height: 100%; }}
</style>
</head>
<body>
<div class="svg-container">
{code}
</div>
</body>
</html>""", task_type

    if task_type == "mermaid_diagram":
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title} — Mermaid Preview</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
  body {{ background: #0f0f23; display: flex; justify-content: center; padding: 2rem; margin: 0; font-family: 'Inter', sans-serif; }}
  .mermaid {{ background: white; padding: 2rem; border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.3); max-width: 95vw; overflow: auto; }}
  h1 {{ color: #e0e0e0; text-align: center; margin-bottom: 1rem; }}
</style>
</head>
<body>
<div>
<h1>{title}</h1>
<div class="mermaid">
{code}
</div>
</div>
<script>mermaid.initialize({{ startOnLoad: true, theme: 'default' }});</script>
</body>
</html>""", task_type

    if task_type == "plantuml_diagram":
        svg_content = fetch_kroki_svg(code, "plantuml")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title} — PlantUML Preview</title>
<style>
  body {{ background: #1a1a2e; margin: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; }}
  .svg-container {{ background: white; padding: 2rem; border-radius: 12px; width: 90vw; height: 90vh; overflow: auto; display: flex; justify-content: center; align-items: center; box-shadow: 0 8px 32px rgba(0,0,0,0.3); }}
  .svg-container svg {{ width: 100%; height: 100%; max-width: 100%; max-height: 100%; }}
  h1 {{ color: #7c83ff; font-family: monospace; position: absolute; top: 1rem; }}
</style>
</head>
<body>
<div class="svg-container">{svg_content}</div>
</body>
</html>""", task_type

    if task_type == "graphviz_dot":
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title} — Graphviz DOT Preview</title>
<script src="https://cdn.jsdelivr.net/npm/@viz-js/viz@3/lib/viz-standalone.js"></script>
<style>
  body {{ background: #0f0f23; display: flex; flex-direction: column; align-items: center; padding: 2rem; margin: 0; }}
  #graph {{ background: white; padding: 2rem; border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.3); max-width: 95vw; overflow: auto; margin-top: 1rem; }}
  h1 {{ color: #e0e0e0; font-family: 'Inter', sans-serif; }}
  .error {{ color: #ff6b6b; padding: 1rem; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div id="graph">Rendering...</div>
<script>
Viz.instance().then(viz => {{
  try {{
    const svg = viz.renderSVGElement(`{code.replace('`', '\\`').replace('${', '\\${')}`);
    document.getElementById('graph').innerHTML = '';
    document.getElementById('graph').appendChild(svg);
  }} catch(e) {{
    document.getElementById('graph').innerHTML = '<div class="error">Render Error: ' + e.message + '</div>';
  }}
}});
</script>
</body>
</html>""", task_type

    if task_type == "d2_diagram":
        svg_content = fetch_kroki_svg(code, "d2")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title} — D2 Preview</title>
<style>
  body {{ background: #1a1a2e; margin: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; }}
  .svg-container {{ background: white; padding: 2rem; border-radius: 12px; width: 90vw; height: 90vh; overflow: auto; display: flex; justify-content: center; align-items: center; box-shadow: 0 8px 32px rgba(0,0,0,0.3); }}
  .svg-container svg {{ width: 100%; height: 100%; max-width: 100%; max-height: 100%; }}
</style>
</head>
<body>
<div class="svg-container">{svg_content}</div>
</body>
</html>""", task_type

    if task_type == "tikz_pgfplots":
        svg_content = fetch_kroki_svg(code, "tikz")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title} — TikZ Preview</title>
<style>
  body {{ background: #1a1a2e; margin: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; }}
  .svg-container {{ background: white; padding: 2rem; border-radius: 12px; width: 90vw; height: 90vh; overflow: auto; display: flex; justify-content: center; align-items: center; box-shadow: 0 8px 32px rgba(0,0,0,0.3); }}
  .svg-container svg {{ width: 100%; height: 100%; max-width: 100%; max-height: 100%; }}
</style>
</head>
<body>
<div class="svg-container">{svg_content}</div>
</body>
</html>""", task_type

    # Fallback: show as code
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><title>{title}</title>
<style>body {{ background: #1a1a2e; color: #e0e0e0; padding: 2rem; font-family: monospace; }} pre {{ white-space: pre-wrap; }}</style>
</head>
<body><h1>{title}</h1><pre>{code.replace('<', '&lt;').replace('>', '&gt;')}</pre></body>
</html>""", task_type


def render_preview(filepath, task_type_override=None):
    """Extract visual code from JSON, render to temp HTML, open in browser."""
    code, task_type = extract_rendered_code(filepath)
    if not code:
        log("No rendered code found in task JSON")
        return False

    if task_type_override:
        task_type = task_type_override

    basename = os.path.splitext(os.path.basename(filepath))[0]
    html_content, task_type = wrap_in_html(code, task_type, title=basename)

    # Write to temp file
    preview_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                               "Output", "previews")
    os.makedirs(preview_dir, exist_ok=True)
    preview_path = os.path.join(preview_dir, f"{basename}_preview.html")

    with open(preview_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    log(f"Preview saved to: {preview_path}")
    log(f"Opening in browser (task_type: {task_type})...")

    webbrowser.open(f"file:///{preview_path.replace(os.sep, '/')}")
    return True


def main():
    if len(sys.argv) < 2:
        log("Usage: python render_preview.py <json_filepath> [--task-type TYPE]")
        sys.exit(1)

    filepath = sys.argv[1]
    task_type_override = None
    if "--task-type" in sys.argv:
        idx = sys.argv.index("--task-type")
        if idx + 1 < len(sys.argv):
            task_type_override = sys.argv[idx + 1]

    success = render_preview(filepath, task_type_override)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
