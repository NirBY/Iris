"""Generate per-machine private config and a user LaunchAgent. Does not start it."""

import argparse
import ipaddress
import json
import os
import platform
import plistlib
import secrets
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="127.0.0.1", help="Mac private IP or loopback")
args = parser.parse_args()
if platform.system() != "Darwin" or platform.machine() != "arm64":
    parser.error("Use a native Apple Silicon Terminal/Python (M1 or later), not Rosetta")
if int(platform.mac_ver()[0].split(".")[0]) < 14:
    parser.error("This Mila setup requires macOS 14 or later")
address = ipaddress.ip_address(args.host)
allowed = [
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "::1/128",
        "fc00::/7",
    )
]
if not any(address in network for network in allowed):
    parser.error("Use a loopback, private LAN or Tailscale address assigned to this Mac")

os.umask(0o077)
home = Path.home()
root = home / "Library/Application Support/MilaAPI"
models = home / "Library/Application Support/Mila/Models"
private = home / ".config/mila-api"
for directory in (root, root / "tmp", root / "logs", private):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
conf = private / "config.json"
cfg = json.loads(conf.read_text()) if conf.exists() else {"api_key": secrets.token_urlsafe(48)}
cfg["host"] = args.host
# Preserve working per-machine engine/model paths when updating an existing installation.
for name, value in {
    "port": 8081,
    "data_dir": str(root),
    "models_dir": str(models),
    "engine": str(root / "engine-source/build/bin/whisper-cli"),
    "ffmpeg": "/opt/homebrew/bin/ffmpeg",
    "ffprobe": "/opt/homebrew/bin/ffprobe",
}.items():
    cfg.setdefault(name, value)
conf.write_text(json.dumps(cfg, indent=2) + "\n")
conf.chmod(0o600)
key = private / "api-key.txt"
key.write_text(cfg["api_key"] + "\n")
key.chmod(0o600)
agent = {
    "Label": "io.local.mila-api",
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 10,
    "Nice": 10,
    "ProcessType": "Background",
    "ProgramArguments": [str(root / ".venv/bin/python"), str(root / "app.py")],
    "WorkingDirectory": str(root),
    "EnvironmentVariables": {
        "MILA_API_CONFIG": str(conf),
        "TMPDIR": str(root / "tmp"),
        "PYTHONUNBUFFERED": "1",
    },
    "StandardOutPath": "/dev/null",
    "StandardErrorPath": "/dev/null",
}
agents = home / "Library/LaunchAgents"
agents.mkdir(parents=True, exist_ok=True)
plist = agents / "io.local.mila-api.plist"
plist.write_bytes(plistlib.dumps(agent))
plist.chmod(0o600)
print("Private configuration and login LaunchAgent created. API key was not printed.")
print("Start the service using the launchctl command in INSTALL.md.")
