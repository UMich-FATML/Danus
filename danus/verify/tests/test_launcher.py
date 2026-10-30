"""Offline verifier launch, output, concurrency and fail-closed tests."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException
from danus import dsh
from danus.verify import launcher
from danus.tests.test_dsh import events, stub

_STMT = "For every integer n, n + 0 equals n."
_PROOF = "Zero is the additive identity; adding it changes nothing, so n + 0 = n."


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIFIER_RESULTS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("DANUS_VERIFY_TIMEOUT_SECONDS", "0")
    return tmp_path


def launch(service, monkeypatch, body, rid="RID"):
    monkeypatch.setenv("DANUS_DSH_BIN", str(stub(service, body)))
    return launcher.run_dsh_verification(rid, _STMT, _PROOF)


def writing(body):
    return "import sys,json,re\nfrom pathlib import Path\nprompt=sys.stdin.read()\nout=Path(re.search(r'this exact path: (.+)\\.$', prompt).group(1))\n" + body + "\n" + f"sys.stdout.write({events()!r})\n"


def test_success_unique_output_cwd_and_gateway(service, monkeypatch):
    body = writing("assert out.parent==Path.cwd()\nassert (Path.cwd()/'VERIFIER.md').is_file()\nout.write_text(json.dumps({'verdict':'correct','verification_report':{'critical_errors':[],'gaps':[]}}))")
    result = launch(service, monkeypatch, body)
    assert result["verdict"] == "correct"
    metadata = json.loads((launcher._results_dir("RID") / "session.json").read_text())
    assert metadata["session_id"] == "test-session"
    root = Path(__import__('os').environ['DANUS_DSH_RUNS_DIR'])
    overlay = json.loads((root / metadata['run_id'] / 'site.patch.json').read_text())
    gateway = next(r for r in overlay if 'insert' in r)['insert'][0]['config']
    assert gateway['command'] == sys.executable and gateway['env']['DANUS_ROLE'] == 'verifier'
    assert gateway['cwd'] == str(launcher._results_dir('RID'))


@pytest.mark.parametrize("body,status,needle", [
    ("import sys;sys.stdin.read();sys.exit(7)",500,"exit code 7"),
    ("import time;time.sleep(60)",504,"timed out"),
    (f"import sys;sys.stdin.read();sys.stdout.write({events()!r})",500,"was not found"),
    (writing("out.write_text('{ invalid')"),500,"not valid JSON"),
    (writing("out.write_text('[]')"),500,"must be a JSON object"),
    (writing("out.write_text('{}')").replace('completed','cancelled'),500,"cancelled"),
])
def test_error_mapping(service, monkeypatch, body, status, needle):
    monkeypatch.setenv("DANUS_VERIFY_TIMEOUT_SECONDS", "1")
    with pytest.raises(HTTPException) as exc:
        launch(service, monkeypatch, body)
    assert exc.value.status_code == status and needle in exc.value.detail


def test_allocate_concurrently_never_clobbers(service, monkeypatch):
    monkeypatch.setattr(launcher, "generate_run_id", lambda s: "same")
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(launcher._allocate_run_id, ["s"] * 20))
    assert len(set(ids)) == 20
    assert "same" in ids and "same_2" in ids


def test_verification_alias_and_reused_run_refusal(service, monkeypatch):
    run_dir = launcher._results_dir("RID")
    run_dir.mkdir(parents=True)
    assert launcher._verification_path("RID") is None
    (run_dir / "verificationt.json").write_text("{}")
    assert launcher._verification_path("RID").name == "verificationt.json"
    with pytest.raises(HTTPException, match="already has output"):
        launcher.run_dsh_verification("RID", _STMT, _PROOF)


def test_run_id_cannot_escape_results(service):
    with pytest.raises(ValueError):
        launcher._results_dir("../../outside")
