"""Offline deployment configuration validation; does not print secret values."""
from pathlib import Path
from urllib.parse import urlsplit, unquote
import re
import sys
root = Path(__file__).resolve().parents[1]


def read_env(path):
    if not path.exists():
        return {}
    return dict(line.split("=",1) for line in path.read_text().splitlines() if line and not line.startswith("#") and "=" in line)


def main():
    outer=read_env(root/".env"); inner=read_env(root/"backend/.env")
    errors=[]
    for name in ("caddy/Caddyfile", "frontend_api_demo/index.html", "backend/.env", ".env"):
        if not (root/name).is_file(): errors.append(f"Missing {name}")
    domain=outer.get("SITE_DOMAIN", "")
    if not re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", domain) or "example" in domain:
        errors.append("Set a real SITE_DOMAIN without a scheme or path")
    password=outer.get("DB_PASSWORD", "")
    if not re.fullmatch(r"[a-fA-F0-9]{32,}", password): errors.append("DB_PASSWORD must be at least 32 random hex characters")
    u=urlsplit(inner.get("DATABASE_URL", ""))
    if not u.scheme.startswith("postgresql") or u.hostname != "db" or u.username != "enertri_user" or u.path != "/enertri" or unquote(u.password or "") != password:
        errors.append("DATABASE_URL must match the Compose database and DB_PASSWORD")
    for name, minimum in (("SECRET_KEY",32),("BOOTSTRAP_ADMIN_PASSWORD",16)):
        value=inner.get(name, "")
        if len(value)<minimum or any(x in value.lower() for x in ("replace", "change", "example")):
            errors.append(f"Set a unique {name}")
    for name,value in (("APP_ENV","production"),("APP_BOOTSTRAP_ON_STARTUP","false"),("TASK_EXECUTION_MODE","database_worker"),("SIMULATION_EXECUTION_ENABLED","false")):
        if inner.get(name)!=value: errors.append(f"Require {name}={value}")
    if inner.get("CORS_ORIGINS") != "https://"+domain: errors.append("CORS_ORIGINS must match the HTTPS domain")
    if errors:
        print("BLOCKED\n"+"\n".join(errors)); return 1
    print("Configuration checks passed. Container, dependency, security and load gates still required."); return 0


if __name__ == "__main__":
    sys.exit(main())
