import os
import subprocess
from pathlib import Path


def test_prepare_generates_private_independent_password_without_overwriting_files(tmp_path):
    script = Path("scripts/shadow-server.sh").read_text()
    script = script.replace("/var/lib/trade-bot", str(tmp_path / "state"))
    script = script.replace("/etc/trade-bot", str(tmp_path / "credentials"))
    script = script.replace("/root/trade-bot-bootstrap", str(tmp_path / "bootstrap"))
    # Map server root/UID ownership to the test user; this workspace cannot chown
    # unmapped container UIDs. Generation, modes and repeat preparation still run.
    script = script.replace('"$EUID"', '"0"')
    script = script.replace("-o 10001 -g 10001", f"-o {os.geteuid()} -g {os.getegid()}")
    script = script.replace("chown 10001:10001", f"chown {os.geteuid()}:{os.getegid()}")
    target = tmp_path / "scripts" / "shadow-server.sh"
    target.parent.mkdir()
    target.write_text(script)
    first = subprocess.run(
        ["bash", str(target), "prepare"], capture_output=True, text=True, check=True
    )
    password_path = tmp_path / "credentials" / "dashboard_password"
    password = password_path.read_text()
    assert len(password) == 64 and all(c in "0123456789abcdef" for c in password)
    assert password_path.stat().st_mode & 0o777 == 0o600
    assert password_path.stat().st_uid == os.geteuid()
    assert password not in first.stdout + first.stderr
    key = password_path.parent / "openai_api_key"
    key.write_text("existing-private-test-key")
    subprocess.run(["bash", str(target), "prepare"], capture_output=True, text=True, check=True)
    assert password_path.read_text() == password
    assert key.read_text() == "existing-private-test-key"
