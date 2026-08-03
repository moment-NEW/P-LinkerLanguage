# P-LinkerLanguage Demo

完整中文文档从 [docs/README.md](docs/README.md) 开始，包括链接基础、五分钟入门、布局 API、业务宏、双工具链接入、生成器原理、排错与扩展路线。

本演示将链接布局表示成普通 C 结构体数组，而不是单行宏。Python 先按目标工具链选择 `#if` 分支，再用正则词法器将受控 C 子集解析成布局 IR，最后生成 GNU ld 或 Arm Compiler scatter 文件。

## 结构模型

`example/layout.pl.c` 是唯一的布局来源，其中有两种对象：

- `pl_memory_t`：内存区名称、起始地址、容量、访问属性。
- `pl_link_region_t`：逻辑区域名称、类型、运行内存、加载内存、地址、大小、对齐和边界符号。

支持的区域类型：

- `PL_LINK_INIT`：收集 `.pl.init.<region>.<priority>` 的函数指针；实际大小由链接器决定。
- `PL_LINK_RAM_CODE`：收集 `.pl.ram_code.<region>`；在运行内存执行，并从加载内存复制。
- `PL_LINK_RESERVED`：保留固定地址范围，不收集输入 section。

关键表达式：

- `PL_AUTO`：地址由链接器按所属内存区顺序分配。
- `PL_LINKER_SIZE`：区域大小由链接器从实际收集的输入 section 结算。
- `PL_KIB(value)` / `PL_MIB(value)`：容量表达式。
- `PL_REF(memory)`：引用内存区名称。
- `PL_SYMBOL(symbol)`：请求导出 C 可用的边界符号。
- `PL_NO_MEMORY` / `PL_NO_SYMBOL`：没有加载内存或加载地址符号。

例如 RAM 代码区：

```c
{
    .name = "fast_code",
    .type = PL_LINK_RAM_CODE,
    .memory = PL_REF(RAM),
    .load_memory = PL_REF(FLASH),
    .address = PL_AUTO,
    .size = PL_LINKER_SIZE,
    .alignment = 4,
    .start_symbol = PL_SYMBOL(pl_fast_code_start),
    .end_symbol = PL_SYMBOL(pl_fast_code_end),
    .load_symbol = PL_SYMBOL(pl_fast_code_load_start),
}
```

业务代码仅依赖抽象宏和稳定符号：

```c
PL_INIT(app_init, 010, board_init);

PL_RAMFUNC(fast_code)
void motor_control_step(void)
{
}
```

`pl_linker.h` 根据编译器提供的预定义宏使用 section 属性，但不包含 GNU ld 或 scatter 语法。`pl_linker_symbols.h` 由生成器输出：GNU 后端声明用户符号；ARMClang 后端将相同的用户符号映射到 `armlink` 的 `Image$$ER...` 和 `Load$$ER...` 自动符号。

## 条件编译与词法边界

布局文件可用下面的方式放置少量工具链条件信息：

```c
#if defined(PL_TOOLCHAIN_GNU)
const char *const pl_demo_active_backend = "gnu";
#elif defined(PL_TOOLCHAIN_ARMCLANG)
const char *const pl_demo_active_backend = "armclang";
#endif
```

Python 在词法分析前只保留当前 `--toolchain` 对应的分支。它支持 `#if defined(...)`、`#ifdef`、`#ifndef`、`#elif`、`#else` 与 `#endif`；不自行实现完整 C 预处理器。

词法器由正则构成并保留行列位置，解析器只解析指定的全局 `pl_memory_t[]` 和 `pl_link_region_t[]` 初始化器。支持指定初始化器、嵌套花括号、字符串、整数、位或、加减、移位和上述受控宏。非布局 C 声明会被跳过，不会推测任意结构体的语义。

## 生成

GNU Arm：

```powershell
python tools/generate_linker.py example/layout.pl.c --toolchain gnu --linker-out build/pl_sections.ld --header-out build/generated/pl_linker_symbols.h
```

Arm Compiler 6：

```powershell
python tools/generate_linker.py example/layout.pl.c --toolchain armclang --linker-out build/pl_sections.sct --header-out build/armclang_generated/pl_linker_symbols.h
```

输出文件：

- `pl_sections.ld`：GNU ld 的 `MEMORY` 与扩展 `SECTIONS`。
- `pl_sections.sct`：Arm Compiler 的 Load Region / Execution Region scatter 文件。
- `pl_linker_symbols.h`：业务代码使用的跨后端边界符号 API。

GNU ld 输出适合作为芯片原始 `.ld` 的扩展。scatter 文件在演示中还会加入一个 `+RO` 兜底执行区，以便完整链接普通代码；真实工程可将该策略与芯片启动、向量表、堆栈布局合并。

## 验证结果

此演示已用本机工具链验证：

- GNU Arm Embedded Toolchain 10.3：`FAST_CODE` 的运行地址为 `0x20000000`，加载地址为 `0x08000008`；固定 `shared_buffer` 占用 `0x2001E000` 到 `0x20020000`。
- Arm Compiler for Embedded 6.22：`armlink` 可链接生成的 scatter 文件，并导出 `Image$$ER_APP_INIT$$Base/Limit`、`Image$$ER_FAST_CODE$$Base/Limit` 和 `Load$$ER_FAST_CODE$$Base`。
