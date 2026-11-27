#!/usr/bin/env bash
# Run in the scheduled disconnected lab guest, with verified read-only media.
set -Eeuo pipefail
umask 077
exec </dev/null
cd "$(dirname "$0")/../../.."
media=$(realpath "${1:?staged media directory}")
trial=${2:?baseline, copy-window, copy-boundary or gate}
case $trial in
    baseline|copy-window) experiment=017 ticket=43 sequence=26 controller=cdc-baseline/baseline.py ;;
    copy-boundary)
        experiment=023 ticket=60 sequence=32 controller=cdc-baseline/copy_boundary.py
        export COPY_SCHEDULE=${3:?overlap, delayed, before-slot or after-copy}
        case $COPY_SCHEDULE in overlap|delayed|before-slot|after-copy) ;; *) exit 2 ;; esac
        ;;
    gate) experiment=020 ticket=46 sequence=29 controller=cdc-gate/gate.py ;;
    *) exit 2 ;;
esac
: "${CDC_REVISION:?tested revision}" "${CDC_OVERLAY:?guest overlay identity}"
[[ $CDC_REVISION =~ ^[0-9a-f]{40}$ && $CDC_OVERLAY =~ ^[a-zA-Z0-9_.-]+$ ]]
test "$(id -u)" = 0
findmnt -no OPTIONS --target "$media" | tr , '\n' | grep -Fxq ro
test -z "$(ip -4 route show default; ip -6 route show default)"
test "$(ls /sys/class/net | sort | paste -sd ' ')" = 'docker0 lo'
unset DOCKER_CONTEXT DOCKER_HOST COMPOSE_FILE COMPOSE_PROFILES COMPOSE_ENV_FILES SOURCE_INPUT_ID
unset SOURCE_FIXTURE_ID_FILE
export LC_ALL=C TZ=UTC COMPOSE_DISABLE_ENV_FILE=1
utc=$(date -u +%Y%m%dT%H%M%SZ)
export CDC_RUN_KEY="r$(date -u +%Y%m%dt%H%M%Sz)$(openssl rand -hex 2)"
# The guarded 2.2 publisher CLI enrolls only projects with this prefix.
export COMPOSE_PROJECT_NAME="cdc22-$CDC_RUN_KEY"
export RUN_ID="$utc-$CDC_RUN_KEY" RUNNER_ID="$utc-p01-$sequence" TRIAL="$trial"
export EVIDENCE="$PWD/artifacts/EXP-$experiment/$RUN_ID"
if [[ $trial == gate ]]; then
    parent=$(realpath "${3:?gate evidence parent}")
    [[ $parent == "$PWD/artifacts/EXP-020/pair-"* && -d $parent ]]
    export EVIDENCE="$parent/$RUN_ID"
fi
export SOURCE_RUNNER_IMAGE=cdc-lab-fixture-runner:v1-1.8
mkdir -p "${EVIDENCE%/*}"
mkdir "$EVIDENCE" secrets
exec > >(tee "$EVIDENCE/run.txt") 2>&1
trap 'echo "Run failed at line $LINENO (exit $?)" >&2' ERR
trap 'exit 124' TERM
echo "owner=Codex ticket=$ticket trial=$trial run=$RUN_ID runner=$RUNNER_ID sha=$CDC_REVISION overlay=$CDC_OVERLAY project=$COMPOSE_PROJECT_NAME"
echo 'Budgets: guest 2 vCPU / 2 GiB, run 480s, checkpoint 60s, polling 500ms after a read, rollback hold 10s'
d() { timeout --foreground -k 2s 35s docker --host unix:///var/run/docker.sock "$@"; }
stack() { d compose -f compose.source.yaml -f compose.cdc.yaml -f compose.runner.yaml --profile source --profile cdc --profile generator "$@"; }
bridge="p${sequence}${CDC_RUN_KEY:10:6}${CDC_RUN_KEY:17:4}"
label="com.docker.compose.project=$COMPOSE_PROJECT_NAME"
rules=()
identity() {
    local service=$1 volume=$2 destination=$3 id=$4
    test "$(d inspect -f '{{index .Config.Labels "com.docker.compose.project"}}/{{index .Config.Labels "com.docker.compose.service"}} {{len .NetworkSettings.Networks}} {{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}} {{.HostConfig.Privileged}}' "$id")" = "$COMPOSE_PROJECT_NAME/$service 1 $SOURCE_INPUT_ID false" &&
    test "$(d inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}:{{.Destination}}{{end}}{{end}}' "$id")" = "${COMPOSE_PROJECT_NAME}_$volume:$destination" &&
    test "$(d volume inspect -f '{{index .Labels "com.docker.compose.project"}}/{{index .Labels "com.docker.compose.volume"}}' "${COMPOSE_PROJECT_NAME}_$volume")" = "$COMPOSE_PROJECT_NAME/$volume" &&
    test -z "$(d port "$id")"
}
rule() {
    local action=$1 fw=$2 chain=$3
    if [[ $chain == INPUT ]]; then "$fw" "$action" INPUT -i "$bridge" -j DROP
    else "$fw" "$action" DOCKER-USER -i "$bridge" ! -o "$bridge" -j DROP; fi
}
dispose() {
    local id service volume ids volumes peers running networks fw chain
    ids=$(d ps -aq --no-trunc --filter "label=$label") || return 1
    for id in $ids; do
        service=$(d inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$id") || return 1
        case $service in
            source-db) identity "$service" source-pg /var/lib/postgresql/data "$id" || return 1 ;;
            cdc-catalog) identity "$service" cdc-pg /var/lib/postgresql "$id" || return 1 ;;
            *) return 1 ;;
        esac
    done
    volumes=$(d volume ls -q --filter "label=$label") || return 1
    for volume in $volumes; do
        case $volume in "${COMPOSE_PROJECT_NAME}_source-pg"|"${COMPOSE_PROJECT_NAME}_cdc-pg") ;; *) return 1 ;; esac
        test "$(d volume inspect -f '{{index .Labels "com.docker.compose.project"}}/{{index .Labels "com.docker.compose.volume"}}' "$volume")" = "$COMPOSE_PROJECT_NAME/${volume#"${COMPOSE_PROJECT_NAME}_"}" || return 1
    done
    peers=$(d network inspect -f '{{range $id, $_ := .Containers}}{{println $id}}{{end}}' "$SOURCE_INPUT_ID" | awk 'NF' | sort) || return 1
    running=$(d ps -q --no-trunc --filter "label=$label" | sort) || return 1
    [[ $peers == "$running" ]] || return 1
    for service in cdc-catalog source-db; do
        id=$(stack ps -aq "$service") || return 1
        [[ -n $id ]] || continue
        stack stop -t 12 "$service" || return 1
        test "$(d inspect -f '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}' "$id")" = 'exited 0 false' || return 1
        echo "$service exited 0 OOMKilled=false"
    done
    stack down --volumes || return 1
    ids=$(d ps -aq --filter "label=$label") && volumes=$(d volume ls -q --filter "label=$label") || return 1
    [[ -z $ids && -z $volumes ]] || return 1
    d network rm "$SOURCE_INPUT_ID" || return 1
    [[ ! -e /sys/class/net/$bridge ]] || return 1
    networks=$(d network ls -q --filter "name=^${COMPOSE_PROJECT_NAME}-input$") || return 1
    [[ -z $networks ]] || return 1
    for entry in "${rules[@]}"; do
        read -r fw chain <<< "$entry"
        rule -D "$fw" "$chain" || return 1
    done
    echo 'Project containers, volumes, bridge and firewall rules removed'
}
finish() {
    local rc=$? cleanup=0
    trap - EXIT ERR TERM
    if [[ -n ${SOURCE_INPUT_ID:-} ]] && ! dispose; then
        echo "Teardown incomplete. Inspect exact project $COMPOSE_PROJECT_NAME and bridge $SOURCE_INPUT_ID"
        cleanup=1
    else
        rm -f secrets/{source-db,cdc-catalog,source-fixture-reader,source-fixture-writer,publisher}-password "secrets/$COMPOSE_PROJECT_NAME-fixture-id"
        rmdir secrets
    fi
    if [[ $trial == gate && $rc == 0 && $cleanup == 0 ]]; then
        touch "$EVIDENCE/teardown.ok"
    fi
    echo "experiment_exit=$rc cleanup_exit=$cleanup"
    (( cleanup == 0 )) || exit 1
    exit "$rc"
}
trap finish EXIT
test -z "$(d ps -aq --filter "label=$label")"
test -z "$(d ps -q)"
test -z "$(d volume ls -q --filter "label=$label")"
test -z "$(d network ls -q --filter "name=^${COMPOSE_PROJECT_NAME}-input$")"
test ! -e "/sys/class/net/$bridge"
d version --format 'engine={{.Server.Version}}'
d compose version
uname -sr
python3 --version
(cd "$media" && sha256sum -c SHA256SUMS)
test "$(cat "$media/revision")" = "$CDC_REVISION"
python3 scripts/cdc/consumer/image.py verify "$media/consumer.tar"
for archive in source consumer probe runner; do
    timeout --foreground -k 2s 90s docker --host unix:///var/run/docker.sock load -i "$media/$archive.tar"
done
source_image=$(sed -n 's/^    image: //p' compose.source.yaml)
consumer_image=$(sed -n 's/^    image: //p' compose.cdc.yaml)
for image in "$source_image" "$consumer_image" "$SOURCE_RUNNER_IMAGE"; do
    observed=$(d image inspect "$image" -f '{{.Os}}/{{.Architecture}} {{.Id}}')
    echo "$image $observed"
    expected=${image##*@}
    if [[ $image == "$SOURCE_RUNNER_IMAGE" ]]; then expected=$(<"$media/runner.id"); fi
    [[ $expected =~ ^sha256:[0-9a-f]{64}$ && $observed == "linux/amd64 $expected" ]]
done
for account in source-db cdc-catalog source-fixture-reader source-fixture-writer publisher; do
    openssl rand -hex 24 > "secrets/$account-password"
done
chmod 0444 secrets/{source-db,cdc-catalog}-password
cat /proc/sys/kernel/random/uuid > "secrets/$COMPOSE_PROJECT_NAME-fixture-id"
for fw in iptables ip6tables; do
    test "$("$fw" -S FORWARD | awk '$1=="-A" {print; exit}')" = '-A FORWARD -j DOCKER-USER'
done
SOURCE_INPUT_ID=$(d network create --internal --ipv6 --opt "com.docker.network.bridge.name=$bridge" "$COMPOSE_PROJECT_NAME-input")
export SOURCE_INPUT_ID BRIDGE="$bridge"
for fw in iptables ip6tables; do
    for chain in INPUT DOCKER-USER; do
        rule -I "$fw" "$chain"
        rules+=("$fw $chain")
    done
done
d network inspect -f '{{.Id}} {{.Name}} internal={{.Internal}} {{json .IPAM.Config}}' "$SOURCE_INPUT_ID"
stack config > "$EVIDENCE/compose.resolved.yaml"
timeout --foreground -k 2s 75s python3 -u scripts/isolation/preflight.py --start-compose "$PWD/compose.source.yaml"
stack up -d --wait --wait-timeout 30 --no-deps --no-build --pull never source-db
SOURCE_ID=$(d inspect -f '{{.Id}}' "$(stack ps -q source-db)")
test "$(d network inspect -f '{{len .Containers}}' "$SOURCE_INPUT_ID")" = 1
stack up -d --wait --wait-timeout 30 --no-deps --no-build --pull never cdc-catalog
CONSUMER_ID=$(d inspect -f '{{.Id}}' "$(stack ps -q cdc-catalog)")
export SOURCE_ID CONSUMER_ID
test "$(d network inspect -f '{{len .Containers}}' "$SOURCE_INPUT_ID")" = 2
identity source-db source-pg /var/lib/postgresql/data "$SOURCE_ID"
identity cdc-catalog cdc-pg /var/lib/postgresql "$CONSUMER_ID"
for id in "$SOURCE_ID" "$CONSUMER_ID"; do
    d inspect -f '{{.Id}} {{.Image}} {{json .NetworkSettings.Networks}}' "$id"
    d exec --user postgres "$id" sh -ec '
        test "$(ls /sys/class/net | sort | paste -sd " ")" = "eth0 lo"
        awk '\''$2=="00000000" {bad=1} END {exit bad}'\'' /proc/net/route
        awk '\''$2=="00" && $NF!="lo" {bad=1} END {exit bad}'\'' /proc/net/ipv6_route
        readlink /proc/1/ns/net /proc/1/ns/pid
    '
done
d volume inspect -f '{{.Name}} {{json .Labels}}' "${COMPOSE_PROJECT_NAME}_source-pg" "${COMPOSE_PROJECT_NAME}_cdc-pg"
PYTHONPATH=. python3 -u "tests/integration/$controller"
