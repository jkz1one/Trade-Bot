import importlib.util
from pathlib import Path
import pytest


def loader():
    p = Path(__file__).parents[1] / "scripts/paper-session-start.py"
    spec = importlib.util.spec_from_file_location("paper_start_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_exact_reviews_flow_to_enrollment_and_run(tmp_path):
    calls = []
    def invoke(args):
        calls.append(args)
        return {"review_sha256": args[0] + "-hash", "degen_option_configuration_ready": True}
    loader().launch("/captures", "2026-10-28", "paper-first", 600,
                    invoke=invoke, session_root=tmp_path, today="2026-10-28")
    assert [c[0] for c in calls] == ["prepare-session", "review-session", "enroll-session", "review-run", "run"]
    assert calls[2][-1] == "review-session-hash"
    assert calls[-1][-1] == "review-run-hash"
    assert "--resume-flat" in calls[-1]
    with pytest.raises(FileExistsError):
        loader().launch("/captures", "2026-10-28", "paper-first", 600,
                        invoke=invoke, session_root=tmp_path, today="2026-10-28")


def test_not_ready_never_launches(tmp_path):
    calls = []
    def invoke(args):
        calls.append(args[0])
        return {"review_sha256": "hash", "degen_option_configuration_ready": False}
    with pytest.raises(ValueError, match="still blocked"):
        loader().launch("/captures", "2026-10-28", "blocked", 600,
                        invoke=invoke, session_root=tmp_path, today="2026-10-28")
    assert "run" not in calls
