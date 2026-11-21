"""Tests for the bundled read-console.py predefined script"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import test_imports  # Automatic path setup
from server.mcp_tools import describe_predefined_scripts

SCRIPT = Path(__file__).resolve().parents[2] / "predefined-ex" / "read-console.py"


def run(*arguments):
    return subprocess.run([sys.executable, str(SCRIPT), *arguments],
                          capture_output=True, text=True, timeout=30)


def embedded_arguments(output):
    """The argument list the script put into the JavaScript it printed"""
    line = next(line for line in output.splitlines() if "] = [" in line)
    return json.loads(line.split("] = ", 1)[1].rstrip(";"))


def test_without_arguments_it_reads_the_last_50_entries_of_any_level():
    result = run()

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("(() => {")
    assert embedded_arguments(result.stdout) == [None, None, 50, False]


def test_arguments_reach_the_generated_script():
    result = run("--level", "error", "--pattern", 'say "hi"', "--limit", "7", "--clear")

    assert result.returncode == 0, result.stderr
    assert embedded_arguments(result.stdout) == ["error", 'say "hi"', 7, True]


@pytest.mark.parametrize("arguments", [
    ["--limit", "0"], ["--limit", "501"], ["--limit", "many"], ["--level", "trace"],
    ["--unknown"],
])
def test_bad_arguments_exit_with_a_usage_message(arguments):
    result = run(*arguments)

    assert result.returncode != 0
    assert "read-console.py" in result.stderr
    assert result.stdout == ""


def test_the_script_is_listed_with_its_description(tmp_path):
    listing = describe_predefined_scripts(str(SCRIPT.parent))

    assert "read-console.py [--level" in listing
    assert "Read what the page logged to its console" in listing
