"""Create an empty, temporary LOCAL cluster; never load .env or an existing DB.

Requires already-installed PostgreSQL binaries. No package installation, Docker,
Windows service, external host or production backup is used.
"""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", required=True)
    parser.add_argument("--schema-only", action="store_true", help="Build synthetic tables from models without running migrations.")
    parser.add_argument("labels", nargs="*")
    options = parser.parse_args()
    pg_bin = Path(options.pg_bin).resolve(strict=True)
    for executable in ("initdb.exe", "pg_ctl.exe", "createdb.exe"):
        if not (pg_bin / executable).is_file():
            parser.error("PostgreSQL initdb, pg_ctl and createdb binaries are required.")
    env = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG", "PYTHONTZPATH") if name in os.environ}
    root = Path(tempfile.mkdtemp(prefix="kbc-phase3-pg-tests-")).resolve()
    data = root / "data"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    kwargs = dict(env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True,
                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    def run(command, *, checked=True):
        if Path(command[0]).name == "pg_ctl.exe":
            # On Windows postgres may inherit pg_ctl's pipe handle after the
            # parent exits. A local file avoids communicate() waiting for the
            # long-lived server to close that pipe.
            with (root / "pg_ctl.log").open("a", encoding="utf-8") as output:
                result = subprocess.run(command, **{**kwargs, "check": False, "stdout": output})
            print(f"Local PostgreSQL {command[-1]}: exit {result.returncode}", flush=True)
        else:
            result = subprocess.run(command, **{**kwargs, "check": False})
            print(result.stdout, end="", flush=True)
        if checked:
            result.check_returncode()
        return result
    started = False
    try:
        run([str(pg_bin / "initdb.exe"), "-D", str(data), "-U", "kbc_test_admin",
             "--auth=trust", "--encoding=UTF8", "--locale=C"])
        run([str(pg_bin / "pg_ctl.exe"), "-D", str(data), "-l", str(root / "postgres.log"),
             "-o", f"-h 127.0.0.1 -p {port} -c fsync=off", "-w", "start"])
        started = True
        run([str(pg_bin / "createdb.exe"), "-h", "127.0.0.1", "-p", str(port),
             "-U", "kbc_test_admin", "kbc_phase3_tests"])
        result = run([sys.executable, "-B", str(Path(__file__).with_name("run_isolated_tests.py")),
                      "--postgres-port", str(port), *(["--schema-only"] if options.schema_only else []),
                      *(options.labels or ["library"])], checked=False)
        return result.returncode
    finally:
        if started:
            # Exact cluster path from this invocation; no unrelated service stop.
            run([str(pg_bin / "pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"])
        print(f"Synthetic test cluster (no production data): {root}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
