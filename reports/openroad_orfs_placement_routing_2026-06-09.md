# OpenROAD ORFS Placement and Routing Stage Entrypoints

Date: 2026-06-09
Host workspace: `/data/home/lxy/cxl_demo`

## Summary

OpenROAD-flow-scripts is kept as one EDA workload family, but this repository now exposes two independent AES stage entrypoints:

```text
openroad-orfs-place-aes
openroad-orfs-route-aes
```

Both use the same default input:

```text
designs/nangate45/aes/config.mk
```

The split is by ORFS execution stage, not by design size. Other designs such as `jpeg` can still be selected manually with `--design-config`, but they are not automatic defaults and are not counted as separate candidates here.

## Entrypoints

Placement bootstraps through floorplan, then times placement:

```bash
python3 scripts/run_openroad_orfs_place.py
```

Default timed command inside Docker:

```bash
make -C flow DESIGN_CONFIG=designs/nangate45/aes/config.mk do-place
```

Routing bootstraps through CTS, then times routing:

```bash
python3 scripts/run_openroad_orfs_route.py
```

Default timed command inside Docker:

```bash
make -C flow DESIGN_CONFIG=designs/nangate45/aes/config.mk do-route
```

The runner mounts the checked-out ORFS repository at:

```text
/work/OpenROAD-flow-scripts
```

and explicitly points ORFS at the Docker image toolchain:

```text
OPENROAD_EXE=/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad
OPENSTA_EXE=/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/sta
YOSYS_EXE=/usr/local/bin/yosys
```

## Fixed Versions

Default ORFS repository:

```text
https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git
```

Default ORFS commit:

```text
8abc6a9035ca36490a1577867addca732a87cee8
```

Default Docker image:

```text
openroad/orfs
```

Local image digest used in the recorded run:

```text
openroad/orfs@sha256:e4e71714221bbabba09242c03d3c093af07f6231d4a76de17ecc6408061c6802
```

Default Docker memory cap:

```text
64g
```

Default work directory:

```text
/tmp/cxl_openroad_orfs
```

## Metrics and Logs

Placement metrics:

```text
logs/openroad_orfs_place_metrics.json
```

Placement host `/usr/bin/time -v` log:

```text
logs/openroad_orfs_place_time.log
```

Routing metrics:

```text
logs/openroad_orfs_route_metrics.json
```

Routing host `/usr/bin/time -v` log:

```text
logs/openroad_orfs_route_time.log
```

ORFS output paths for the default AES design:

```text
/tmp/cxl_openroad_orfs/OpenROAD-flow-scripts/flow/logs/nangate45/aes
/tmp/cxl_openroad_orfs/OpenROAD-flow-scripts/flow/results/nangate45/aes
/tmp/cxl_openroad_orfs/OpenROAD-flow-scripts/flow/reports/nangate45/aes
```

Each JSON metrics file records workload name, ORFS source and commit, Docker mode/image/digest/memory cap, design config, bootstrap stage, timed stage, full command, exit status, wall time, Docker peak memory sampled from `docker stats`, raw stats samples, the `/usr/bin/time -v` log path, ORFS output paths, and an `error` field. The error field is present even for successful runs as `null`.

## Local Execution Status

Implementation verification run on 2026-06-09:

```bash
python3 -m unittest discover -s tests
python3 -m py_compile scripts/openroad_orfs_common.py scripts/run_openroad_orfs_place.py scripts/run_openroad_orfs_route.py
docker --version
python3 scripts/run_openroad_orfs_place.py
python3 scripts/run_openroad_orfs_route.py
python3 -m json.tool logs/openroad_orfs_place_metrics.json
python3 -m json.tool logs/openroad_orfs_route_metrics.json
```

Observed Docker version:

```text
Docker version 26.1.3, build b72abbb
```

Docker mode is `auto`: the runner tries direct `docker` first and falls back to `sg docker -c ...` if direct Docker is unavailable. This host used direct Docker.

Recorded AES stage results:

| Entrypoint | Bootstrap | Timed target | Exit | Timed wall seconds | Docker peak MiB | Metrics |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `openroad-orfs-place-aes` | `floorplan` | `do-place` | 0 | 192.918 | 463.700 | `logs/openroad_orfs_place_metrics.json` |
| `openroad-orfs-route-aes` | `cts` | `do-route` | 0 | 238.757 | 4443.136 | `logs/openroad_orfs_route_metrics.json` |

The host `/usr/bin/time -v` RSS in the metrics is for the Docker client wrapper. Use `container_peak_memory_mib` for the ORFS container working set.

## Caveat

These entrypoints prove native workload execution and stage isolation. They do not prove that the workload is useful for PIN tracing, Belady analysis, LLC replacement, or CXL cache evaluation. That still requires a representative trace window and a separate Belady/LRU comparison.
