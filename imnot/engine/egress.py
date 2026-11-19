"""
Where a callback may be sent (SSRF guard).

Anyone who can reach a ``callback`` mock route chooses the URL imnot then calls, so on a shared
deployment it could be pointed at the cloud metadata service or at internal admin APIs.

Always on, for everybody:
- only ``http`` and ``https``;
- never a link-local or cloud-metadata address (``169.254.0.0/16``, ``fe80::/10``,
  ``fd00:ec2::254``), checked on every address the host name resolves to. No real webhook lives there.

Private addresses are allowed by default: the system under test usually runs next to imnot.

Opt-in (``--callback-allowed-hosts`` / ``IMNOT_CALLBACK_ALLOWED_HOSTS``): a comma-separated list of
host names (``orders.team-a``), ``*.`` suffixes (``*.team-a.svc.cluster.local``) and CIDRs
(``10.20.0.0/16``). When set, a callback must match one of them by name or resolve only to
addresses inside the listed networks.

The URL is checked when the submit arrives (a clear 422) and again before every delivery attempt,
after a fresh DNS lookup. That narrows DNS rebinding but does not pin the connection: httpx resolves
the name again when it connects, so a TTL-0 answer can still differ. An egress NetworkPolicy is the
hard limit (see docs/deployment.md).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

BLOCKED_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.ip_network("169.254.0.0/16"),  # IPv4 link-local, AWS/GCP/Azure metadata
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("fd00:ec2::254/128"),  # AWS metadata over IPv6
)


def _is_blocked(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:169.254.169.254 is the same address
    return any(ip in net for net in BLOCKED_NETWORKS)


@dataclass(frozen=True)
class CallbackPolicy:
    allowed_names: tuple[str, ...] = ()  # lower-case exact names, or ".suffix" for "*.suffix"
    allowed_networks: tuple[IPNetwork, ...] = ()

    @property
    def restricted(self) -> bool:
        return bool(self.allowed_names or self.allowed_networks)

    @classmethod
    def parse(cls, spec: str | None) -> CallbackPolicy:
        """Build a policy from ``IMNOT_CALLBACK_ALLOWED_HOSTS``. Raises ValueError on a bad entry."""
        names: list[str] = []
        networks: list[IPNetwork] = []
        for raw in (spec or "").split(","):
            entry = raw.strip().lower()
            if not entry:
                continue
            try:
                networks.append(ipaddress.ip_network(entry, strict=False))
                continue
            except ValueError:
                pass
            if entry.startswith("*."):
                entry = entry[1:]
            if not entry.strip(".") or any(c in entry for c in "/:*@ "):
                raise ValueError(f"invalid entry in callback allowed hosts: {raw.strip()!r}")
            names.append(entry)
        return cls(tuple(names), tuple(networks))

    def _name_allowed(self, host: str) -> bool:
        return any(host.endswith(n) if n.startswith(".") else host == n for n in self.allowed_names)

    async def problem(self, url: str) -> str | None:
        """Why *url* may not be called, or None when it may."""
        try:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError:
            return "is not a valid URL"
        if parts.scheme not in ("http", "https"):
            return "must use http or https"
        if not host:
            return "has no host"

        try:
            ips: list[IPAddress] = [ipaddress.ip_address(host)]
        except ValueError:
            ips = await _resolve(host, port)

        if any(_is_blocked(ip) for ip in ips):
            return "points to a link-local or cloud metadata address"
        if not self.restricted or self._name_allowed(host):
            return None
        if ips and all(any(ip in net for net in self.allowed_networks) for ip in ips):
            return None
        return "is not in the callback allowed hosts (IMNOT_CALLBACK_ALLOWED_HOSTS)"


async def _resolve(host: str, port: int) -> list[IPAddress]:
    """Every address *host* resolves to; empty when it does not resolve (the delivery then fails anyway)."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return []
    out: list[IPAddress] = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]))  # drop an IPv6 zone id
        except ValueError:
            continue
    return out
