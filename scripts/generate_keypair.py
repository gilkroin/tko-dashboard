"""
Create the RSA key pair the ingestion job uses to sign in to Snowflake.

    python scripts/generate_keypair.py

Writes (into the git-ignored keys/ folder):
    keys/tko_ingest_rsa_key.p8   PRIVATE key  -> stays on your laptop + GitHub secret
    keys/tko_ingest_rsa_key.pub  PUBLIC key   -> pasted into Snowflake (script 02)

Why key-pair instead of a password?
  * Snowflake is phasing out password-only sign-in for users, and service
    users (TYPE = SERVICE) cannot use passwords at all.
  * The private key never leaves your control; Snowflake only stores the
    public half, which is useless to an attacker.
"""
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_DIR = Path(__file__).resolve().parent.parent / "keys"
PRIVATE = KEY_DIR / "tko_ingest_rsa_key.p8"
PUBLIC = KEY_DIR / "tko_ingest_rsa_key.pub"


def main() -> None:
    if PRIVATE.exists():
        raise SystemExit(f"{PRIVATE} already exists - delete it first if you really want a new key.")

    KEY_DIR.mkdir(exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    PRIVATE.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    PUBLIC.write_bytes(pub_pem)

    # Snowflake wants the public key body only: no BEGIN/END lines, no line breaks.
    body = "".join(
        line for line in pub_pem.decode().splitlines() if "-----" not in line
    )
    print(f"Private key written to {PRIVATE}  (keep secret, never commit)")
    print(f"Public key written to  {PUBLIC}")
    print("\nPaste this value into snowflake/02_ingest_role_and_service_user.sql")
    print("in place of <PASTE_PUBLIC_KEY_BODY_HERE> (public key - safe to share):\n")
    print(body)


if __name__ == "__main__":
    main()
