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

Local prebuilt executable locations found on this host and used for validation:

```text
/tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad
/tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/sta
/tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/yosys/bin/yosys
```

Those local binaries require:

```text
LD_LIBRARY_PATH=/tmp/openroad_rootfs/opt/or-tools/lib:/tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/lib:/tmp/openroad_rootfs/usr/lib/x86_64-linux-gnu:/tmp/openroad_rootfs/lib/x86_64-linux-gnu
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

Implementation verification and full native workload validation were run after the native-runner change.

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

Full native OpenROAD placement and routing were rerun on 2026-06-10 using the host toolchain under `/tmp/openroad_rootfs`. The default work directory `/tmp/cxl_openroad_orfs` was not reused because its ORFS output directories contained files owned by another user. The full validation used a separate local work directory:

```text
/tmp/cxl_openroad_orfs_native_lxy_local
```

The ORFS source was the existing local checkout at `/tmp/cxl_openroad_orfs/OpenROAD-flow-scripts`, fixed at commit `8abc6a9035ca36490a1577867addca732a87cee8`. The runner copied that checkout into the isolated work directory and ran native `make` commands directly on the host.

Full placement command:

```bash
LD_LIBRARY_PATH=/tmp/openroad_rootfs/opt/or-tools/lib:/tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/lib:/tmp/openroad_rootfs/usr/lib/x86_64-linux-gnu:/tmp/openroad_rootfs/lib/x86_64-linux-gnu \
python3 scripts/run_openroad_orfs_place.py \
  --orfs-repo /tmp/cxl_openroad_orfs/OpenROAD-flow-scripts \
  --work-dir /tmp/cxl_openroad_orfs_native_lxy_local \
  --openroad-exe /tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad \
  --opensta-exe /tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/sta \
  --yosys-exe /tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/yosys/bin/yosys
```

Full routing command:

```bash
LD_LIBRARY_PATH=/tmp/openroad_rootfs/opt/or-tools/lib:/tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/lib:/tmp/openroad_rootfs/usr/lib/x86_64-linux-gnu:/tmp/openroad_rootfs/lib/x86_64-linux-gnu \
python3 scripts/run_openroad_orfs_route.py \
  --orfs-repo /tmp/cxl_openroad_orfs/OpenROAD-flow-scripts \
  --work-dir /tmp/cxl_openroad_orfs_native_lxy_local \
  --openroad-exe /tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad \
  --opensta-exe /tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/sta \
  --yosys-exe /tmp/openroad_rootfs/OpenROAD-flow-scripts/tools/install/yosys/bin/yosys
```

Latest native validation results:

| Entrypoint | Bootstrap | Timed target | Execution mode | Peak memory source | Metrics |
| --- | --- | --- | --- | --- | --- |
| `openroad-orfs-place-aes` | `floorplan` | `do-place` | `native` | `/usr/bin/time -v` max RSS | `logs/openroad_orfs_place_metrics.json` |
| `openroad-orfs-route-aes` | `cts` | `do-route` | `native` | `/usr/bin/time -v` max RSS | `logs/openroad_orfs_route_metrics.json` |

Measured results:

| Entrypoint | Exit status | Timed wall time | Peak RSS | Primary result |
| --- | ---: | ---: | ---: | --- |
| `openroad-orfs-place-aes` | 0 | 274.54 s | 496.246 MiB | `/tmp/cxl_openroad_orfs_native_lxy_local/OpenROAD-flow-scripts/flow/results/nangate45/aes/base/3_place.odb` |
| `openroad-orfs-route-aes` | 0 | 367.69 s | 4459.609 MiB | `/tmp/cxl_openroad_orfs_native_lxy_local/OpenROAD-flow-scripts/flow/results/nangate45/aes/base/5_route.odb` |

The checked-in `logs/openroad_orfs_place_metrics.json`, `logs/openroad_orfs_route_metrics.json`, and the latest appended sections in the matching `*_time.log` files now record successful native runs. Older Docker sections may still appear earlier in the append-only time logs and should be treated as historical records only.

## Caveat

These entrypoints now define native workload execution and stage isolation in the repository, and the default AES placement/routing stages have been validated on the host with the available prebuilt OpenROAD/STA/Yosys binaries. CXL cache evaluation still requires a representative trace window plus a separate Belady/LRU comparison.
