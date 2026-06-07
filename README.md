# CXL Demo / HPC Benchmark 复现实验说明

本文记录 `/data/home/lxy/cxl_demo` 上已经完成的一组 HPC benchmark demo。当前内容面向复现实验者：先说明本机环境和已安装组件，再列出已完成结果、日志位置，以及如何用现有安装重新运行主要步骤。

本实验不是完整性能评测报告；结果用于确认 benchmark、依赖和 POT3D 流程能在本机跑通。

注：部分历史日志中路径显示为 `/home/lxy/cxl_demo`；在本机上该路径与 `/data/home/lxy/cxl_demo` 解析到同一个实际目录。

## 项目概览

本机环境为 Ubuntu 22.04，主要运行过以下 demo：

| 类别 | 组件 | 用途 |
| --- | --- | --- |
| PTS smoke | `pts/compress-7zip-1.13.0` | 快速 CPU 压缩/解压基准 |
| PTS workload | `pts/openfoam-1.2.0` / OpenFOAM 10 | CFD benchmark demo |
| PTS workload | `pts/incompact3d-2.1.1` / Xcompact3d Incompact3d 5.0 | CFD/DNS benchmark demo |
| 手动构建 | `src/POT3D` / POT3D 4.6.4 | MPI + HDF5 Fortran 程序测试和 `bench_tiny` demo |

## 环境摘要

系统信息来自 `logs/pts_system_info.log`，工具路径来自当前机器查询。

| 项目 | 当前值 |
| --- | --- |
| CPU | `2 x Intel Xeon Gold 6326 @ 3.50GHz` |
| 核心/线程 | `32` cores / `64` threads |
| 内存 | `24 x 32GB DDR4-3200MT/s` |
| OS | Ubuntu 22.04 |
| Kernel | `6.8.0-79-generic (x86_64)` |
| CPU scaling | `intel_cpufreq schedutil` |
| PTS | Phoronix Test Suite `v10.8.6`, executable: `/home/lxy/.local/bin/phoronix-test-suite` |
| PTS 用户目录 | `/home/lxy/.phoronix-test-suite` |
| MPI | Open MPI `4.1.2`, executable: `/usr/bin/mpirun` |
| HDF5 | HDF5 `1.10.7`, OpenMPI flavor, installation point: `/usr` |
| HDF5 wrappers | `/usr/bin/h5pcc`, `/usr/bin/h5pfc` |
| POT3D executable | `src/POT3D/bin/pot3d` |

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `logs/` | 本次实验保留的终端日志和 benchmark 输出摘要 |
| `src/POT3D/` | POT3D 源码、配置、测试集、benchmark 输入和已构建二进制 |
| `src/POT3D/bin/pot3d` | 当前可运行的 POT3D 可执行文件 |
| `src/POT3D/benchmarks/bench_tiny/` | `bench_tiny` 输入和运行输出目录 |
| `/home/lxy/.phoronix-test-suite/installed-tests/` | PTS 已安装测试 |
| `/home/lxy/.phoronix-test-suite/test-results/` | PTS 结果目录，包含 `pts-smoke-test`、`openfoam-demo`、`xcompact3d-demo` |

## 已完成结果

| Benchmark | 配置 | 结果 | 来源 |
| --- | --- | --- | --- |
| PTS `compress-7zip` | Compression Rating | `201330 MIPS` average, deviation `0.69%` | `logs/pts_smoke_test.log` |
| PTS `compress-7zip` | Decompression Rating | `137481 MIPS` average, deviation `1.22%` | `logs/pts_smoke_test.log` |
| OpenFOAM 10 | `drivaerFastback, Small Mesh Size` mesh time | `46.734443 s` | `logs/openfoam_demo.log` |
| OpenFOAM 10 | `drivaerFastback, Small Mesh Size` execution time | `123.97334 s` | `logs/openfoam_demo.log` |
| Incompact3D | `Cavity` | `854.080658 s` average, `2.38%` deviation, `4` samples | `logs/xcompact3d_demo.log` |
| POT3D testsuite | `potential_field_source_surface` | `PASS`, runtime `36.884 s` | `logs/pot3d_testsuite.log` |
| POT3D testsuite | `potential_field_current_sheet` | `PASS`, runtime `85.229 s` | `logs/pot3d_testsuite.log` |
| POT3D testsuite | `open_field` | `PASS`, runtime `116.180 s` | `logs/pot3d_testsuite.log` |
| POT3D `bench_tiny` | `mpirun -np 4` | `13799` iterations, total time `3346.882166 s`, wall time `55:47.37`, exit status `0` | `logs/pot3d_bench_tiny.log` |

POT3D `bench_tiny` 日志显示读取输入文件 `br_input_small.h5`，最终 field solver converged，退出码为 `0`。

## 复现命令

以下命令默认从项目根目录执行，复跑日志写入 `*.rerun.log`，避免覆盖当前归档日志。

### 1. 基础环境确认

```bash
cd /data/home/lxy/cxl_demo
export PATH="$HOME/.local/bin:$PWD/src/POT3D/bin:$PATH"

phoronix-test-suite system-info | tee logs/pts_system_info.rerun.log
mpirun --version
h5pcc -showconfig | head -n 30
```

### 2. 复跑 PTS demos

PTS 已有结果名位于 `/home/lxy/.phoronix-test-suite/test-results/`。`batch-run` 可以使用这些 Test Result 名称复跑对应测试和当时的测试选择。

```bash
cd /data/home/lxy/cxl_demo
export PATH="$HOME/.local/bin:$PATH"

phoronix-test-suite batch-run pts-smoke-test | tee logs/pts_smoke_test.rerun.log
phoronix-test-suite batch-run openfoam-demo | tee logs/openfoam_demo.rerun.log
phoronix-test-suite batch-run xcompact3d-demo | tee logs/xcompact3d_demo.rerun.log
```

如果需要重新从测试 profile 运行，而不是复用已有结果定义，可使用：

```bash
phoronix-test-suite benchmark pts/compress-7zip
phoronix-test-suite benchmark pts/openfoam
phoronix-test-suite benchmark pts/incompact3d
```

### 3. 复跑 POT3D testsuite

当前二进制已经存在于 `src/POT3D/bin/pot3d`。如果只复跑 testsuite，不需要重新构建。

```bash
cd /data/home/lxy/cxl_demo/src/POT3D/testsuite
export PATH="$(cd .. && pwd)/bin:$PATH"

./run_test_suite.sh -np=4 | tee ../../../logs/pot3d_testsuite.rerun.log
```

如需重新构建 POT3D，当前生成的 `src/POT3D/src/Makefile` 对应 OpenMPI HDF5 wrapper，可用：

```bash
cd /data/home/lxy/cxl_demo/src/POT3D
./build.sh conf/gcc_cpu_ubuntu_openmpi_wrapper.conf 2>&1 | tee ../../logs/pot3d_build.rerun.log
```

### 4. 复跑 POT3D `bench_tiny`

该 workload 运行时间较长，本次记录 wall time 约 `55:47.37`。

```bash
cd /data/home/lxy/cxl_demo/src/POT3D/benchmarks/bench_tiny

/usr/bin/time -v mpirun -np 4 ../../bin/pot3d pot3d.dat 2>&1 | tee ../../../../logs/pot3d_bench_tiny.rerun.log
```

## 日志索引

| 日志 | 用途 |
| --- | --- |
| `logs/pts_system_info.log` | PTS 采集的硬件、系统、编译器和 CPU scaling 信息 |
| `logs/pts_smoke_test.log` | `pts/compress-7zip` smoke benchmark 安装/运行记录和 MIPS 结果 |
| `logs/openfoam_demo.log` | PTS OpenFOAM 安装与 `drivaerFastback, Small Mesh Size` 运行结果 |
| `logs/xcompact3d_demo.log` | PTS Incompact3D `Cavity` 运行结果 |
| `logs/pot3d_build.log` | POT3D 构建记录，生成 `src/POT3D/bin/pot3d` |
| `logs/pot3d_testsuite.log` | POT3D testsuite 三个用例的 PASS/FAIL 汇总 |
| `logs/pot3d_bench_tiny.log` | POT3D `bench_tiny` 迭代数、总耗时、wall time、资源统计和退出码 |

## 注意事项

1. CPU scaling governor 当前不是 `performance`，PTS 日志中给出过性能提示；复跑结果可能受频率策略影响。
2. Incompact3D 日志中 `Estimated Trial Run Count` 为 `3`，实际记录了 `4` 个 samples。PTS 可能为了稳定性追加动态样本。
3. OpenFOAM 通过 PTS 安装和构建时依赖系统开发包；如果复跑时报 SCOTCH/ptscotch headers 缺失，先检查相关系统依赖。
4. `src/POT3D/benchmarks/bench_tiny/` 当前没有生成 `br.h5`；本次成功运行读取的是 `br_input_small.h5`，日志退出码为 `0`。
5. benchmark 耗时会随 CPU governor、系统负载、PTS 采样策略、MPI/HDF5 库版本变化；以 `logs/*.log` 中的记录作为本次实验基线。
