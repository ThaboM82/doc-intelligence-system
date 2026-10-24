import os
import re

PATTERNS = {
    "OpenAI API Key": re.compile(r"sk-(proj-|service-[a-zA-Z0-9-_])?[a-zA-Z0-9-_]{20,}"),
    "Stripe Key": re.compile(r"(rk|sk)_(live|test)_[0-9a-zA-Z]{24,}"),
    "AWS Access Key ID": re.compile(r"AKIA[0-9A-Z]{16}"),
    "Generic Secret / Token": re.compile(r"(api_key|secret|token|password)\s*[:=]\s*['\"'][a-zA-Z0-9_\-\.]{16,}['\"]", re.IGNORECASE),
}

def scan_directory(directory):
    print(f"Scanning '{directory}' for hardcoded secrets...")
    match_count = 0
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith((".py", ".json", ".yml", ".yaml", ".env")):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            for name, pattern in PATTERNS.items():
                                if pattern.search(line):
                                    match_count += 1
                                    print(f"[{name}] Found in {filepath} (Line {line_num})")
                                    print(f"  -> {line.strip()}")
                except Exception:
                    pass
    print(f"Scan complete for '{directory}'. Total potential matches found: {match_count}\n")

if __name__ == "__main__":
    scan_directory("tests")
    scan_directory("backend")
