import argparse
import sys

from keyring.errors import KeyringError

if sys.platform == "darwin":
    from keyring.backends.macOS import Keyring
else:
    from keyring.backends.SecretService import Keyring

parser = argparse.ArgumentParser(description="Store Ortie token JSON in the system keyring.")
parser.add_argument("action", choices=["read", "write"])
parser.add_argument("account")
args = parser.parse_args()
keyring = Keyring()

try:
    if args.action == "write":
        keyring.set_password("ortie", args.account, sys.stdin.read())
    else:
        token = keyring.get_password("ortie", args.account)
        if token is None:
            sys.exit("No Ortie token stored; authorize the account with ortie auth get first.")
        sys.stdout.write(token)
except KeyringError as error:
    sys.exit(f"Ortie keyring error: {error}")
