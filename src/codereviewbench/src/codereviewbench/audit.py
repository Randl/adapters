"""Runtime isolation probe, usable directly or inside a Harbor audit agent."""

import json
import os
import socket
from pathlib import Path


def audit() -> dict:
    assert os.getuid() != 0, "Agent must not run as root"
    repo = Path("/workspace/repo")
    assert repo.is_dir()
    assert not list(repo.rglob(".git")), "Git metadata leaked"
    for path in (
        "/checkout",
        "/snapshot",
        "/head.tar",
        "/tests",
        "/solution",
        "/var/run/docker.sock",
        "/root/.ssh",
        "/root/.aws",
    ):
        assert not os.path.lexists(path), f"Private/build asset exposed: {path}"
    for key in os.environ:
        assert not any(token in key for token in ("API_KEY", "AUTH_TOKEN", "SECRET")), (
            f"Credential variable exposed: {key}"
        )
    assert not os.access(repo, os.W_OK), "Source directory must be read-only to agent"
    assert Path("/workspace/change.diff").stat().st_size > 0
    blocked = []
    for host, port in (
        ("1.1.1.1", 443),
        ("8.8.8.8", 53),
        ("2606:4700:4700::1111", 443),
    ):
        try:
            with socket.create_connection((host, port), timeout=2):
                raise AssertionError(f"Network reachable: {host}")
        except OSError:
            blocked.append(host)
    # Linux network namespace should have only the loopback interface.
    interfaces = sorted(p.name for p in Path("/sys/class/net").iterdir())
    assert interfaces == ["lo"], f"Unexpected network interfaces: {interfaces}"
    Path("/workspace/review.json").write_text("[]")
    return {
        "uid": os.getuid(),
        "git_metadata": False,
        "private_assets": False,
        "credentials": False,
        "external_connections_blocked": blocked,
        "network_interfaces": interfaces,
        "submission_writable": True,
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
