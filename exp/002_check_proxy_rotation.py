"""Probe whether DataImpulse rotates exit IPs within a single curl_cffi session.

Hits an IP-echo endpoint N times reusing the same session, then N more times
opening a fresh session per request. If reuse pins the IP but per-request
sessions rotate, that confirms the CONNECT-tunnel hypothesis.
"""

from curl_cffi import requests
from proxy import DATAIMPULSE_PROXY_URL

IP_ECHO_URL = "https://api.ipify.org?format=json"
IMPERSONATE_TARGET = "safari18_0"
REQUEST_TIMEOUT_SECONDS = 30.0
NUM_REQUESTS = 5
PROXIES = {"http": DATAIMPULSE_PROXY_URL, "https": DATAIMPULSE_PROXY_URL}


def fetch_ip(session: requests.Session) -> str:
    response = session.get(IP_ECHO_URL)
    response.raise_for_status()
    return response.json()["ip"]


def main() -> None:
    print(f"--- Reusing one session across {NUM_REQUESTS} requests ---")
    with requests.Session(
        impersonate=IMPERSONATE_TARGET,
        timeout=REQUEST_TIMEOUT_SECONDS,
        proxies=PROXIES,
    ) as session:
        ips_reused = [fetch_ip(session) for _ in range(NUM_REQUESTS)]
    for i, ip in enumerate(ips_reused, 1):
        print(f"  [{i}] {ip}")
    print(f"  unique: {len(set(ips_reused))}")

    print(f"\n--- Fresh session per request ({NUM_REQUESTS} requests) ---")
    ips_fresh: list[str] = []
    for _ in range(NUM_REQUESTS):
        with requests.Session(
            impersonate=IMPERSONATE_TARGET,
            timeout=REQUEST_TIMEOUT_SECONDS,
            proxies=PROXIES,
        ) as session:
            ips_fresh.append(fetch_ip(session))
    for i, ip in enumerate(ips_fresh, 1):
        print(f"  [{i}] {ip}")
    print(f"  unique: {len(set(ips_fresh))}")


if __name__ == "__main__":
    main()
