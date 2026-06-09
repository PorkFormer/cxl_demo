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

Default timed command on the native host:

```bash
make -C /tmp/cxl_openroad_orfs/OpenROAD-flow-scripts/flow DESIGN_CONFIG=designs/nangate45/aes/config.mk do-place
```

Routing bootstraps through CTS, then times routing:

```bash
python3 scripts/run_openroad_orfs_route.py
```

Default timed command on the native host:

```bash
make -C /tmp/cxl_openroad_orfs/OpenROAD-flow-scripts/flow DESIGN_CONFIG=designs/nangate45/aes/config.mk do-route
```

The runner checks out ORFS at:

```text
/tmp/cxl_openroad_orfs/OpenROAD-flow-scripts
```

The runner no longer starts Docker. It runs `make` directly on the host and lets ORFS use native tool paths. The paths can be supplied explicitly:

```text
--openroad-exe /path/to/openroad
--opensta-exe /path/to/sta
--yosys-exe /path/to/yosys
```

If those arguments are omitted, the runner preserves existing `OPENROAD_EXE`, `OPENSTA_EXE`, and `YOSYS_EXE` environment variables, then tries the ORFS `tools/install` layout, then `PATH`.

## Fixed Versions

Default ORFS repository:

```text
https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git
```

Default ORFS commit:

```text
8abc6a9035ca36490a1577867addca732a87cee8
```

Default work directory:

```text
/tmp/cxl_openroad_orfs
```

Default native executable locations, when ORFS has been installed under the work directory:

```text
/tmp/cxl_openroad_orfs/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad
/tmp/cxl_openroad_orfs/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/sta
/tmp/cxl_openroad_orfs/OpenROAD-flow-scripts/tools/install/yosys/bin/yosys
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

Each new JSON metrics file records workload name, ORFS source and commit, `execution.mode = native`, native toolchain paths, design config, bootstrap stage, timed stage, full command, exit status, wall time, peak memory from `/usr/bin/time -v`, the time log path, ORFS output paths, and an `error` field. The error field is present even for successful runs as `null`.

## Local Execution Status

Implementation verification run after the native-runner change:

The native OpenROAD smoke checks used:

```text
LD_LIBRARY_PATH=/tmp/openroad_rootfs/opt/or-tools/lib:/tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/lib:/tmp/openroad_rootfs/usr/lib/x86_64-linux-gnu:/tmp/openroad_rootfs/lib/x86_64-linux-gnu
```

```bash
python3 -m unittest tests.test_openroad_orfs_runner -v
python3 -m py_compile scripts/openroad_orfs_common.py scripts/run_openroad_orfs_place.py scripts/run_openroad_orfs_route.py
python3 -m unittest discover -s tests
/tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad -version
make -C /tmp/cxl_openroad_orfs/OpenROAD-flow-scripts/flow DESIGN_CONFIG=designs/nangate45/aes/config.mk check-openroad
python3 scripts/run_openroad_orfs_place.py --skip-bootstrap --timed-target check-openroad --output /tmp/openroad_native_check_metrics.json --time-log /tmp/openroad_native_check_time.log --openroad-exe /tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad --opensta-exe /tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/sta --yosys-exe /tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/yosys/bin/yosys
```

Native runner checks covered:

```text
build_native_make_command emits make -C /tmp/cxl_openroad_orfs/OpenROAD-flow-scripts/flow ...
build_native_tool_env exports only native OPENROAD_EXE, OPENSTA_EXE, and YOSYS_EXE overrides
run_orfs_workload writes execution.mode = native and no docker metrics field on failure
OpenROAD placement/routing parser defaults still select AES floorplan/do-place and CTS/do-route
OpenROAD native smoke reports version 26Q2-1846-g49bd051a10
ORFS check-openroad exits 0 using native OPENROAD_EXE/OPENSTA_EXE/YOSYS_EXE
Runner check-openroad exits 0 with execution.mode = native and full_command = /usr/bin/time -v make -C ...
```

Full OpenROAD placement/routing was not rerun during this code change to avoid launching a multi-minute EDA workload while another user's OpenROAD job was active on the host. The native runner was verified with the lightweight `check-openroad` target using explicit host tool paths under `/tmp/openroad_rootfs`. For normal use, install ORFS tools under the work directory, put `openroad`, `sta`, and `yosys` on `PATH`, or pass explicit tool paths with the `--openroad-exe`, `--opensta-exe`, and `--yosys-exe` arguments.

The checked-in `logs/openroad_orfs_place_metrics.json`, `logs/openroad_orfs_route_metrics.json`, and matching `*_time.log` files are historical pre-change Docker run artifacts. They should not be used as evidence for the current native runner.

Expected new native metrics fields:

| Entrypoint | Bootstrap | Timed target | Execution mode | Peak memory source | Metrics |
| --- | --- | --- | --- | --- | --- |
| `openroad-orfs-place-aes` | `floorplan` | `do-place` | `native` | `/usr/bin/time -v` max RSS | `logs/openroad_orfs_place_metrics.json` |
| `openroad-orfs-route-aes` | `cts` | `do-route` | `native` | `/usr/bin/time -v` max RSS | `logs/openroad_orfs_route_metrics.json` |

## Caveat

These entrypoints now define native workload execution and stage isolation in the repository. A full native placement/routing run still requires a usable host OpenROAD/STA/Yosys toolchain, and CXL cache evaluation still requires a representative trace window plus a separate Belady/LRU comparison.
