import os
import re
import ast
from pathlib import Path

ROOT_DIR = r"c:\Users\khars\PycharmProjects\scratch\centrag"

def refactor_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if "import structlog" not in content:
            return

        # Simple initial import replacement
        new_content = re.sub(r'^import structlog[ \t]*\n', 'from centrag.utils.logger import get_logger\n', content, flags=re.MULTILINE)

        # Balanced parens locator to cleanly scoop out structlog.get_logger arguments even over multiple lines
        idx = 0
        while True:
            match = re.search(r'(?P<var>logger|log)\s*=\s*structlog\.get_logger\(', new_content[idx:])
            if not match:
                break
                
            start_pos = idx + match.end() - 1  # points to the '('
            paren_count = 1
            i = start_pos + 1
            while i < len(new_content) and paren_count > 0:
                if new_content[i] == '(': paren_count += 1
                elif new_content[i] == ')': paren_count -= 1
                i += 1
                
            if paren_count == 0:
                # We found the matched block
                end_pos = i
                inner_args = new_content[start_pos+1:end_pos-1]
                
                var_name = match.group("var")
                # Replace the exact substring
                segment_to_replace = match.group(0) + inner_args + ")"
                replacement = f"{var_name} = get_logger({inner_args})"
                
                # We replace exactly from idx+match.start() to end_pos
                global_start = idx + match.start()
                new_content = new_content[:global_start] + replacement + new_content[global_start + len(segment_to_replace):]
                
                idx = global_start + len(replacement)
            else:
                idx += match.end()

        if new_content != content:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"Refactored: {filepath}")
    except Exception as e:
        print(f"Failed to process {filepath}: {e}")

for root, _, files in os.walk(ROOT_DIR):
    # Only skip literal "utils" directory components (rather than substrings)
    if "utils" in Path(root).parts:
        continue
        
    for file in files:
        if file.endswith(".py"):
            filepath = os.path.join(root, file)
            refactor_file(filepath)
