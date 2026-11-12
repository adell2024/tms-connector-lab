import json
import sys

import requests

URL = "http://localhost:3000/expeditions"


def main() -> None:
    try:
        response = requests.get(URL, timeout=10)
    except requests.RequestException as exc:
        print(f"Erreur lors de l'appel à {URL} : {exc}", file=sys.stderr)
        sys.exit(1)

    if response.status_code != 200:
        print(
            f"Code HTTP inattendu : {response.status_code} (attendu 200)",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = response.json()
    except ValueError as exc:
        print(f"La réponse n'est pas un JSON valide : {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
