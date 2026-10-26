"""Create development-only credentials; never overwrite existing operator configuration."""

import secrets
from pathlib import Path


def main():
    target = Path(".env")
    if target.exists():
        raise SystemExit(".env exists; refusing to overwrite")
    value = Path(".env.example").read_text()
    for placeholder in (
        "replace-with-random-password",
        "replace-with-another-random-password",
        "replace-with-separate-random-password",
    ):
        value = value.replace(placeholder, secrets.token_hex(32))
    with target.open("x") as output:
        target.chmod(0o600)
        output.write(value)
    print("Development configuration created")


if __name__ == "__main__":
    main()
