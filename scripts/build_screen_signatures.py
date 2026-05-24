"""タイトル・クエスト画面の参照シグネチャを生成する（工程8 ② ハイブリッド）。

詳細: docs/design/15_システムテスト計画書.md §8

debug フレームから title / quest を抽出し、参照サムネイル集合を
`templates/screen_signatures.npz` に保存する。あわせて判定しきい値を算出する。

使い方:
    .venv/Scripts/python.exe -m scripts.build_screen_signatures
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from scripts.analyze_screen_signatures import DEBUG, _imread_u, fingerprint, true_label

OUT = Path("templates/screen_signatures.npz")


def main() -> None:
    title: list[np.ndarray] = []
    quest: list[np.ndarray] = []
    other: list[np.ndarray] = []
    for f in sorted(DEBUG.glob("*.png")):
        img = _imread_u(f)
        if img is None:
            continue
        fp = fingerprint(img, None)
        lab = true_label(f.name)
        if lab == "title":
            title.append(fp)
        elif lab == "quest":
            quest.append(fp)
        else:
            other.append(fp)

    print(f"title: {len(title)} 参照 / quest: {len(quest)} 参照 / その他: {len(other)}")

    # しきい値算出: クラス内 NN 最大距離 と 他クラスからの最小距離 の間に取る
    for name, refs in (("title", title), ("quest", quest)):
        if not refs:
            continue
        intra = 0.0
        for i, fp in enumerate(refs):
            nn = min(
                float(np.linalg.norm(fp - g))
                for j, g in enumerate(refs)
                if j != i
            )
            intra = max(intra, nn)
        inter = min(
            min(float(np.linalg.norm(o - r)) for r in refs) for o in other
        )
        print(
            f"  {name}: クラス内NN最大={intra:.0f} / 他クラス最小={inter:.0f} "
            f"-> しきい値候補 {(intra + inter) / 2:.0f}"
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        OUT,
        title=(np.stack(title) if title else np.zeros((0, 1), np.float32)).astype(np.uint8),
        quest=(np.stack(quest) if quest else np.zeros((0, 1), np.float32)).astype(np.uint8),
    )
    print(f"saved -> {OUT}")


if __name__ == "__main__":
    main()
