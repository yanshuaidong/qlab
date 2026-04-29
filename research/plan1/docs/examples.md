# 同向占比计算示例

> 对应脚本：[scripts/run_cooc.py](../scripts/run_cooc.py)  
> 对应方案：[docs/validation_plan_main_force_resonance.md](validation_plan_main_force_resonance.md)

---

## 核心公式回顾

对每个滑动窗口，取序列**末值 − 首值**得到差分 `Δ`，再取符号得到方向 `dir`：

```
Δ = X_last − X_first
dir = +1  （Δ > 0，涨）
dir = -1  （Δ < 0，跌）
dir =  0  （Δ = 0，持平）
```

**同向**：`dir_main == dir_close`（含 0 == 0）  
**严格反向**：两者均非 0 且 `dir_main == −dir_close`  
**同向占比** = 同向窗口数 / 全部有效窗口数

---

## 例一：S = 3，基础示范（5 个交易日）

### 原始数据

| 日期   | main_force | retail | close_price |
|--------|-----------|--------|-------------|
| Day 1  | 100       | 50     | 5000        |
| Day 2  | 105       | 48     | 5100        |
| Day 3  | 110       | 45     | 5200        |
| Day 4  | 108       | 47     | 5150        |
| Day 5  | 115       | 43     | 5300        |

S = 3，stride = 1，共生成 3 个窗口（Day1~Day3、Day2~Day4、Day3~Day5）。

### 逐窗计算

**窗口 1：Day1 → Day3**

```
delta_main   = 110 − 100 = +10   →  dir_main   = +1  （主力净增，涨）
delta_retail = 45  − 50  = −5    →  dir_retail = −1  （散户净减，跌）
delta_close  = 5200 − 5000 = +200→  dir_close  = +1  （价格上涨）

main  ~ close : +1 == +1  ✓ 同向
retail~ close : −1 == +1  ✗ 不同向，且严格反向
main  ~ retail: +1 == −1  ✗ 不同向，严格反向（主力散户分化）
```

**窗口 2：Day2 → Day4**

```
delta_main   = 108 − 105 = +3    →  dir_main   = +1
delta_retail = 47  − 48  = −1    →  dir_retail = −1
delta_close  = 5150 − 5100 = +50 →  dir_close  = +1

main  ~ close : +1 == +1  ✓ 同向
retail~ close : −1 == +1  ✗ 严格反向
main  ~ retail: +1 == −1  ✗ 严格反向
```

**窗口 3：Day3 → Day5**

```
delta_main   = 115 − 110 = +5    →  dir_main   = +1
delta_retail = 43  − 45  = −2    →  dir_retail = −1
delta_close  = 5300 − 5200 = +100→  dir_close  = +1

main  ~ close : +1 == +1  ✓ 同向
retail~ close : −1 == +1  ✗ 严格反向
main  ~ retail: +1 == −1  ✗ 严格反向
```

### 汇总

| 配对           | 同向窗口数 | 总窗口数 | 同向占比 | 严格反向占比 |
|---------------|-----------|---------|---------|-------------|
| main ~ close  | 3         | 3       | **100%**| 0%          |
| retail ~ close| 0         | 3       | 0%      | **100%**    |
| main ~ retail | 0         | 3       | 0%      | **100%**    |

> 这组数据完美符合 H1（主力与价格同向）和 H2（散户与价格反向）假设。

---

## 例二：S = 2，含方向为 0 的情形（6 个交易日）

### 原始数据

| 日期   | main_force | retail | close_price |
|--------|-----------|--------|-------------|
| Day 1  | 200       | 80     | 3000        |
| Day 2  | 210       | 78     | 3050        |
| Day 3  | 210       | 79     | 3000        |
| Day 4  | 205       | 82     | 2950        |
| Day 5  | 200       | 84     | 2980        |
| Day 6  | 208       | 81     | 3020        |

S = 2，stride = 1，共生成 5 个窗口。

### 逐窗计算

| 窗口    | Δ_main | Δ_retail | Δ_close | dir_main | dir_retail | dir_close | main~close | retail~close |
|---------|--------|----------|---------|----------|------------|-----------|------------|--------------|
| D1→D2  | +10    | −2       | +50     | +1       | −1         | +1        | ✓ 同向      | ✗ 反向       |
| D2→D3  | 0      | +1       | −50     | **0**    | +1         | −1        | ✗ 不同向    | ✗ 不同向（非严格反向，因 dir_close=-1 且 dir_retail=+1 → 严格反向）|
| D3→D4  | −5     | +3       | −50     | −1       | +1         | −1        | ✓ 同向      | ✗ 严格反向   |
| D4→D5  | −5     | +2       | +30     | −1       | +1         | +1        | ✗ 严格反向  | ✗ 严格反向（dir_retail=+1 == dir_close=+1 → 同向）|
| D5→D6  | +8     | −3       | +40     | +1       | −1         | +1        | ✓ 同向      | ✗ 严格反向   |

> **D2→D3 细节**：`dir_main = 0`（主力持平），`dir_close = −1`（价格跌）→ 不等，不同向；也不是严格反向（因为 dir_main = 0）。  
> **D4→D5 细节**：`dir_retail = +1`，`dir_close = +1` → 同向（散户与价格这次同涨）。

### 汇总（修正上表）

重新整理 retail~close 列：

| 窗口    | dir_retail | dir_close | retail~close |
|---------|------------|-----------|--------------|
| D1→D2  | −1         | +1        | ✗ 严格反向   |
| D2→D3  | +1         | −1        | ✗ 严格反向   |
| D3→D4  | +1         | −1        | ✗ 严格反向   |
| D4→D5  | +1         | +1        | ✓ **同向**   |
| D5→D6  | −1         | +1        | ✗ 严格反向   |

| 配对           | 同向窗口数 | 总窗口数 | 同向占比 |
|---------------|-----------|---------|---------|
| main ~ close  | 3         | 5       | **60%** |
| retail ~ close| 1         | 5       | **20%** |

> `dir = 0` 不影响分母（所有有效窗口都计入分母），只影响：该窗口不被算作同向，也不被算作严格反向。

---

## 例三：断点处理（序列中有跳空）

脚本通过 `mark_breakpoints` 检测相邻交易日间距是否 ≤ 7 天。若某两日之间跳空超过 7 天（如节假日长假），则视为**序列断点**，不生成跨断点窗口。

```
Day 1 → Day 2 : 间距 1 天  ✓ 连续
Day 2 → Day 5 : 间距 3 天  ✓ 连续（期间无数据但未超 7 天）
Day 5 → Day 20: 间距 15 天 ✗ 断点！

窗口 Day4~Day6 若跨越 Day5→Day20 这段，整个窗口被丢弃。
```

这确保每个窗口内的首尾差是真实连续行情下的变化，不混入节假日跳空。

---

## 对应代码位置

| 步骤              | 函数                    | 文件位置 |
|-------------------|------------------------|---------|
| 首尾差分 + 方向    | `dir_net` / `scan_windows` | [run_cooc.py:46-83](../scripts/run_cooc.py#L46-L83) |
| 同向/反向统计      | `pair_stats`           | [run_cooc.py:112-141](../scripts/run_cooc.py#L112-L141) |
| 断点检测           | `mark_breakpoints`     | [run_cooc.py:41-43](../scripts/run_cooc.py#L41-L43) |
| Bootstrap 零假设   | `bootstrap_same_rate`  | [run_cooc.py:144-162](../scripts/run_cooc.py#L144-L162) |
