"""No API key may ever be part of the repository: callers of the LLM parser use their own."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def tracked_files_containing(text):
    result = subprocess.run(["git", "grep", "-lI", text], cwd=ROOT, capture_output=True, text=True)
    if result.returncode not in (0, 1):  # 1 means nothing found
        pytest.skip("not a git repository")
    return result.stdout.split()


# Built from two parts so that this file does not match itself.
KEY_PREFIX = "sk" + "-ant-"


def test_no_tracked_file_contains_an_anthropic_api_key():
    assert tracked_files_containing(KEY_PREFIX) == []
