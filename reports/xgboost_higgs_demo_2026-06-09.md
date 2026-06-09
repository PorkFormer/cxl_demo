# XGBoost + HIGGS CPU LC/LLC Demo

日期：2026-06-09

## 结论摘要

本机已跑通一个开源、CPU-only、native workload demo：XGBoost `hist` 训练 UCI HIGGS 子集。该 demo 用真实数据和真实 CPU 训练路径产生了明确的内存占用和 wall time 记录，可作为 LC/LLC replacement 调研的 workload 候选运行证据。

这不是 PIN/SimPoint/Belady 证明，不能直接替代后续 L3 replacement headroom 判定。是否适合保留为 L3 replacement workload 仍需短 PIN trace 加 `Belady/LRU` 对比：`<1.05x` 淘汰，`>=1.10x` 保留。

本文中的 LC/LLC 指 CPU 最后级硬件缓存（本机为 L3 cache）。不使用 GPU cache、网络 cache 或应用层 cache hit ratio 作为 LC/LLC replacement 证据。

## 本机环境

```text
Kernel: Linux 6.8.0-79-generic x86_64
CPU: 2 x Intel Xeon Gold 6326 CPU @ 2.90GHz
Logical CPUs: 64
Threads/core: 2
Cores/socket: 16
L3 cache: 48 MiB (2 instances)
NUMA nodes: 2
```

`numactl --hardware` 摘要：

```text
available: 2 nodes (0-1)
node 0 cpus: 0-15,32-47, size 515672 MB, free 141303 MB
node 1 cpus: 16-31,48-63, size 257989 MB, free 2187 MB
node distances:
  0 -> 0: 10, 0 -> 1: 20
  1 -> 0: 20, 1 -> 1: 10
```

## 数据下载

数据源：UCI HIGGS public dataset

URL:

```text
https://archive.ics.uci.edu/ml/machine-learning-databases/00280/HIGGS.csv.gz
```

执行命令：

```bash
mkdir -p /tmp/cxl_xgboost_higgs
curl -fL --retry 3 -C - \
  -o /tmp/cxl_xgboost_higgs/HIGGS.csv.gz \
  https://archive.ics.uci.edu/ml/machine-learning-databases/00280/HIGGS.csv.gz
sha256sum /tmp/cxl_xgboost_higgs/HIGGS.csv.gz
```

下载结果：

```text
Path: /tmp/cxl_xgboost_higgs/HIGGS.csv.gz
Size: 2.7G
SHA256: ea302c18164d4e3d916a1e2e83a9a8d07069fa6ebc7771e4c0540d54e593b698
```

## Python 环境

记录来自 `logs/xgboost_higgs_demo_metrics.json`：

```text
Python: 3.10.12
XGBoost: 3.1.2
scikit-learn: 1.7.2
pandas: 2.3.1
NumPy: 1.26.4
psutil: 7.1.0
```

环境验证命令：

```bash
python3 -c 'import xgboost, sklearn, pandas, numpy, psutil'
command -v curl
command -v perf
command -v numactl
command -v sha256sum
```

## Native Demo 命令

脚本：

```text
scripts/run_xgboost_higgs_demo.py
```

执行命令：

```bash
/usr/bin/time -v \
  python3 scripts/run_xgboost_higgs_demo.py \
    --data /tmp/cxl_xgboost_higgs/HIGGS.csv.gz \
    --rows 2000000 \
    --rounds 50 \
    --threads 16 \
    --max-depth 10 \
    --output logs/xgboost_higgs_demo_metrics.json \
  > logs/xgboost_higgs_demo_time.log 2>&1
```

XGBoost 关键参数：

```json
{
  "objective": "binary:logistic",
  "eval_metric": "auc",
  "tree_method": "hist",
  "device": "cpu",
  "nthread": 16,
  "max_depth": 10,
  "max_bin": 256,
  "eta": 0.1,
  "seed": 20260609
}
```

## Native Demo 结果

结果文件：

```text
logs/xgboost_higgs_demo_metrics.json
logs/xgboost_higgs_demo_time.log
```

结果摘要：

| 项目 | 值 |
| --- | --- |
| loaded rows | `2,000,000` |
| features | `28` |
| train/test split | `1,600,000 / 400,000` |
| rounds | `50` |
| threads | `16` |
| max_depth | `10` |
| max_bin | `256` |
| AUC | `0.8216797614` |
| JSON load_seconds | `34.067675` |
| JSON train_seconds | `5.728202` |
| JSON total_seconds | `45.986230` |
| `/usr/bin/time` elapsed | `0:46.93` |
| `/usr/bin/time` max RSS | `1,476,084 KB` |
| JSON peak RSS | `1,441.49 MiB` |

RSS 对 L3 压力：

```text
Per-socket LLC: 48 MiB
Total LLC instances: 2 x 48 MiB = 96 MiB
Peak RSS: 1,441.49 MiB
Peak RSS / per-socket LLC: 30.0x
Peak RSS / total LLC: 15.0x
```

因此本次 native demo 明显超过 `192 MiB` RSS 验收目标，并且 wall time 小于 10 分钟。

## Perf / LLC Counter 尝试

尝试命令：

```bash
perf stat \
  -e cycles,instructions,cache-references,cache-misses,mem_load_retired.l3_hit,mem_load_retired.l3_miss \
  -o logs/xgboost_higgs_demo_perf.log \
  python3 scripts/run_xgboost_higgs_demo.py \
    --data /tmp/cxl_xgboost_higgs/HIGGS.csv.gz \
    --rows 2000000 \
    --rounds 50 \
    --threads 16 \
    --max-depth 10 \
    --output logs/xgboost_higgs_demo_metrics_perf.json
```

本机 `perf` 未能采集 PMU counters。失败原因保存在：

```text
logs/xgboost_higgs_demo_perf_error.log
```

失败摘要：

```text
Access to performance monitoring and observability operations is limited.
perf_event_paranoid setting is 4
```

`logs/xgboost_higgs_demo_perf.log` 只包含 perf 启动时间戳，`logs/xgboost_higgs_demo_metrics_perf.json` 未生成，因为 workload 未被 perf 启动。

## CXL/NUMA 复现实验模板

先确认 NUMA 和 CXL memory node 映射：

```bash
numactl --hardware
```

模板：

```bash
CPU_NODE=0
DRAM_NODE=0
CXL_NODE=1

numactl --cpunodebind=$CPU_NODE --membind=$DRAM_NODE \
  python3 scripts/run_xgboost_higgs_demo.py \
    --data /tmp/cxl_xgboost_higgs/HIGGS.csv.gz \
    --rows 2000000 \
    --rounds 50 \
    --threads 16 \
    --max-depth 10 \
    --output logs/xgboost_higgs_demo_metrics_dram.json

numactl --cpunodebind=$CPU_NODE --membind=$CXL_NODE \
  python3 scripts/run_xgboost_higgs_demo.py \
    --data /tmp/cxl_xgboost_higgs/HIGGS.csv.gz \
    --rows 2000000 \
    --rounds 50 \
    --threads 16 \
    --max-depth 10 \
    --output logs/xgboost_higgs_demo_metrics_cxl.json
```

注意：本机 `numactl --hardware` 只能显示 NUMA node，不自动证明 node 1 是 CXL memory。正式 CXL 对比前需要用平台拓扑、`daxctl`/`ndctl` 或 BIOS/内核暴露的信息确认 CXL node。

## 日志索引

| 路径 | 说明 |
| --- | --- |
| `scripts/run_xgboost_higgs_demo.py` | CPU-only XGBoost HIGGS runner |
| `logs/xgboost_higgs_demo_metrics.json` | 本次 native run JSON metrics |
| `logs/xgboost_higgs_demo_time.log` | `/usr/bin/time -v` 日志 |
| `logs/xgboost_higgs_demo_perf.log` | perf timestamp-only output |
| `logs/xgboost_higgs_demo_perf_error.log` | perf 权限失败信息 |
| `/tmp/cxl_xgboost_higgs/HIGGS.csv.gz` | UCI HIGGS 数据文件，不放入 repo |

## 后续判定

本 demo 已满足 native workload 复现要求：真实开源数据、CPU-only hist training、固定参数、版本记录、SHA256、wall time、RSS 和 perf 权限状态。

下一步若要决定是否纳入 LC/LLC replacement 评测集合，需要补：

```text
short PIN trace -> cache simulation -> Belady/LRU headroom
```

保留/淘汰阈值沿用：

```text
Belady/LRU < 1.05x: 淘汰
Belady/LRU >= 1.10x: 保留
1.05x <= Belady/LRU < 1.10x: 视 trace 稳定性和采样覆盖再判定
```
