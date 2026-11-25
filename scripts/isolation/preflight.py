"""Exercise local Linux bridge paths. Exit nonzero while host policy is unverified."""
import argparse
import contextlib
import json
from pathlib import Path
import socket
import socketserver
import subprocess
import threading
import time
import uuid

IMAGE = "public.ecr.aws/supabase/postgres-meta@sha256:a84cc713585eea7b401e4a2561ec4a1e48c87083d1c7ecb4502f204bb4391300"
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]
FIXTURE = Path(__file__).with_name("probe.js").resolve()


def docker(*args):
    return subprocess.check_output([*DOCKER, *args], text=True).strip()


class Marker(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b"cdc-isolation-v1")


def main(stack, network):
    tag = "cdc-preflight-" + uuid.uuid4().hex[:12]
    print("Run label", tag, flush=True)

    def bridge(suffix, *options):
        ident = docker("network", "create", "--internal", "--label", tag, *options, tag + suffix)
        stack.callback(docker, "network", "rm", ident)
        return ident

    source = network or bridge("-source")
    info = json.loads(docker("network", "inspect", source))[0]
    if info["Driver"] != "bridge" or not info["Internal"] or info["Containers"]:
        raise SystemExit("STOP: require empty internal source bridge")
    gateway = next(c["Gateway"] for c in info["IPAM"]["Config"] if "." in c.get("Gateway", ""))
    outside = bridge("-outside", "--ipv6")

    def container(net, suffix, args, *opts):
        ident = docker("run", "-d", "--pull=never", "--network", net, "--label", tag,
                       "--name", tag + suffix, "--memory", "96m", "--cpus", "0.5",
                       "--pids-limit", "64", "--read-only", "--cap-drop", "ALL",
                       "-v", f"{FIXTURE}:/probe.js:ro", *opts, "--entrypoint", "node", IMAGE, *args)
        stack.callback(docker, "rm", "-fv", ident)
        if docker("port", ident):
            raise SystemExit("STOP: unexpected published port")
        return ident

    hold = ["-e", "setInterval(()=>{},60000)"]
    target = container(outside, "-target", hold)
    nic = next(iter(json.loads(docker("inspect", target))[0]["NetworkSettings"]["Networks"].values()))
    v4, v6 = nic["IPAddress"], nic["GlobalIPv6Address"]
    if not v4 or not v6:
        raise SystemExit("STOP: missing dual-stack control addresses")
    docker("exec", "-d", target, "node", "/probe.js", "serve", "::", "8181", v4)
    peer = tag + "-peer"
    container(source, "-peer", ["/probe.js", "serve", "0.0.0.0"])
    client = container(source, "-client", hold, "--dns", v4)
    control = container(outside, "-control", hold, "--dns", v4)
    server = stack.enter_context(socketserver.TCPServer((gateway, 0), Marker))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stack.callback(server.shutdown)
    port = str(server.server_address[1])
    with socket.create_connection((gateway, int(port)), 2) as sock:
        if sock.makefile("rb").read() != b"cdc-isolation-v1":
            raise SystemExit("STOP: host control missing")
    print("Host positive: expected marker; all container ports unpublished")
    print("Source addresses", info["IPAM"]["Config"])
    print(docker("exec", client, "cat", "/proc/net/route", "/proc/net/ipv6_route"))
    print("Source IPv6 interfaces:", docker("exec", client, "cat", "/proc/net/if_inet6"))
    cases = [
        ("peer DNS+TCP", client, True, "tcp", peer, "8181"),
        ("host", client, False, "tcp", gateway, port),
    ]
    for label, mode, dst, arg in [("LAN IPv4", "tcp", v4, "8181"),
                                  ("IPv6", "tcp", v6, "8181"),
                                  ("delegated DNS", "dns", v4, "53")]:
        cases.append((label + " positive", control, True, mode, dst, arg))
        cases.append((label, client, False, mode, "127.0.0.11" if mode == "dns" else dst, arg))

    vpn = bridge("-vpn")
    vpn_peer = container(vpn, "-vpn-peer", ["/probe.js", "serve", "0.0.0.0"])
    vpn_ip = docker("inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", vpn_peer)
    cases.extend([
        ("VPN IPv4 positive", container(vpn, "-vpn-client", hold), True, "tcp", vpn_ip, "8181"),
        ("VPN IPv4", client, False, "tcp", vpn_ip, "8181"),
    ])
    passed = True
    for label, cid, positive, mode, dst, arg in cases:
        start = time.monotonic()
        result = subprocess.run([*DOCKER, "exec", cid, "node", "/probe.js", mode, dst, arg, v4],
                                text=True, capture_output=True, timeout=4)
        msg = (result.stdout + result.stderr).strip()
        denied = result.returncode == 1 and msg in {
            "ETIMEDOUT", "ENETUNREACH", "EHOSTUNREACH", "EREFUSED", "ESERVFAIL"}
        ok = result.returncode == 0 if positive else denied
        passed &= ok
        print(f"{label}: {'PASS' if ok else 'FAIL'} {msg} ({time.monotonic()-start:.2f}s)", flush=True)
    if not passed:
        raise SystemExit("STOP: probe expectations failed; source startup blocked")
    if not network:
        raise SystemExit("STOP: source startup requires the actual source network")
    interface = info["Options"].get("com.docker.network.bridge.name", "br-" + info["Id"][:12])
    if docker("info", "--format", "{{.FirewallBackend.Driver}}") != "iptables":
        raise SystemExit("STOP: unsupported firewall backend")
    for tool in ("iptables", "ip6tables"):
        for chain, match in (("INPUT", f"-i {interface}"),
                             ("DOCKER-USER", f"-i {interface} ! -o {interface}"),
                             ("FORWARD", "")):
            rules = subprocess.check_output([tool, "-S", chain], text=True).splitlines()
            target = "DOCKER-USER" if chain == "FORWARD" else "DROP"
            expected = " ".join(filter(None, ["-A", chain, match, "-j", target]))
            first = next((rule for rule in rules if rule.startswith("-A ")), "")
            if first != expected:
                raise SystemExit(f"STOP: {tool} requires first rule {expected}")
    print("PASS: source bridge probes and required IPv4/IPv6 rules verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", help="existing empty internal source network")
    with contextlib.ExitStack() as cleanup:
        main(cleanup, parser.parse_args().network)
