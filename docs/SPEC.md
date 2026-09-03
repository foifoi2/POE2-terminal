# POE2 Reddit Trend / Alpha Detector — MVP仕様

更新日: 2026-09-03

## 1. 目的と非目的

目的は、`r/PathOfExile2` の公開投稿・コメントから、POE2内のビルド、
ファーム効率、供給、需要、価格に影響し得る情報の芽を、普及前に検出することです。
最終ランキング単位は投稿ではなくTopicです。

次は目的外です。

- Redditの人気投稿ランキング
- LLMによる未公開ビルドの発明や、投稿にない性能の断定
- アイテムの売買実行、価格保証、投資助言
- 未承認APIやHTMLスクレイピングによるRedditデータ取得
- POE1情報をPOE2情報として利用すること

## 2. 実装済みMVP

1. Reddit OAuth Data APIから`new`、`rising`、`hot`を取得・重複統合
2. 投稿本文の版、score、upvote ratio、コメント数を時系列保存
3. 候補投稿のコメント取得
4. Velocity、Acceleration、投稿年齢帯別Anomaly、Recencyを計算
5. Lunaによる全投稿の軽量意味解析
6. Terraによる有望候補の詳細解析
7. EmbeddingによるオンラインTopic clustering
8. Topic Momentum、Trend Score、Alpha Score、Confidence、Stageを計算
9. Alpha優先CLIランキングと重複防止console alert
10. `as_of`以前のデータだけを使うreplay/backtest境界
11. モデル・処理別のtoken使用量記録
12. API不要の合成データデモ

価格履歴との自動照合、YouTube/X監視、Dashboard、Stage 3/4判定は未実装です。
したがってコア装備候補の市場表示は常に`unverified`で、価格確認は手動です。

## 3. 処理フロー

```text
Reddit new/rising/hot
  → Post/Version/Snapshot保存
  → 安価な統計特徴
  → 全投稿Luna一次解析
  → 意味候補または統計候補
  → 候補コメント + Terra詳細解析
  → Embedding + Topic割当
  → Topic Momentum
  → Trend / Alpha / Confidence / Stage
  → Alpha優先ランキング + Alert
```

低score投稿を捨てるhard filterは設けません。全投稿を一次解析し、`rising`、
高い初動、ビルド・発見・経済カテゴリなど複数経路から詳細解析候補にします。

## 4. モデル構成

| 用途 | 既定値 | reasoning |
|---|---|---|
| 全投稿の分類・entity抽出 | `gpt-5.6-luna` | low |
| 経済因果・コア装備・反証評価 | `gpt-5.6-terra` | medium |
| Topic Embedding | `text-embedding-3-large` | - |
| APIなしのテスト/デモ | `heuristic-v1` + `hashing-embedding-v1` | - |

Responses APIにはstrict JSON Schemaを渡します。同じtitle/body hashとモデルの解析は
キャッシュし、再分析しません。APIレスのheuristic結果は本番品質とはみなしません。

## 5. スコア

全構成要素は0〜100へ正規化します。重みは`Settings`で変更できます。

```text
Trend =
  0.40 × Upvote Velocity percentile
+ 0.25 × Comment Velocity percentile
+ 0.15 × Engagement Anomaly percentile
+ 0.10 × Recency
+ 0.10 × Topic Momentum
```

Anomalyは`0–1h / 1–3h / 3–6h / 6–12h / 12–24h / 24–48h / 48h+`
の投稿年齢帯で比較します。母数が3件未満なら全体percentileへフォールバックします。
古いsnapshotのvelocityは6時間半減期で減衰させます。Reddit scoreは厳密な投票数では
ないため、負方向の小さな変化は0として扱います。

```text
Alpha =
  0.25 × Economic Impact
+ 0.20 × Actionability
+ 0.15 × Irreversibility
+ 0.15 × Novelty
+ 0.10 × Information Asymmetry
+ 0.10 × Topic Momentum
+ 0.05 × Credibility
```

Information Asymmetryは、LLM評価と現在の到達規模を組み合わせます。単にscoreが低い
だけではAlphaは高くなりません。ConfidenceはAlphaと分離して表示し、通知優先度には
控えめなconfidence補正をかけます。

## 6. ビルドとコア装備

詳細解析では次を分離します。

- `core_items`: ビルド成立に必須または強く推奨される候補
- `role`: enabler、scaler、optional等の役割
- `required_conditions`: Modifier値や組合せ条件
- `substitute_names`: 代替品
- `demand_concentration`: 追随需要が同じ装備へ集中する可能性
- `evidence`: コアと判断した投稿・コメント中の根拠

投稿者が装備しているだけのアイテムをコア扱いしないよう、Structured Outputの指示に
因果要件を含めています。LLM出力は仮説であり、市場確認・ゲーム内検証を代替しません。

## 7. Propagation Stage

- Stage 0: 単独またはごく小規模な発見
- Stage 1: 複数投稿者、複数投稿、またはコメント検証が始まった状態
- Stage 2: Reddit上で強いTrendまたは広い到達が確認された状態

YouTube/X/Build Guideと価格データがないため、Stage 3（Mass Adoption）とStage 4
（Market Priced In）はMVPでは判定しません。拡散段階と市場反映は別軸です。

## 8. Alert

次のいずれかで通知候補になります。

- Alpha Score >= 75
- Alpha Score >= 65 かつ Topic Momentum >= 70
- TrendとEngagement Accelerationが同時に高い
- Stage 0から1へ遷移

同一Topic・Stage・Alpha帯のalert keyをDBで一意にし、毎回同じ通知を出しません。

## 9. DB Schema

| テーブル | 用途 |
|---|---|
| `posts` | Reddit ID、URL、作成・初回/最終観測時刻 |
| `post_versions` | 時点別title/body/hash/flair/source list |
| `post_snapshots` | 時点別score/ratio/comment count |
| `comments` / `comment_versions` | 候補コメントと取得時点の本文・score |
| `llm_analysis` | hash、level、model、source cutoff、JSON結果 |
| `embeddings` | 投稿Embedding cache |
| `topics` / `topic_posts` | centroidと投稿割当 |
| `topic_metrics` | 時点別Trend/Alpha/Stage/内訳 |
| `alerts` | 通知重複防止とpayload |
| `model_usage` | model・処理別token使用量 |

Repository境界を設け、将来PostgreSQL実装へ交換可能にしています。

## 10. セットアップ

Python 3.12以上を使用します。MVP本体は標準ライブラリだけで動きます。依存関係を
インストールせず、リポジトリ同梱launcherから実行できます。

```bash
cp .env.example .env
./poe2-alpha demo --reset
```

任意でconsole scriptとしてインストールする場合は、venv内で
`python -m pip install -e .`を実行します。

`.env`は自動読込しません。秘密情報をファイルへ置きたくない場合はshellまたは秘密管理
機能から環境変数を渡してください。`.env`と`.env.*`はgitignore済みです。

Redditは事前承認済みData API資格情報だけを使用します。

```bash
export REDDIT_CLIENT_ID="..."
export REDDIT_CLIENT_SECRET="..."
export REDDIT_USER_AGENT="script:poe2-alpha-detector:0.1 (by /u/your_name)"
export OPENAI_API_KEY="..."
```

OpenAI公式ドキュメント:

- https://developers.openai.com/api/reference/cli/resources/responses/methods/create
- https://developers.openai.com/api/docs/models
- https://developers.openai.com/api/docs/models/text-embedding-3-large

Reddit公式方針:

- https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy
- https://redditinc.com/policies/data-api-terms

## 11. 実行

```bash
# DB作成
poe2-alpha init-db

# 1回ずつ実行
poe2-alpha collect
poe2-alpha analyze
poe2-alpha rank

# 取得→分析→通知
poe2-alpha run-once

# 10分間隔のローカル常駐（Ctrl-Cで停止）
poe2-alpha watch --interval 600

# APIなしのデモ
poe2-alpha demo --reset

# 機械可読出力
poe2-alpha rank --json

# 使用token集計
poe2-alpha usage
```

未インストールで実行する場合:

```bash
export PYTHONPATH="$PWD/src"
python3 -m poe2_alpha demo --reset
```

## 12. Backtest

```bash
poe2-alpha analyze --as-of 2026-09-02T12:00:00Z
poe2-alpha rank --as-of 2026-09-02T12:00:00Z
```

`posts_as_of`はcutoff以前の最終本文版と最終snapshotだけを返し、コメント・解析・Topic
割当もcutoffで制限します。過去のscore推移は導入前に遡って取得できないため、本格的な
backtestは導入後に蓄積したsnapshotで行います。過去時点を初めて再現するときは、その
時点で`analyze --as-of`してTopicを作成してから`rank --as-of`します。

## 13. テストと受け入れ条件

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

現行テストは次を確認します。

- 編集後本文・未来score・未来解析を過去時点へ混入しない
- `new/rising/hot`重複投稿を1件へ統合する
- Strict Output schemaとアプリmodelの整合
- TrendがMemeより低い新興ビルドをAlpha上位へ残す
- 類似ビルド2投稿をTopic化し、コア装備候補を出す
- Score内訳を表示する
- Alertを重複発行しない

外部APIの実資格情報を使う統合テストは、承認済みReddit資格情報とOpenAI API keyを
設定した環境で別途実施します。ローカルunit testは課金も外部書込みも行いません。

## 14. 既知の制約・次フェーズ

- Redditのみでは「インフルエンサー動画化直前」を直接観測できない
- 市場価格・出品数を自動確認しないため、値上がり前とは断定できない
- オンラインクラスタリングは誤結合・分割があり、再クラスタリングUIは未実装
- 新規subredditや外部ソース追加時はActivity normalizationをsource別に再校正する
- Reddit削除データの完全な追随は、承認された削除通知/保持条件に合わせた追加実装が必要
- Scoreの閾値・重みは合成データではなく、運用後の人手ラベルで校正する必要がある

次の優先順は、(1)承認済みAPIでの統合確認、(2)評価セット作成、(3)価格履歴、
(4)YouTube監視、(5)Dashboardです。
