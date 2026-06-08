# CXL Tiered Memory 场景下的 Workload 访存特征提取工作流

## 文档目的

这份文档描述了一整套工作流：从"找到合适的 workload"，到"采集它的内存访问 trace"，再到"把 trace 处理成缓存模拟器能用的格式"。目标是让一个没有相关背景的读者也能理解每一步在做什么、为什么要这么做。

---

## 0. 背景与术语

### 0.1 我们到底在做什么？

现代服务器可以用 **CXL（Compute Express Link）** 技术来扩展内存——在普通 DRAM 之外再挂一块 CXL 内存，构成两级内存层级：

```
CPU → L1 Cache → L2 Cache → L3 Cache → DRAM → CXL Memory
       <1ns        ~5ns       ~20ns     ~80ns    ~250ns
```

DRAM 快但贵且容量有限，CXL 慢但便宜且可以很大。关键问题是：**L3 缓存应该如何决定哪些数据留在 cache 里，哪些驱逐到 CXL 去？**

如果 L3 把"马上又要被访问"的热数据踢出去了，CPU 就得从慢 3 倍的 CXL 去取，性能损失巨大。所以 **L3 Cache Replacement 策略** 直接决定了 CXL 场景下的性能。

### 0.2 术语表

| 术语 | 全称 | 含义 |
|------|------|------|
| **CXL** | Compute Express Link | 一种新的内存扩展总线，允许服务器挂接额外内存 |
| **Temporal Locality** | 时间局部性 | "刚访问过的数据，马上又会被访问"——这是缓存能起效的根本原因 |
| **Reuse Distance** | 重用距离 | 同一个内存地址两次被访问之间，间隔了多少次"其他访存"。间隔短 = locality 强 |
| **SimPoint** | - | UCSD 的一个工具，能从完整程序执行中"挑出几个最有代表性的一小段"用于仿真，避免仿真整段程序 |
| **BBV** | Basic Block Vector | 基本块频率向量：把程序执行划分成间隔（interval），每个间隔统计"哪个基本块被执行了多少次"，形成一个向量。SimPoint 对这些向量做聚类 |
| **PIN** | Intel PIN | Intel 的动态二进制插桩工具。可以在程序运行时"注入"分析代码，记录每次访存的地址/类型/大小 |
| **BBL** | Basic Block | 基本块：一段没有分支的连续指令序列。PIN 以 BBL 为单位做插桩 |
| **RDP** | Reuse Distance Prediction | 预测某个地址下一次被访问的"距离"，用于决定是否值得保留在缓存中 |
| **RPP** | Reuse Page Predictor | 基于 page 级别的 reuse distance 预测器，SilkLoom/MockingJay 的核心组件 |
| **Belady** | Belady's OPT | 理论最优缓存替换算法——"踢掉未来最晚才被用到的那个"。实际不可能实现，但可作为性能上界 |
| **PRF** | Page Reuse Frequency | Page 级的复用频率分布，用于判断 workload 的 locality 特征 |
| **HNSW** | Hierarchical Navigable Small World | 一种近似最近邻搜索的图索引结构，Milvus/Qdrant 等向量数据库底层用的就是这个 |
| **Zipfian** | Zipf 分布 | 一种"少数极热、多数极冷"的概率分布。θ 越大越集中。YCSB 用它来模拟"热 key"现象 |
| **YCSB** | Yahoo! Cloud Serving Benchmark | 标准的 KV 存储性能测试工具，支持多种读写比例和访问分布 |

### 0.3 为什么 PIN trace 比直接跑模拟器好？

Champsim 这类缓存模拟器需要 **逐条访存 trace** 作为输入——"CPU 在指令 N 访问了地址 X，读 4 字节"。PIN 可以在真实程序运行时准确记录这些信息。相比之下，直接从程序代码推导访存行为是极其困难的（因为有数据依赖、分支预测、OS 调度等复杂因素）。

---

## 1. 完整工作流

```
                        一个 cycle 通常需要数小时
                        ========================

  ① 选择 Workload         ② Phase 1: BBV 采集        ③ Phase 2: SimPoint 聚类
  (YCSB / ML / etc)       (pin_bbv.so)              (simpoint 命令)
       │                      │                          │
       │             ┌─────── │ 程序在 PIN 下运行        │ 对 BBV 做 k-means
       │             │        │ 每 2 亿条指令为一个       │ 找出"代表性阶段"
       │             │        │ interval，输出 .bb 文件   │
       │             │        │                          │
       ▼             ▼        ▼                          ▼
  特点:             轻量(~10min)              瞬间(~1sec)
  - Memory footprint > L3
  - Temporal locality 强
  - Zipfian/Pareto 分布
       │
       ▼
  ④ Phase 3: 定向 Trace 采集         ⑤ Phase 4: Trace 处理              ⑥ 模拟器分析
  (pinatrace_icount.so)             (get_page_area → belady →       (Champsim / mainCache)
       │                              heat_bin → xz)                    │
       │                                     │                          │
       │ 在 SimPoint 选中的阶段            每条访存记录被标注         对比 LRU / Hawkeye /
       │ 采集 50M warmup + 1B sim          area (DRAM/CXL) 和         MockingJay / RPP
       │ 的完整访存 trace                  next-access 距离           的 CXL miss 率
       │                                     │
       ▼                                     ▼
  瓶颈(~数小时)                    瓶颈(~数小时, 单线程)
  PIN 对每条访存插桩                belady 反向扫描计算
  程序被拖慢 100-1000x              next-access 距离
```

---

## 2. 各阶段详解

### 2.1 Phase 1: BBV 采集（~10 分钟）

**做什么**：让程序在 PIN + pin_bbv.so 下运行，每 2 亿条指令输出一行频率向量。

**为什么**：SimPoint 需要这些向量来聚类。这一步用的是轻量插桩（只统计基本块执行次数，不记录具体访存），所以很快。

**产出的 .bb 文件格式**：
```
T:BB_ID1:Count1 :BB_ID2:Count2 :BB_ID3:Count3 ...
```
每行是一个 interval。`BB_ID1` 是某个基本块的编号，`Count1` 是它在这个 interval 内执行的指令条数。

**类比**：相当于把一部 3 小时的电影每隔 10 秒截一张缩略图。

### 2.2 Phase 2: SimPoint 聚类（~1 秒）

**做什么**：对 Phase 1 的 BBV 做 k-means 聚类，选出每个 cluster 的代表 interval。

**命令**：
```bash
~/simpoint/bin/simpoint \
    -loadFVFile workload.bb \      # 输入的 BBV 文件
    -maxK 10 \                     # 最多分 10 个 cluster
    -saveSimpoints workload.simpoints \    # 输出: 代表 intervals
    -saveSimpointWeights workload.weights  # 输出: 每个 cluster 的权重
```

**输出解读**：
```
workload.simpoints:         workload.weights:
  interval_id cluster_id      weight cluster_id
     56          0            0.36     0
     12          1            0.12     1
     ...
```

这表示：cluster 0 的代表是 interval #56，这个 cluster 占了 36% 的执行时间。**一般选权重最高的那个 interval** 足够。

**为什么需要这一步**：不可能对几小时的程序执行完整仿真。SimPoint 帮我们找到"最有代表性的几个片段"，只仿真这些片段就可以得到接近完整仿真的结果。

### 2.3 Phase 3: 定向 Trace 采集（~数小时）

**做什么**：在 SimPoint 选中的 interval 位置，用 PIN + pinatrace_icount.so 记录 50M warmup + 1B sim 指令的完整访存。

**为什么这么慢**：pinatrace_icount 对程序的**每一条访存指令**都插桩——每次内存读写都要调用一次记录函数。这会把程序拖慢 100-1000 倍。

**关键参数**：
```
-interval_size  200000000     # 和 Phase 1 保持一致
-simpoints      "56"          # Phase 2 选中的 interval
-warmup_length  50000000      # warmup 50M 指令（让 cache 热起来）
-sim_length     1000000000    # 仿真 1B 指令
```

**窗口计算**（为什么 warmup 在 simpoint 之前）：
```
假设 interval #56, interval_size = 200M

  start_icount = 56 × 200M - 50M = 11.15B
  warmup_end   = 56 × 200M = 11.2B         ← simpoint 起点
  end_icount   = 56 × 200M + 1B = 12.2B

  窗口: [11.15B, 12.2B)
  ├─ warmup: [11.15B, 11.2B)  覆盖 interval #55
  └─ sim:    [11.2B, 12.2B)   从 interval #56 开始
```

**warmup 设计的关键**：warmup 必须放在 simpoint interval **之前**，这样 simpoint 选中的代表性阶段才真正落在仿真窗口内，而不是被 warmup "盖掉"。

**输出**：
- `workload_sp56.out`：每行一个访存记录，格式 `R/W <ip> <addr> <size>`
  - `R` = 读，`W` = 写
  - `<ip>` = 触发访存的指令地址
  - `<addr>` = 被访存的内存地址
  - `<size>` = 访存字节数
- `workload_sp56.meta`：记录 warmup/sim 各有多少条访存记录

**RDB 加速技巧**（针对 Redis workload）：
1. 第一次用原生速度 load 数据（不经过 PIN）
2. `BGSAVE` 保存 RDB 文件
3. 以后每次 trace 直接用 RDB 启动 redis（~90 秒），不需要重新 load

### 2.4 Phase 4: Trace 处理 Pipeline（~数小时）

**四步流水线**：

| 步骤 | 工具 | 输入 → 输出 | 做什么 |
|------|------|-------------|--------|
| 1 | `get_page_area` | `.out` → `_area.out` | 为每个内存地址分配 area（0=DRAM, 1=CXL1, 2=CXL2） |
| 2 | `generate_belady_trace` | `_area.out` → `_belady.out` | 反向扫描，计算每个 page 的 next-access 距离 |
| 3 | `generate_belady_heat_trace_bin` | `_belady.out` → `_heat.bin` | 转为紧凑的二进制格式，附加 heat 信息 |
| 4 | `xz_compress` | `_heat.bin` → `.xz` | XZ 压缩，供模拟器读取 |

**步骤 2（belady）是最慢的**：
- 需要对整个 trace 做反向扫描
- 对每个 page 地址维护一个 hash table，记录"下一次被访问的位置"
- O(n × m) 复杂度，其中 m 是唯一 page 数量
- 790M 行 trace 的 belady 需要 1-2 小时（单线程）

**为什么需要 belady trace**：
Belady 的最优替换信息（"这个 page 下一次被访问是多久之后"）是 cache replacement 研究的黄金标准。有了它，模拟器可以：
1. 计算每个策略离最优还有多远
2. 分析哪些 page 被错误逐出
3. 评估 RDP 预测的准确率

---

## 3. Workload 选择标准

### 3.1 要满足什么条件

| 条件 | 为什么 | 如何验证 |
|------|--------|---------|
| Memory footprint > L3 容量 | 否则全命中 L3，无法评估 replacement 策略 | 查 target program 的 RSS |
| Temporal locality 强 | 热 page 反复访问 → RDP 能预测 → 策略才有效 | 从 belady trace 提取 PRF 分布 |
| 访问有冷热之分 | 冷数据放 CXL，热数据放 DRAM+L3 | SimPoint cluster 分布集中 |
| 可被 PIN 稳定插桩 | 程序不能 crash 或被插桩后行为异常 | launch/attach 测试 |
| 执行有稳态阶段 | SimPoint 能选出代表阶段，而非启动/关闭 | BBV 分布分析 |

### 3.2 如何快速判断一个 workload 是否合适

**不需要跑完整流程！** 做了 Phase 1（BBV）后就能判断：

```
Phase 1 完成 → 看 SimPoint 结果
  ├─ 最高权重 > 0.5：行为高度集中 → 适合继续
  ├─ 最高权重 < 0.2：行为碎片化 → 可能不适合
  ├─ intervals < 10：程序太短，或执行不够丰富
  └─ intervals > 1000：程序很长且行为多样 → SimPoint 价值大

Phase 4 belady 完成 → 从 belady.out 提取 PRF
  ├─ P50 reuse distance < L3_size：强 temporal locality
  ├─ P90 reuse distance > L3_size：大部分 page 会 miss L3
  └─ 分布呈 Zipf 形态：CXL+DRAM 分层场景有价值
```

---

## 4. 当前已采集的 Workload

### 4.1 KV Store 系列

| Workload | Footprint | 读/写 | 分布 | Temporal Locality | Trace 大小 | 
|----------|-----------|-------|------|-------------------|-----------|
| **YCSB-A** | 16 GB | 50/50 | Zipfian θ=0.99 | **强** | 7.9 亿 acc / 619M xz |
| **YCSB-B** | 16 GB | 95/5 | Zipfian θ=0.99 | **最强** | 6.9 亿 acc |
| YCSB-C | 80 MB | 100/0 | Zipfian θ=0.99 | 强 | 5.4 亿 acc / 2.4G xz |
| YCSB-F | 80 MB | 50/50 | Zipfian θ=0.99 | 强 | 5.4 亿 acc / 2.4G xz |
| Redis-Rand | 80 MB | 50/50 | Uniform | **弱（对照）** | 2.7 亿 acc / 1.3G xz |
| Facebook-ETC | ~10 GB | Mixed | Pareto | 中 | 3.1 亿 acc |

### 4.2 ML Embedding 系列（C 合成 benchmark）

| Workload | Footprint | 模拟的访问模式 | Temporal Locality |
|----------|-----------|---------------|-------------------|
| DLRM-emb | 4 GB | Zipfian embedding 查表 | 强（少数 hot embedding） |
| KNN | 4 GB | HNSW 图遍历 + 向量读取 | 中（指针追踪 + 局部扫描） |
| ANN | 4 GB | 图遍历(70%) + 随机探索(30%) | 中 |
| GloVe-search | 4 GB | Long-tail 词向量查询 + 顺序扫描 | 强 |

> **说明**：ML 系列用 C 程序 `vector_search_sim` 模拟核心访存特征——它分配大块内存并在上面做 HNSW 风格的图遍历/指针追踪/向量读取。这样做的原因是真实 Milvus/Qdrant 部署需要 Docker，且 PIN 下极慢。合成 benchmark 捕获了核心访存模式但去掉了网络/协议开销。

---

## 5. 性能瓶颈与加速方案

### 5.1 各阶段耗时

| 阶段 | 典型耗时 | 瓶颈根因 | 可加速性 |
|------|---------|---------|---------|
| Phase 1: BBV | ~10 min | PIN BBL 计数（轻量） | ✅ 已很快 |
| Phase 2: SimPoint | ~1 sec | 纯计算（k-means） | ✅ 瞬间 |
| **Phase 3: PIN trace** | **1-4 小时** | PIN 对每条访存插桩 | ❌ PIN 固有限制 |
| **Phase 4: belady** | **1-3 小时** | 单线程 backward scan | ⚠️ 可考虑并行 |
| Phase 4: xz | ~30 min | 压缩 | ✅ 可接受 |

### 5.2 Phase 3 加速技巧

1. **只需要 1B sim**：不要用 2B 或更大的 sim_length，填满就 kill
2. **RDB 模式**（Redis）：避免每次重新 load 数据
3. **launch 优于 attach**：如果程序可以用 PIN launch（`pin -- program`），比 attach 模式（`pin -pid`）更稳定
4. **减小 operation count**：2M ops 可能过多了，1M 已经能产生足够的访存样本

### 5.3 Phase 4 加速技巧

belady 目前是单线程的。但因为它是**按 page 独立计算**的，理论上可以分 chunk 并行：
1. 把 trace 按 page 地址范围分成 N 段
2. 每段独立跑 belady
3. 合并结果

这需要对 `generate_belady_trace` 工具做修改。

---

## 6. 快速验证策略

如果要快速判断"这个 workload 是否值得深入研究"：

| 方法 | 需要什么 | 耗时 | 能回答什么 |
|------|---------|------|-----------|
| **看 SimPoint 权重** | Phase 1 的 .bb 文件 | ~15 min | 行为是否集中 |
| **看 footprint** | `dbsize`（Redis）/ `ps aux` RSS | ~1 sec | 是否真正 > L3 |
| **看 PRF 分布** | Phase 4 belady.out 的前几行 | Phase 3+4 完成后 | temporal locality 强度 |
| **跑一次快仿** | xz 文件 + 模拟器 | ~10 min | 不同策略的 CXL miss 率 |

**最简路径**：
```
Phase 1 (15min) → SimPoint → 高权重? 
  → yes → Phase 3+4 (数小时) → belady.out → PRF 分析
  → no  → 换下一个 workload
```

### 6.1 排除 DB/向量类后的当前推荐

如果排除 Redis、YCSB、Milvus、Qdrant、GloVe、DLRM，当前仓库里最合适的短时真实负载是：

**POT3D `potential_field_current_sheet`**

- 真实负载：POT3D 是真实 HPC potential-field solver，不是随机/线性扫描 microbenchmark。
- 时间局部性：核心阶段是 PCG 迭代，反复访问同一批 stencil 系数、Jacobi preconditioner 和 CG 向量。
- CXL/L3 压力：`101 x 181 x 361` 网格，demo 估算迭代热工作集约 `621 MiB/rank`，超过本机 `48 MiB` L3 的 10 倍。
- 执行时间：已有日志中 `potential_field_current_sheet` 约 `85.229s`，比 Incompact3D `854s` 和 POT3D `bench_tiny` `55:47` 更适合快速筛选。

快速验证命令：

```bash
python3 tools/pot3d_workload_demo.py
```

复跑 workload：

```bash
cd src/POT3D/testsuite
./run_test_suite.sh -np=4 -test=potential_field_current_sheet
```

---

## 7. 部署到新机器

### 7.1 需要拷贝的东西

```
~/simpoint/                              # SimPoint 工具（2.4MB，无依赖）
backend-aware-cache/tools/source/
  ├── pin_bbv.cpp                        # Phase 1 用的 PIN 工具
  ├── pinatrace_icount.cpp               # Phase 3 用的 PIN 工具
  └── vector_search_sim.c                # ML workload 合成 benchmark
backend-aware-cache/tools/Key-Value_workload/
  └── PIN_TRACE_CAPTURE.md               # KV workload 采集流程文档
backend-aware-cache/build/bin/tools/      # Phase 4 处理工具（需 cmake 编译）
~/pin-3.22/                              # Intel PIN toolkit（从 Intel 下载）
```

### 7.2 在新机器上编译

```bash
# 编译 PIN 工具
cp pin_bbv.cpp pinatrace_icount.cpp ~/pin-3.22/source/tools/ManualExamples/
cd ~/pin-3.22/source/tools/ManualExamples/
make obj-intel64/pin_bbv.so obj-intel64/pinatrace_icount.so TARGET=intel64

# 编译 Phase 4 处理工具
cd backend-aware-cache/build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)
```

### 7.3 完整文档索引

| 文档 | 位置 | 内容 |
|------|------|------|
| SimPoint 工作流 | `~/simpoint/SIMPOINT_WORKFLOW.md` | Phase 1-4 的完整命令和参数 |
| KV Trace 采集 | `tools/Key-Value_workload/PIN_TRACE_CAPTURE.md` | RDB 模式 + 并行采集 |
| 本文档 | `CXL_WORKLOAD_WORKFLOW.md` | 全流程概述 + 术语 + 快速验证策略 |
