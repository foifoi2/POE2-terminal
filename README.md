# POE2 Alpha Detector

Reddit の初動から、POE2 のビルド・ファーム・アイテム需要に影響し得る
新興トピックを検出するローカル CLI です。人気順ではなく、時系列の伸び、
話題の新規性、経済的影響、行動可能性、情報の非対称性を別々に評価します。

現在の実装範囲、セットアップ、コマンド、制約は
[docs/SPEC.md](docs/SPEC.md) を参照してください。

```bash
./poe2-alpha demo --reset
./poe2-alpha rank
python3 -m unittest discover -s tests -v
```

パッケージをインストールせず実行する場合は、上のコマンドの前に
`export PYTHONPATH="$PWD/src"` を設定してください。
