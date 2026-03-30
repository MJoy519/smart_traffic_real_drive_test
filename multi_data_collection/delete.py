"""
delete.py  —  删除指定受试者数据脚本
=================================================
用法：
  在下方 PARTICIPANT_ID 处填写要删除的受试者编号，
  运行后将删除 data/ 目录下以下4个子目录中对应的受试者文件夹：
    data/azure/{PARTICIPANT_ID}/
    data/facial_video/{PARTICIPANT_ID}/
    data/traffic_video/{PARTICIPANT_ID}/
    data/gps/{PARTICIPANT_ID}/
"""

import shutil
from pathlib import Path

# ═══════════════════════════════════════════════
#  ▼▼▼  在此处设置要删除的受试者编号  ▼▼▼
PARTICIPANT_ID = "P1"
#  ▲▲▲  在此处设置要删除的受试者编号  ▲▲▲
# ═══════════════════════════════════════════════

DATA_ROOT = Path(__file__).parent / "data"

SUB_DIRS = [
    "azure",
    "facial_video",
    "traffic_video",
    "gps",
]


def delete_participant(participant_id: str) -> None:
    print(f"\n即将删除受试者 [{participant_id}] 的所有数据")
    print("─" * 45)

    targets = [DATA_ROOT / sub / participant_id for sub in SUB_DIRS]
    existing = [p for p in targets if p.exists()]

    if not existing:
        print("未找到任何相关数据文件夹，无需删除。")
        return

    print("以下文件夹将被永久删除：")
    for p in existing:
        print(f"  {p}")

    print()
    confirm = input("确认删除？输入 yes 继续，其他任意键取消：").strip().lower()
    if confirm != "yes":
        print("已取消，未删除任何数据。")
        return

    print()
    for p in existing:
        shutil.rmtree(p)
        print(f"  [已删除] {p}")

    not_found = [p for p in targets if p not in existing]
    for p in not_found:
        print(f"  [不存在，跳过] {p}")

    print(f"\n受试者 [{participant_id}] 数据删除完毕。")


if __name__ == "__main__":
    delete_participant(PARTICIPANT_ID)
