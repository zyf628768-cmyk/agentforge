# AgentForge

**0.2.0a1：本地工程 Alpha，尚未完成生产资格验证。** Python 3.11+，MIT。

本轮增加通用工程产物包、真实 Responses 协议后端、通用 JSON/WASM 执行、
更严格的进程资源限额，以及 Python 的 rootless gVisor 容器执行适配器。
通用生成接口接收实际实现代码，不再局限于文本清洗模板。

本轮没有调用真实模型、检查或读取真实密钥、公开发布或访问生产环境。
离线协议夹具是人工编写的测试数据，不作为模型能力质量证明。

## 安装和离线运行

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux: source .venv/bin/activate
python -m pip install -e '.[dev]'
agentforge doctor
agentforge plan 'Compute sum and count of signed integers' --name integer-stats --kind wasm-json --response examples/v02/integer-stats.planning-response.json --model-receipts planning-receipts.json --output plan.json
agentforge build plan.json --response examples/v02/integer-stats.response.json --model-receipts build-receipts.json --output skills/integer-stats
agentforge test skills/integer-stats --evaluation examples/v02/integer-stats.evaluation.json --report numeric-test.json
agentforge run skills/integer-stats --input skills/integer-stats/examples/input.json
```

整数统计返回 `{"sum":6,"count":3}`。另一个 ROT13 Skill 实际处理大小写、Unicode
和 JSON 转义。Python CSV 列统计工程也可以生成；只有合格的容器环境才能执行。
引擎不会在宿主机运行生成的 Python。原有文本清洗链路仍保留并接受回归测试。

## 通用规划、生成和修复

`plan --kind wasm-json/python-json` 支持任意目标和可编辑的输入输出 Schema。
`--contract FILE` 可提供人工契约；`--response FILE` 使用离线模型协议夹具。
`build --bundle FILE` 接收其他生成器输出的标准工程包。

工程包包含真实源代码、README、测试和示例。可信构建器生成并封存规格、Schema、
SKILL.md、入口哈希和运行时信息，检查路径穿越、大小写冲突、设备路径、文件预算
与敏感信息。模型生成的 WAT 也在受限工作进程中编译。

通用 Skill 必须通过独立验收文件才能标记为 verified；只有生成测试时状态为
unverified，不能激活。独立用例绑定契约哈希，不能放在候选工程中；模型请求不会
包含这些用例。修复模型只接收生成测试的失败证据。升级时重新验证基准通过行为，
并以原子条件更新活动版本指针，阻止并发升级覆盖其他已激活版本。

```sh
agentforge build examples/v02/integer-stats.plan.json --bundle examples/v02/integer-stats.broken.bundle.json --output broken/integer-stats
agentforge evolve broken/integer-stats --response examples/v02/integer-stats.response.json --model-receipts repair-receipts.json --evaluation examples/v02/integer-stats.evaluation.json --output repair --seconds 30 --max-iterations 2 --cost-usd 0
python tools/verify_v02.py --output offline-evidence
```

所有命令都有 `--help`；全局 `--home` 写在子命令之前。退出码 2 包含拒绝、失败、
候选回归和未独立验证状态，具体原因由 JSON 报告说明。

## 模型与隔离边界

Responses HTTP 后端已实现结构化输出、拒答/截断处理、有限响应读取、禁止重定向、
Token/金额预留及审计记录。真实调用要求显式模型、人工核对的价格和正数预算，
以及 `--approve-model-request`、显式凭据变量和新的审计路径。
默认不发现或读取密钥。未知结果保留预算，不盲目重试。实际模型质量、延迟和计费
尚未测试，需你确认后执行。

Windows WASM 工作进程增加 Job Object：默认 256 MiB 进程组提交内存、有限 CPU
时间、两个进程（虚拟环境启动器和解释器）、关闭即终止及墙钟看门狗。
这与 Guest 的 64 KiB 内存、有限燃料、零导入/无 WASI 共同构成约束。
Job/rlimit 是资源控制，不是任意 Python 代码的安全沙盒。

Python 执行要求本地 rootless Docker、cgroup v2、seccomp、gVisor/runsc 与已批准的
本地镜像 digest。禁止拉取、构建、联网、可写宿主挂载和宿主回退，并在启动前读回
容器配置核验。本机没有这个环境，所以 Python 实际执行会拒绝；容器适配器目前
通过的是离线协议和拒绝路径测试，不能据此宣称已完成真实容器安全验证。

详见 [生产缺口清单](docs/production-readiness.md)、[安全模型](docs/security.md)、
[模型后端](docs/model-backend.md) 和 [CLI](docs/cli.md)。
