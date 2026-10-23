"""Read-only endpoint diagnostics; never download or print response bodies."""

from __future__ import annotations

import argparse
import json
import math
import queue
import socket
import threading
from urllib.parse import urlsplit

import requests

from .federal_spending_auditor import API_URL
from .reconciliation import FPDS_URL


def dns_status(host: str, timeout: float) -> str:
    """Bound local DNS observation without changing the HTTP routing path."""
    result: queue.Queue[str] = queue.Queue()

    def resolve() -> None:
        try:
            socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            result.put("resolved")
        except OSError:
            result.put("dns_error")

    # A stuck system resolver must not keep the command alive after timeout.
    threading.Thread(target=resolve, daemon=True).start()
    try:
        return result.get(timeout=timeout)
    except queue.Empty:
        return "timeout"


def diagnose_endpoint(url: str, timeout: float = 5.0) -> dict:
    """HEAD only, no redirects/retries, using Requests' inherited proxy/CA trust."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if url not in (API_URL, FPDS_URL):
        raise ValueError("only official USAspending and FPDS endpoints are supported")
    proxies = requests.utils.get_environ_proxies(url)
    result = {
        "url": url,
        "method": "HEAD",
        "dns": dns_status(urlsplit(url).hostname, timeout),
        "proxy_configured": bool(requests.utils.select_proxy(url, proxies)),
        "http_status": None,
        "error": None,
    }
    try:
        with requests.Session() as session:
            with session.head(
                url, timeout=(timeout, timeout), allow_redirects=False, stream=True
            ) as response:
                result["http_status"] = response.status_code
                if not 200 <= response.status_code < 300:
                    result["error"] = "redirect" if response.status_code < 400 else "http_error"
    except requests.exceptions.ProxyError:
        result["error"] = "proxy_error"
    except requests.exceptions.SSLError:
        result["error"] = "tls_error"
    except requests.Timeout:
        result["error"] = "timeout"
    except requests.ConnectionError:
        result["error"] = "connection_error"
    except requests.RequestException:
        result["error"] = "request_error"
    except OSError:
        result["error"] = "local_configuration_error"
    # Exception messages, proxy URLs, headers and bodies can contain credentials.
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=5.0, help="DNS/connect/read timeout in seconds")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    results = [diagnose_endpoint(url, args.timeout) for url in (API_URL, FPDS_URL)]
    print(json.dumps(results, indent=2, sort_keys=True))
    return int(any(row["error"] is not None for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
