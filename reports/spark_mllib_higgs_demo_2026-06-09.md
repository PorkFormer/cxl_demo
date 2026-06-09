# Spark MLlib HIGGS Cached-RDD Demo

Date: 2026-06-09

## Summary

This run completes a native Apache Spark MLlib `spark.mllib` cached-RDD demo on the local UCI HIGGS dataset. The demo converts the first `2,000,000` rows to LIBSVM, loads them with `MLUtils.loadLibSVMFile`, persists train/test RDDs with `MEMORY_ONLY`, and trains both:

- Linear SVM via `SVMWithSGD`
- Logistic regression via `LogisticRegressionWithLBFGS`

This is not a completed PIN/SimPoint/Belady proof. It is workload execution evidence for a native cached-RDD Spark MLlib path. Suitability for CPU LC/LLC replacement work still requires a later short PIN trace plus `Belady/LRU` headroom: `<1.05x` reject, `>=1.10x` keep.

## Local Environment

Spark install:

```text
/home/lxy/.phoronix-test-suite/installed-tests/pts/spark-tpch-1.0.0/spark-3.5.0-bin-hadoop3
```

Spark runtime:

```text
Spark: 3.5.0
Scala: 2.12.18
Java: OpenJDK 11.0.31
PySpark: 3.5.0
Python: 3.10.12
```

CPU and cache:

```text
CPU: 2 x Intel Xeon Gold 6326 CPU @ 2.90GHz
Logical CPUs: 64
Cores/socket: 16
Threads/core: 2
L3 cache: 48 MiB (2 instances)
NUMA nodes: 2
```

`numactl --hardware` summary:

```text
available: 2 nodes (0-1)
node 0 cpus: 0-15,32-47, size 515672 MB, free 240863 MB
node 1 cpus: 16-31,48-63, size 257989 MB, free 295 MB
node distances:
  0 -> 0: 10, 0 -> 1: 20
  1 -> 0: 20, 1 -> 1: 10
```

## Source References

Apache Spark documentation used:

- MLlib RDD API guide: https://spark.apache.org/docs/3.5.0/mllib-guide.html
- MLlib linear methods: https://spark.apache.org/docs/3.5.0/mllib-linear-methods.html
- RDD persistence guide: https://spark.apache.org/docs/3.5.6/rdd-programming-guide.html

Relevant points: Spark documents `spark.mllib` as the RDD-based API; linear methods include linear SVM and logistic regression; examples use `MLUtils.loadLibSVMFile`, split RDDs, and cache training data; Spark persistence keeps computed RDD partitions in memory for reuse by later actions, which is the important native cached-RDD behavior for this demo.

## Data

Existing local dataset:

```text
Path: /tmp/cxl_xgboost_higgs/HIGGS.csv.gz
SHA256: ea302c18164d4e3d916a1e2e83a9a8d07069fa6ebc7771e4c0540d54e593b698
```

Materialized Spark-friendly subset:

```text
LIBSVM: /tmp/cxl_spark_mllib_higgs/higgs_2000000_rows_28_features.libsvm
Metadata: /tmp/cxl_spark_mllib_higgs/higgs_2000000_rows_28_features.metadata.json
Rows: 2,000,000
Features: 28
LIBSVM SHA256: 75fa9d571870ab2a320a264eeb6933fe609a6ee001ddc5cad70859e51e632a9a
```

The final timed run reused this validated LIBSVM subset (`libsvm_reused: true`). The first run created it and wrote matching metadata.

## Commands

Unit tests:

```bash
python3 -m unittest tests/test_spark_mllib_higgs_demo.py
python3 -m unittest discover -s tests
```

Spark checks:

```bash
SPARK_LOCAL_IP=127.0.0.1 \
  /home/lxy/.phoronix-test-suite/installed-tests/pts/spark-tpch-1.0.0/spark-3.5.0-bin-hadoop3/bin/spark-submit \
  --version
```

Full demo:

```bash
export SPARK_HOME=/home/lxy/.phoronix-test-suite/installed-tests/pts/spark-tpch-1.0.0/spark-3.5.0-bin-hadoop3
export SPARK_LOCAL_IP=127.0.0.1

/usr/bin/time -v \
  "$SPARK_HOME/bin/spark-submit" \
    --master 'local[16]' \
    --driver-memory 32g \
    --conf spark.ui.enabled=false \
    --conf spark.local.dir=/tmp/cxl_spark_mllib_tmp \
    scripts/run_spark_mllib_higgs_demo.py \
      --data /tmp/cxl_xgboost_higgs/HIGGS.csv.gz \
      --rows 2000000 \
      --partitions 64 \
      --svm-iterations 30 \
      --logreg-iterations 30 \
      --output logs/spark_mllib_higgs_demo_metrics.json \
  > logs/spark_mllib_higgs_demo_time.log 2>&1
```

Split workload programs:

```bash
export SPARK_HOME=/home/lxy/.phoronix-test-suite/installed-tests/pts/spark-tpch-1.0.0/spark-3.5.0-bin-hadoop3
export SPARK_LOCAL_IP=127.0.0.1

/usr/bin/time -v \
  "$SPARK_HOME/bin/spark-submit" \
    --master 'local[16]' \
    --driver-memory 32g \
    --conf spark.ui.enabled=false \
    --conf spark.local.dir=/tmp/cxl_spark_mllib_tmp \
    scripts/run_spark_mllib_higgs_svm.py \
      --data /tmp/cxl_xgboost_higgs/HIGGS.csv.gz \
      --rows 2000000 \
      --partitions 64 \
      --iterations 30 \
      --output logs/spark_mllib_higgs_svm_metrics.json \
  > logs/spark_mllib_higgs_svm_time.log 2>&1

/usr/bin/time -v \
  "$SPARK_HOME/bin/spark-submit" \
    --master 'local[16]' \
    --driver-memory 32g \
    --conf spark.ui.enabled=false \
    --conf spark.local.dir=/tmp/cxl_spark_mllib_tmp \
    scripts/run_spark_mllib_higgs_logreg.py \
      --data /tmp/cxl_xgboost_higgs/HIGGS.csv.gz \
      --rows 2000000 \
      --partitions 64 \
      --iterations 30 \
      --output logs/spark_mllib_higgs_logreg_metrics.json \
  > logs/spark_mllib_higgs_logreg_time.log 2>&1
```

Perf attempt:

```bash
SPARK_LOCAL_IP=127.0.0.1 \
perf stat \
  -e cycles,instructions,cache-references,cache-misses,mem_load_retired.l3_hit,mem_load_retired.l3_miss \
  -o logs/spark_mllib_higgs_demo_perf.log \
  "$SPARK_HOME/bin/spark-submit" \
    --master 'local[16]' \
    --driver-memory 32g \
    --conf spark.ui.enabled=false \
    scripts/run_spark_mllib_higgs_demo.py \
      --data /tmp/cxl_xgboost_higgs/HIGGS.csv.gz \
      --rows 2000000 \
      --output logs/spark_mllib_higgs_demo_metrics_perf.json \
  > logs/spark_mllib_higgs_demo_perf_stdout.log \
  2> logs/spark_mllib_higgs_demo_perf_error.log
```

## Results

Final logs:

```text
logs/spark_mllib_higgs_demo_metrics.json
logs/spark_mllib_higgs_demo_time.log
```

Metrics summary:

| Item | Value |
| --- | --- |
| rows | `2,000,000` |
| features | `28` |
| train/test rows | `1,600,161 / 399,839` |
| partitions | `64` |
| storage level | `MEMORY_ONLY` |
| seed | `20260609` |
| LIBSVM reused | `true` |
| materialize seconds | `16.1631936770` |
| JSON total seconds | `73.3484932810` |
| JSON Spark process-tree RSS sample | `11,359.535 MiB` |
| `/usr/bin/time` elapsed | `1:16.01` |
| `/usr/bin/time` max RSS | `10,229,104 KB` |
| `/usr/bin/time` exit status | `0` |

Model results:

| Model | Iterations | Train seconds | Eval seconds | Error rate | Weight length |
| --- | ---: | ---: | ---: | ---: | ---: |
| Linear SVM (`SVMWithSGD`) | `30` | `7.9913942990` | `1.0134370510` | `0.4264416428` | `28` |
| Logistic regression (`LogisticRegressionWithLBFGS`) | `30` | `40.5667270660` | `0.9484349770` | `0.3592546000` | `28` |

## Split Workload Results

Two standalone workload entrypoints now exist for cleaner perf/PIN/Belady attribution:

```text
scripts/run_spark_mllib_higgs_svm.py
scripts/run_spark_mllib_higgs_logreg.py
scripts/spark_mllib_higgs_common.py
```

The original combined entrypoint remains available as `scripts/run_spark_mllib_higgs_demo.py`, but LLC-oriented experiments should prefer one of the standalone scripts.

Standalone run logs:

```text
logs/spark_mllib_higgs_svm_metrics.json
logs/spark_mllib_higgs_svm_time.log
logs/spark_mllib_higgs_logreg_metrics.json
logs/spark_mllib_higgs_logreg_time.log
```

| Workload | Algorithms in metrics | JSON total seconds | `/usr/bin/time` elapsed | `/usr/bin/time` max RSS | Error rate | Weight length |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| SVM-only | `linear_svm` | `30.6490157510` | `0:32.93` | `4,414,756 KB` | `0.4264416428` | `28` |
| LogReg-only | `logistic_regression` | `64.4076434790` | `1:06.94` | `6,248,312 KB` | `0.3592546000` | `28` |

RSS versus local LLC:

```text
Per-socket LLC: 48 MiB
Total LLC instances: 2 x 48 MiB = 96 MiB
/usr/bin/time max RSS: 10,229,104 KB = 9,989.36 MiB
Max RSS / per-socket LLC: 208.1x
Max RSS / total LLC: 104.1x
```

## Perf / LLC Counter Attempt

Perf did not run the workload. It exited with status `255`; no `logs/spark_mllib_higgs_demo_metrics_perf.json` was generated.

Logs:

```text
logs/spark_mllib_higgs_demo_perf.log
logs/spark_mllib_higgs_demo_perf_stdout.log
logs/spark_mllib_higgs_demo_perf_error.log
```

Failure summary:

```text
Access to performance monitoring and observability operations is limited.
perf_event_paranoid setting is 4
```

This blocks PMU LLC counters in the current unprivileged environment.

## CXL / NUMA Template

First confirm which NUMA node, if any, is backed by CXL memory. `numactl --hardware` alone only shows NUMA topology and does not prove node 1 is CXL.

```bash
numactl --hardware
daxctl list
ndctl list
```

Template after mapping is verified:

```bash
export SPARK_HOME=/home/lxy/.phoronix-test-suite/installed-tests/pts/spark-tpch-1.0.0/spark-3.5.0-bin-hadoop3
export SPARK_LOCAL_IP=127.0.0.1
CPU_NODE=0
DRAM_NODE=0
CXL_NODE=1

numactl --cpunodebind=$CPU_NODE --membind=$DRAM_NODE \
  "$SPARK_HOME/bin/spark-submit" \
    --master 'local[16]' \
    --driver-memory 32g \
    --conf spark.ui.enabled=false \
    scripts/run_spark_mllib_higgs_demo.py \
      --data /tmp/cxl_xgboost_higgs/HIGGS.csv.gz \
      --rows 2000000 \
      --output logs/spark_mllib_higgs_demo_metrics_dram.json

numactl --cpunodebind=$CPU_NODE --membind=$CXL_NODE \
  "$SPARK_HOME/bin/spark-submit" \
    --master 'local[16]' \
    --driver-memory 32g \
    --conf spark.ui.enabled=false \
    scripts/run_spark_mllib_higgs_demo.py \
      --data /tmp/cxl_xgboost_higgs/HIGGS.csv.gz \
      --rows 2000000 \
      --output logs/spark_mllib_higgs_demo_metrics_cxl.json
```

## Caveat

This demo exercises real Spark MLlib RDD caching and iterative linear-model training, and the memory footprint is far larger than the local L3 cache. That is useful workload evidence, but it is not direct LC/LLC replacement evidence. The next decision point remains a short PIN trace and Belady/LRU comparison on CPU LLC references.
