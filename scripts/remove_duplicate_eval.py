"""Script to remove duplicate Eval Dashboard endpoints from main.py"""
import sys

file_path = "/Users/cengjiguang/Desktop/work/edu-agent-platform/backend/api/main.py"

with open(file_path, "r") as f:
    lines = f.readlines()

# Find line numbers of the duplicate section
start_line = None
end_line = None
for i, line in enumerate(lines):
    if "# --- Eval Dashboard ---" in line and start_line is None:
        start_line = i
    if start_line is not None and i > start_line and "@app.get(\"/api/history/games\")" in line:
        end_line = i
        break

if start_line is not None and end_line is not None:
    # Remove lines from start_line to end_line (inclusive)
    new_lines = lines[:start_line] + lines[end_line+1:]
    with open(file_path, "w") as f:
        f.writelines(new_lines)
    print(f"Removed lines {start_line} to {end_line} from {file_path}")
else:
    print("Could not find the duplicate section")
