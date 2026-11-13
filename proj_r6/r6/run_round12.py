#!/usr/bin/env python3
"""第 12 轮不再跑敏感性。

p、电池、电量储备、机数、机位、车队和预算都按用户的决定推迟。
直接运行这个文件不会启动任何计算。
"""
from __future__ import annotations


def main() -> int:
    print("敏感性分析已按用户决定推迟，这一轮不再开跑。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
