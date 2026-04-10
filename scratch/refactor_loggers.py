import os
import re

ROOT_DIR = r"c:\Users\khars\PycharmProjects\scratch\centrag"

def refactor_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if "import structlog" not in content:
        return

    # Replace 'import structlog' with 'from centrag.utils.logger import get_logger'
    new_content = re.sub(r'^import structlog[ \t]*\n', 'from centrag.utils.logger import get_logger\n', content, flags=re.MULTILINE)
    
    # Replace 'logger = structlog.get_logger(...)' or 'log = structlog.get_logger()'
    new_content = re.sub(r'(logger|log)\s*=\s*structlog\.get_logger\((.*?)\)', r'\1 = get_logger(\2)', new_content)

    if new_content != content:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Refactored: {filepath}")

for root, _, files in os.walk(ROOT_DIR):
    for file in files:
        if file.endswith(".py") and "utils" not in root:
            filepath = os.path.join(root, file)
            refactor_file(filepath)
