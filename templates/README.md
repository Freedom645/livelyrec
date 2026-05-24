# templates/

数字認識テンプレート画像などを配置するディレクトリ。配布物に同梱される。

## digits/

`digits/<解像度>/{0..9}.png` に判定数識別用の数字テンプレートを格納する。

```
templates/
└── digits/
    └── 1366x768/        # 配信解像度ごとに別ディレクトリ
        ├── 0.png
        ├── 1.png
        ├── ...
        └── 9.png
```

生成手順:

1. リザルト画面のサンプル画像を `docs/sample/リザルト画面/` に収集
2. `python scripts/build_digit_templates.py --sample-dir docs/sample/リザルト画面 --out-dir templates/digits/1366x768`
3. 出力された `_candidates/` 配下を目視確認し、`0/`〜`9/` サブフォルダに振り分け
4. 各フォルダの画像を平均化して `<digit>.png` を生成（補助スクリプトは詳細設計時に追記）

詳細: `docs/10_詳細設計_画像認識.md` §5.2.4、`docs/poc/03_digit_recognition.md`
