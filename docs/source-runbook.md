# Phase 1 source startup gate

**Decision, 2026-11-25. Stop before starting the source on the tested host.** The internal bridge allowed TCP to its host gateway. A service returning a known payload demonstrated the path even with no published ports. Ticket 1.2 runtime validation requires an approved dedicated environment and a fresh successful preflight.

## Reproduce the negative experiment

Run from the repository root on native Linux with Python 3, the local rootful Docker Unix socket, and the exact probe image in the daemon cache. The image digest in the script selects an already staged Node 20.20.2 runtime. Every container overrides the image entrypoint. The script creates three disposable internal bridges (source, synthetic LAN, synthetic VPN), single-homed containers and a host process listening on an ephemeral port bound only to the source bridge gateway. Each container has a read-only root filesystem, 96 MiB memory, half a CPU and a 64-PID limit. The client uses the LAN fixture as its only explicit DNS upstream. The authoritative fixture answers only the synthetic A question for sentinel.isolation.test.

```sh
docker --host unix:///var/run/docker.sock version
docker compose version
cat /etc/os-release
uname -r
docker --host unix:///var/run/docker.sock info --format '{{json .FirewallBackend}}'
iptables --version
ip6tables --version
iptables -S DOCKER-USER
python3 scripts/isolation/preflight.py && echo STARTUP-SENTINEL
```

**Observed** on Ubuntu 24.04.4 LTS, Linux 7.0.0-43-generic, amd64, Docker client/server 29.1.3, API 1.52, Compose 2.40.3+ds1-0ubuntu1~24.04.1. Engine reported driver iptables. The iptables frontend reported 1.8.10 (nf_tables). Reading DOCKER-USER returned permission denied. No firewall or VPN configuration was applied.

| Probe from disposable run | Expected | Observed (elapsed seconds) |
|---|---|---|
| Host process to bound gateway port | Exact marker | cdc-isolation-v1 |
| Source client to peer by Docker DNS | Exact marker | cdc-isolation-v1 (0.08) |
| Source client to host gateway | Denied | **cdc-isolation-v1 (0.08), FAIL** |
| LAN bridge client / source client to LAN IPv4 | Marker / denied | marker (0.08) / ENETUNREACH (0.08) |
| VPN bridge client / source client to VPN IPv4 | Marker / denied | marker (0.08) / ENETUNREACH (0.08) |
| Dual-stack LAN client / source client to LAN IPv6 | Marker / denied | marker (0.08) / ENETUNREACH (0.08) |
| Direct authoritative DNS from LAN / delegated query via source embedded resolver | Exact fixture IPv4 / denied | 172.22.0.2 (0.07) / ESERVFAIL (0.07) |

Source eth0 had only the connected 172.21.0.0/16 route, gateway listener 172.21.0.1, and IPv6 only on loopback. Docker reported no port publications on any fixture. TCP inactivity deadline is 1.5 s, DNS requests use one 500 ms attempt, and each container probe has a four-second outer deadline. A harness error stops the gate. The shell returned 1 and skipped STARTUP-SENTINEL. Routed failures establish absence of a usable path in this topology. They do not measure packet-filter drops. The controlled DNS result covers this upstream and network configuration only.

## Candidate dedicated-host procedure for ticket 1.2

**Requires approval and live verification.** Use a disposable Linux VM with console access, staged images, disconnected external uplinks, and dedicated rootful Engine using iptables. Inspect resolved `docker compose --profile source config` before creating anything. Require internal bridge networks for all source-profile services, no published ports, external DNS, host networking, proxy environment, privileged capabilities or host socket mounts. Record every effective network name. Precreate the actual empty bridges with the exact Compose settings (or use explicitly named external internal bridges). Use these same bridge IDs through startup. Stop on a missing, unexpected, replaced or occupied network. Direct Compose startup bypasses the procedure.

On the approved VM, repeat the following for **each** source bridge. Set NET to its exact Docker network name. These proposed commands assume Docker already dispatches FORWARD to DOCKER-USER first for both families. Verify from the VM console and stop if either chain or dispatch is absent. Confirm neither proposed drop already exists before insertion so undo removes only this run's rules. Run privileged commands only on that VM with approval.

```sh
set -eu
id=$(docker network inspect -f '{{.Id}}' "$NET")
br=$(docker network inspect -f '{{index .Options "com.docker.network.bridge.name"}}' "$NET")
br=${br:-br-${id%"${id#????????????}"}}
ip link show dev "$br"
for fw in iptables ip6tables; do
    "$fw" -S FORWARD
    "$fw" -S INPUT
    "$fw" -S DOCKER-USER
    "$fw" -I INPUT 1 -i "$br" -j DROP
    "$fw" -I DOCKER-USER 1 -i "$br" ! -o "$br" -j DROP
done
```

In the same approved environment run the startup gate with positional arguments set to **all** resolved network names. The script validates each actual network and checks first-rule placement in both families. Keep the source stopped on any failure. Run immediately before startup and repeat after network, DNS, rules or daemon changes. No persisted pass token exists.

```sh
set -eu
test "$#" -gt 0
for net do python3 scripts/isolation/preflight.py --network "$net"; done
docker compose --profile source up -d --pull never
```

After stopping workloads and before deleting each bridge, undo only the insertions that succeeded, using its recorded interface name. A disposable VM snapshot also permits whole-VM rollback.

```sh
for fw in iptables ip6tables; do
    "$fw" -D DOCKER-USER -i "$br" ! -o "$br" -j DROP
    "$fw" -D INPUT -i "$br" -j DROP
done
```

The harness normally removes its containers and temporary bridges on exit and closes the listener. An existing source bridge supplied by name stays in place. After interruption, set TAG to the exact printed run label; inspect the listed IDs before removing them. Never prune shared Docker state.

```sh
docker ps -aq --filter "label=$TAG"
docker network ls -q --filter "label=$TAG"
docker ps -aq --filter "label=$TAG" | xargs -r docker rm -fv
docker network ls -q --filter "label=$TAG" | xargs -r docker network rm
```

Both label queries were empty after the recorded failure. The dedicated-VM apply, pass and undo sequence remains untested. Exact rule ordering is intentionally conservative. A deployment with another backend, OS, topology, DNS policy or Docker version needs a new verification record.

**Verified documentation**, consulted 2026-11-25 for the Engine 29.1.3 experiment. Docker describes embedded DNS on custom networks, host reachability on internal bridges, and DOCKER-USER for forwarded traffic. Host-destined traffic needs an INPUT control as well. [Docker networking](https://docs.docker.com/engine/network/), [bridge gateway modes](https://docs.docker.com/engine/network/port-publishing/#gateway-modes), [Docker with iptables](https://docs.docker.com/engine/network/firewall-iptables/).
