"""Package committed source, genuine evidence, offline wheels and Git bundle."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

from agentforge.core import read_json, write_json


def package(root: Path) -> None:
    output = root / "outputs"
    evidence = output / "evidence/final"
    records = []

    def git(*args):
        command = ["git", "-c", "core.longpaths=true", *args]
        result = subprocess.run(command, cwd=root, capture_output=True, check=True)
        records.append(
            {
                "command": command,
                "exit_code": result.returncode,
                "stdout": result.stdout.decode("utf-8", errors="replace"),
                "stderr": result.stderr.decode("utf-8", errors="replace"),
            }
        )
        return result.stdout

    acceptance = read_json(evidence / "acceptance/commands.json")
    assert all(c["exit_code"] == 0 for c in acceptance)
    demos = read_json(evidence / "demos/summary.json")
    assert demos["status"] == "passed" and demos["demos"] == 3
    fresh = read_json(evidence / "fresh-install.json")
    assert all(c["exit_code"] == c["expected_exit_code"] for c in fresh)
    assert not git("status", "--porcelain").strip(), "Commit all source before packaging"
    commit = git("rev-parse", "HEAD").decode().strip()
    assert git("describe", "--tags", "--exact-match").decode().strip() == "v0.1.0"
    bundle = output / "agentforge-v0.1.0.bundle"
    git("bundle", "create", str(bundle), "--all")
    git("bundle", "verify", str(bundle))
    source = output / "agentforge"
    if source.exists():
        raise RuntimeError("Source deliverable already exists; preserve it")
    tracked = git("ls-files", "-z").decode().split("\0")
    for relative in filter(None, tracked):
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, destination)
    write_json(
        output / "git-status.json",
        {
            "root": str(root),
            "branch": git("branch", "--show-current").decode().strip(),
            "commit": commit,
            "tag": "v0.1.0",
            "status": git("status", "--porcelain").decode(),
            "remotes": git("remote", "-v").decode(),
            "bundle_verified": True,
        },
    )
    write_json(output / "git-commands.json", records)
    tests = acceptance[0]["stdout"].strip().splitlines()[-1]
    report = f"""AgentForge v0.1.0 本地交付记录

源码开发目录：{root}
可复制源码目录：outputs/agentforge
CLI：work/fresh-final/Scripts/agentforge.exe（本机已安装）
安装包：dist/agentforge-0.1.0-py3-none-any.whl
离线依赖：wheelhouse/（本机 Windows x64 / CPython 3.12，其他平台可联网安装免费依赖）
离线安装：python -m pip install --no-index --find-links wheelhouse dist/agentforge-0.1.0-py3-none-any.whl

最终验收：{tests}
静态检查：ruff 全部通过；项目和生成 Skill 的 SKILL.md 通过规范验证。
全新安装：新的虚拟环境中使用 wheel 和本地依赖，无索引安装、pip check、CLI doctor 均通过。
演示一：WASM 文本清洗返回 Hello 世界。
演示二：TAB Bug 原始用例 8/12 通过，修复后原始用例 12/12；基准通过用例额外重跑。
演示三：引入大小写回归，候选被拒绝；活动版本 0.2.1 哈希保留，随后演示回滚到 0.1.0。
版本比较：evidence/final/demos/comparison.json。
完整命令、退出码、输出和错误：evidence/final/ 下的 JSON、JUnit XML。
历史失败：evidence/v0.1.0、evidence/release 保留首次长路径问题及过长目录测试的失败证据。

安全：真实测试了禁止所有 Guest 导入、无限循环燃料耗尽、启动函数无限循环、
越界访问、64 KiB 内存限制、零表、输出范围检查和墙钟超时。
另在全新环境中实际卸载 Wasmtime，确认 doctor/test 返回 2 且不执行不可信代码，再离线恢复依赖。
Guest 无 WASI、文件系统、网络或环境变量接口；生成 Python 未在宿主机执行。
工作进程/虚拟环境本身不是沙盒。可信计算基础包含 Wasmtime 原生 JIT；64 KiB 限额
只针对 Guest 内存，不等同于 Python/JIT 进程 RSS 的操作系统级配额。

已实现：可编辑规格、离线完整工程构建、真实隔离测试、受控已知 Bug 修复、
独立评估和基准回归测试、候选比较、预算限制、SQLite 注册、Git 快照与回滚、全部 CLI。
限制：离线构建器仅支持 ASCII 空白文本清洗；修复器仅支持已知 TAB 缺陷；
尚无任意目标生成、真实模型后端或任意 Python Skill 沙盒。optimize 仅重建并比较规范实现。
公开固定独立测试集用于防止候选测试误删，不承诺抵抗有意作弊。
本机验证 Windows x64 / Python 3.12；Python 3.11–3.13/Linux 的 CI 矩阵已配置但未远程运行。

Git：main，标签 v0.1.0，提交 {commit}；工作区干净，无 remote，未公开推送。
Git bundle 已通过 git bundle verify；可用 git clone agentforge-v0.1.0.bundle agentforge 恢复。
无付费 API、生产访问、发布或权限扩大。
"""
    (output / "DELIVERY.zh-CN.txt").write_text(report, encoding="utf-8")
    selected = []
    for folder in (source, output / "dist", output / "wheelhouse", output / "evidence"):
        selected.extend(
            p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts
        )
    selected.extend(
        [
            bundle,
            output / "git-status.json",
            output / "git-commands.json",
            output / "DELIVERY.zh-CN.txt",
        ]
    )
    hashes = {
        p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in selected
    }
    write_json(output / "MANIFEST.sha256.json", hashes)
    selected.append(output / "MANIFEST.sha256.json")
    archive = output / "agentforge-v0.1.0.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(selected):
            zf.write(path, path.relative_to(output).as_posix())
    with zipfile.ZipFile(archive) as zf:
        assert zf.testzip() is None
        for name, digest in hashes.items():
            assert hashlib.sha256(zf.read(name)).hexdigest() == digest
    (output / "agentforge-v0.1.0.zip.sha256").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "archive": str(archive),
                "bytes": archive.stat().st_size,
                "files_verified": len(hashes),
                "commit": commit,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    package(Path(__file__).resolve().parents[1])
