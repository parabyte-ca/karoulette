"""setup.sh and update.sh write .env through scripts/lib.sh: values must reach the app exactly as typed."""
import shutil
import subprocess
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[2] / "scripts" / "lib.sh"
TRICKY = ["plain-1234", "ab$cd1234", "tab\\tnot\\nnewline", "two words # not a comment", 'say "hi"$', "50%off!"]


def bash(env_file: Path, script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f'source "{LIB}"; ENV_FILE="{env_file}"; {script}'],
                          capture_output=True, text=True)


def set_values(env_file: Path, values: dict[str, str]) -> None:
    for key, value in values.items():
        res = subprocess.run(["bash", "-c", f'source "{LIB}"; ENV_FILE="{env_file}"; set_env "$1" "$2"', "_", key, value],
                             capture_output=True, text=True)
        assert res.returncode == 0, res.stderr


def test_values_round_trip_through_set_env_and_get_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("KQ_PORT=8095\n")
    values = {f"V{i}": v for i, v in enumerate(TRICKY)}
    set_values(env, values)
    for key, value in values.items():
        assert bash(env, f"get_env {key}").stdout == value
    assert "KQ_PORT=8095\n" in env.read_text()  # plain values stay unquoted, so older readers still work
    assert "V0=plain-1234\n" in env.read_text()


def test_values_it_cannot_write_are_refused(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    for bad in ("it's", "ends\\"):
        res = subprocess.run(["bash", "-c", f'source "{LIB}"; ENV_FILE="{env}"; set_env HOST_PIN "$1"', "_", bad],
                             capture_output=True, text=True)
        assert res.returncode != 0 and "single quote" in res.stderr
    assert env.read_text() == ""


def test_update_quotes_a_secret_typed_without_quotes(tmp_path):
    env = tmp_path / ".env"
    env.write_text("HOST_PIN=ab$cd1234\nKQ_PORT=8095\nSECRET_KEY=abc123\n")
    res = bash(env, "quote_secrets")
    assert res.returncode == 0 and "HOST_PIN put in single quotes" in res.stdout
    assert env.read_text() == "HOST_PIN='ab$cd1234'\nKQ_PORT=8095\nSECRET_KEY=abc123\n"
    assert bash(env, "quote_secrets").stdout == ""  # already quoted: left alone


@pytest.mark.skipif(not shutil.which("docker") or subprocess.run(["docker", "compose", "version"],
                    capture_output=True).returncode, reason="needs Docker Compose")
def test_docker_compose_reads_them_as_typed(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    values = {f"V{i}": v for i, v in enumerate(TRICKY)}
    set_values(env, values)
    (tmp_path / "compose.yml").write_text("services:\n  t:\n    image: busybox\n    env_file: [.env]\n")
    out = subprocess.run(["docker", "compose", "config", "--format", "json"], cwd=tmp_path,
                         capture_output=True, text=True, check=True).stdout
    import json
    seen = json.loads(out)["services"]["t"]["environment"]
    # compose config escapes a literal $ as $$ in its output; the container gets a single $
    assert {k: v.replace("$$", "$") for k, v in seen.items()} == values
