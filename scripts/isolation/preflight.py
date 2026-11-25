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

# Classic storage reports the config ID. The containerd store reports the
# platform manifest ID from the offline archive containing that same config.
IMAGE_TAG = "public.ecr.aws/supabase/postgres-meta:v0.96.6"
PINNED_IDS = {
    "sha256:c496f84f24947250e706f03aca4af956a099d8f7e5521279f47e4077964d339a",
    "sha256:ccf3fb919284b063f6a57efadc504e4a8b2df8dc2985b8a8927c5ca05044e02c",
}
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]
FIXTURE = Path(__file__).with_name("probe.js").resolve()


def docker(*args):
    return subprocess.check_output([*DOCKER, *args], text=True).strip()


class Marker(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b"cdc-isolation-v1")


class IPv6Server(socketserver.TCPServer):
    address_family = socket.AF_INET6


def host_control(stack, gateway):
    server_type = IPv6Server if ":" in gateway else socketserver.TCPServer
    server = stack.enter_context(server_type((gateway, 0), Marker))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stack.callback(server.shutdown)
    port = server.server_address[1]
    with socket.create_connection((gateway, port), 2) as sock:
        if sock.makefile("rb").read() != b"cdc-isolation-v1":
            raise SystemExit("STOP: host control missing")
    print(f"Host positive {gateway}: expected marker")
    return str(port)


def main(stack, network):
    image_id = docker("image", "inspect", "-f", "{{.Id}}", IMAGE_TAG)
    if image_id not in PINNED_IDS:
        raise SystemExit("STOP: unexpected probe image ID")
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
                       "-v", f"{FIXTURE}:/probe.js:ro", *opts, "--entrypoint", "node", image_id, *args)
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
    port = host_control(stack, gateway)
    print("All container ports unpublished")
    print("Source addresses", info["IPAM"]["Config"])
    print(docker("exec", client, "cat", "/proc/net/route", "/proc/net/ipv6_route"))
    print("Source IPv6 interfaces:", docker("exec", client, "cat", "/proc/net/if_inet6"))
    cases = [
        ("peer DNS+TCP", client, True, "tcp", peer, "8181"),
        ("host", client, False, "tcp", gateway, port),
    ]
    if info["EnableIPv6"]:
        gateway6 = next(c["Gateway"] for c in info["IPAM"]["Config"] if ":" in c.get("Gateway", ""))
        cases.append(("host IPv6", client, False, "tcp", gateway6, host_control(stack, gateway6)))
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
            # Other source bridges can have earlier DROP rules. An earlier
            # jump or accept could bypass this control and must stop the gate.
            for rule in rules:
                if not rule.startswith("-A "):
                    continue
                if rule == expected:
                    break
                if chain == "FORWARD" or not rule.endswith(" -j DROP"):
                    raise SystemExit(f"STOP: {tool} {rule} precedes {expected}")
            else:
                raise SystemExit(f"STOP: {tool} missing {expected}")
    print("PASS: source bridge probes and required IPv4/IPv6 rules verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", help="existing empty internal source network")
    with contextlib.ExitStack() as cleanup:
        main(cleanup, parser.parse_args().network)
