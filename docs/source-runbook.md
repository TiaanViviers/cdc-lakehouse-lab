# Phase 1 source startup gate

**Decision, 2026-11-25. Use the dedicated VM and gate every actual source bridge immediately before startup.** The VM passed with its IPv4 and IPv6 rules applied. The bare workstation failed the host-gateway probe. The VM rules were rolled back after testing. Follow the [PostgreSQL source profile runbook](source-profile.md) to apply and verify the rules for the `source` profile.

For the full S00–S06 gate, fault suites, and read-only inspection, see [Verify the Phase 1 source gate](source-gate.md).

Run Docker commands from a shell on the intended machine. Define this helper in each staging or guest shell. The preflight uses the same explicit Unix socket for Engine and Compose.

```sh
labdocker() { docker --host unix:///var/run/docker.sock "$@"; }
```

## Reproduce the negative experiment

Run from the repository root on native Linux with Python 3, the local rootful Docker Unix socket, and the exact probe image in the daemon cache. The script resolves the staged linux/amd64 tag, verifies its ID against two immutable pins, and runs Node 20.20.2 by the verified ID. Verify the mapping on the staging machine before export. Every container overrides the image entrypoint. The script creates three disposable internal bridges (source, synthetic LAN, synthetic VPN), single-homed containers and a host process listening on an ephemeral port bound only to the source bridge gateway. Each container has a read-only root filesystem, 96 MiB memory, half a CPU and a 64-PID limit. The client uses the LAN fixture as its only explicit DNS upstream. The authoritative fixture answers only the synthetic A question for sentinel.isolation.test.

```sh
labdocker version
labdocker compose version
cat /etc/os-release
uname -r
labdocker info --format '{{json .FirewallBackend}}'
iptables --version
ip6tables --version
iptables -S DOCKER-USER
python3 scripts/isolation/preflight.py && echo STARTUP-SENTINEL
```

To transfer the fixture on read-only media, use the following staging commands and load the archive inside the guest. On the classic image store, the inspected config ID is `sha256:c496f84f24947250e706f03aca4af956a099d8f7e5521279f47e4077964d339a`.

```sh
ref=public.ecr.aws/supabase/postgres-meta
labdocker image inspect "$ref@sha256:a84cc713585eea7b401e4a2561ec4a1e48c87083d1c7ecb4502f204bb4391300" --format '{{.Os}}/{{.Architecture}} {{.Id}}'
labdocker image save "$ref:v0.96.6" -o probe.tar
# Inside the VM, with the archive on read-only media
labdocker load -i /mnt/probes/probe.tar
labdocker image inspect public.ecr.aws/supabase/postgres-meta:v0.96.6 --format '{{.Id}}'
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

## Dedicated-VM procedure for ticket 1.2

**Run inside the approved guest as root.** Use a disposable Linux VM with console access, staged images, disconnected external uplinks, and dedicated rootful Engine using iptables. Review the Compose file before provisioning bridges, then inspect `labdocker compose -f "$COMPOSE_FILE" --profile source config` after exporting their IDs and before starting workloads. Require internal bridge networks for all source-profile services, no published ports, external DNS, host networking, proxy environment, privileged capabilities or host socket mounts. Record every effective network name. Precreate named, empty internal bridges outside Compose. Capture the full ID returned by each creation in a distinct exported variable and retain it through startup and rollback. For every service network, declare `external: true` and set its Compose `name` to the captured ID, for example `name: ${SOURCE_INPUT_ID:?}`. This is the Engine ID of the named bridge. Keep the Compose inputs, environment, daemon and firewall under exclusive operator control throughout the procedure. Stop on a missing, unexpected, replaced or occupied network. Direct Compose startup bypasses the procedure.

For the standalone experiment, create the named test bridge in the guest and run the gate once before applying controls. Expect exit 1. For 1.2 use the actual precreated network names and configuration instead.

```sh
NET=source-input
SOURCE_INPUT_ID=$(labdocker network create --internal --ipv6 --opt com.docker.network.bridge.name=cdc-source1 "$NET") || exit 1
export SOURCE_INPUT_ID
python3 scripts/isolation/preflight.py --network "$SOURCE_INPUT_ID" && echo STARTUP-SENTINEL
```

On the approved VM, repeat the following for **each** source bridge. Use the full ID captured when provisioning each bridge. The example uses SOURCE_INPUT_ID. These commands require Docker already dispatches FORWARD to DOCKER-USER first for both families. Verify from the VM console and stop if either chain or dispatch is absent. Confirm neither proposed drop already exists before insertion so undo removes only this run's rules. Run privileged commands only on that VM with approval.

```sh
set -eu
id=$SOURCE_INPUT_ID
test "$(labdocker network inspect -f '{{.Id}}' "$id")" = "$id"
br=$(labdocker network inspect -f '{{index .Options "com.docker.network.bridge.name"}}' "$id")
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

Set COMPOSE_FILE to the reviewed Compose file. The gate derives all network IDs from the resolved source services, rejects managed networks and mutable network names, probes each ID, then rechecks the model and every ID before invoking Compose on the same local daemon. Compose 2.40.3 resolves external networks by full ID. Removal of an approved bridge makes the external reference unusable even if its operator-facing name is immediately reused. [Docker Compose external networks](https://docs.docker.com/reference/compose-file/networks/#external), [Compose 2.40.3 network resolution](https://github.com/docker/compose/blob/v2.40.3/pkg/compose/create.go#L1393-L1419).

```sh
python3 scripts/isolation/preflight.py --start-compose "$COMPOSE_FILE"
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
labdocker ps -aq --filter "label=$TAG"
labdocker network ls -q --filter "label=$TAG"
labdocker ps -aq --filter "label=$TAG" | xargs -r docker --host unix:///var/run/docker.sock rm -fv
labdocker network ls -q --filter "label=$TAG" | xargs -r docker --host unix:///var/run/docker.sock network rm
```

Both label queries were empty after the workstation failure. The VM cleanup results appear below. Exact rule ordering is intentionally conservative. A deployment with another backend, OS, topology, DNS policy or Docker version needs a new verification record.

**Verified documentation**, consulted 2026-11-25 for the Engine 29.1.3 experiment. Docker describes embedded DNS on custom networks, host reachability on internal bridges, and DOCKER-USER for forwarded traffic. Host-destined traffic needs an INPUT control as well. [Docker networking](https://docs.docker.com/engine/network/), [bridge gateway modes](https://docs.docker.com/engine/network/port-publishing/#gateway-modes), [Docker with iptables](https://docs.docker.com/engine/network/firewall-iptables/).

## Dedicated VM observations, 2026-11-25

QEMU 8.2.2 with KVM, two vCPUs, 2048 MiB RAM and `-nic none` booted Ubuntu 24.04.5 LTS amd64, kernel 6.8.0-147-generic, from a fresh qcow2 overlay. The base image SHA-256 was `04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94`, verified against Canonical's signed SHA256SUMS. Docker binaries and the probe archive entered through read-only media. Guest versions were Engine 29.1.3, Compose 2.40.3+ds1-0ubuntu1~24.04.1, Python 3.12.3, and both iptables frontends 1.8.10 (nf_tables). Engine reported the iptables driver. Before creating the test bridge, `ip -br link` listed only lo and docker0. [Ubuntu cloud images](https://cloud-images.ubuntu.com/noble/)

**Offline import finding.** The initial guest run stopped at `docker run --pull=never` with “No such image” for the staging daemon's config ID. The guest containerd image store reported the archive's platform manifest ID `sha256:ccf3fb919284b063f6a57efadc504e4a8b2df8dc2985b8a8927c5ca05044e02c`. Inspecting that manifest in the exported archive confirmed its config digest exactly matched the staging ID above. The harness accepts those two verified IDs and runs by immutable ID.

The source bridge had connected routes for 172.18.0.0/16 and fdfa:653f:4c09::/64, IPv6 link-local and loopback, and no usable off-bridge default route. Each host process could read its own marker at its gateway address. The guest reported no published fixture ports. Both FORWARD chains began with an unconditional jump to DOCKER-USER.

| Probe with all rules applied | Same-side positive control | Result from source client |
|---|---|---|
| Peer by service DNS | Expected peer payload | cdc-isolation-v1, 0.08 s |
| VM host IPv4 / IPv6 | Marker on both gateway listeners | ETIMEDOUT, 1.58 / 1.61 s |
| LAN / VPN IPv4 | Marker, 0.09 / 0.08 s | ENETUNREACH, 0.07 / 0.08 s |
| Off-bridge IPv6 | Marker, 0.08 s | ENETUNREACH, 0.08 s |
| External DNS fixture | Exact A record 172.19.0.2, 0.21 s | Embedded resolver ESERVFAIL, 0.08 s |

| VM state, in execution order | Gate and startup decision |
|---|---|
| No guest rules applied | Both host markers returned in 0.08 s. Exit 1. |
| Both INPUT and DOCKER-USER drops in both families | Exit 0. STARTUP-SENTINEL printed once. INPUT counters showed 2 packets / 120 bytes for IPv4 and 13 / 872 for IPv6. Counters include other bridge traffic. |
| Only the IPv6 DOCKER-USER drop removed | All traffic probes still passed. Exact missing-rule diagnostic, exit 1. |
| All experimental rules removed | Host IPv4 and IPv6 markers returned in 0.09 and 0.10 s. Exit 1. |

To repeat the missing-rule control after the successful sentinel, run the following inside the guest. Restoring this one rule allows the ordinary undo loop above to remove each insertion once.

```sh
ip6tables -D DOCKER-USER -i "$br" ! -o "$br" -j DROP
python3 scripts/isolation/preflight.py --network "$SOURCE_INPUT_ID" && echo STARTUP-SENTINEL
# Run separately after observing exit 1
ip6tables -I DOCKER-USER 1 -i "$br" ! -o "$br" -j DROP
```

After undo, repeat the sentinel and expect host reachability to stop startup. Remove the standalone guest test bridge with `labdocker network rm "$SOURCE_INPUT_ID"`. Observed final state: zero containers, only bridge/host/none networks, empty DOCKER-USER chains and default ACCEPT INPUT chains for both families. Workstation firewall and VPN settings were untouched. No PostgreSQL service ran.

## Compose handoff experiment, 2026-11-25

Run the following only with the disposable guest bridge and the sentinel fixture. Begin with the ID captured at creation and both firewall families applied as above. The invalid context and socket exercise the explicit local-daemon selection. The sentinel emits one marker and stays running for endpoint inspection.

```sh
set -eu
export DOCKER_CONTEXT=missing-review-context DOCKER_HOST=unix:///run/intentionally-absent-review.sock
COMPOSE_FILE=tests/integration/isolation-sentinel.yaml
sentinel_compose() { labdocker compose -f "$COMPOSE_FILE" --profile source "$@"; }
gate() { python3 scripts/isolation/preflight.py --start-compose "$COMPOSE_FILE"; }
gate
cid=$(sentinel_compose ps -q sentinel)
test "$(labdocker inspect -f '{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}' "$cid")" = "$SOURCE_INPUT_ID"
test "$(labdocker logs "$cid")" = STARTUP-SENTINEL
sentinel_compose down
labdocker network rm "$SOURCE_INPUT_ID"
for state in missing replaced; do
    if [ "$state" = replaced ]; then
        replacement=$(labdocker network create --ipv6 --internal --opt "com.docker.network.bridge.name=$br" "$NET")
        test "$replacement" != "$SOURCE_INPUT_ID"
    fi
    if gate; then exit 1; fi
    # Sentinel-only control for removal between final inspection and Compose startup.
    if sentinel_compose up -d --no-build --pull never; then exit 1; fi
    test -z "$(sentinel_compose ps --all -q)"
done
```

The approved ID and the running sentinel's inspected NetworkID were identical (`a190bcde23f8…`). Gateway probes timed out in 1.59 s (IPv4) and 1.58 s (IPv6). The sentinel emitted its exact marker. With the network missing, both the gate and the separate Compose control returned 1. Recreating the same network and bridge names produced ID `d097e5256849…`; both commands again returned 1. The gate failed at inspection of the original ID. Compose reported the external network could not be found. Both negative controls left the sentinel project with zero containers.

Use the undo loop above with the recorded bridge interface, then remove the disposable replacement by its captured ID. The guest ended with zero containers and only its three default Docker networks. Ticket 1.2 must repeat the gate with its own Compose file and bridge IDs.
