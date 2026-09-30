# crystal-harness

[English](README.md) | 日本語

長時間かかるアプリケーション開発のためのマルチエージェント・ハーネスを、Claude Code
プラグインとしてまとめたものです。主な特徴は次の5つです。

- 作るエージェントと採点するエージェントを分ける
- 「これで良いか?」という曖昧な問いを、閾値付きのルーブリックに置き換える
- コンテキストを圧縮(compaction)せず、ファイル経由でリセットする
- 各スプリントを当て推量ではなく合意事項にする
- プロダクト全体を独立した立場で評価するまで、run を終わらせない

Anthropic の
[Harness Design for Long-Running Application Development](https://www.anthropic.com/engineering/harness-design-long-running-apps)
をモデルにしています。

## 対処する失敗パターン

| 失敗 | どう見えるか | ハーネスの対策 |
| --- | --- | --- |
| **一貫性の喪失 / コンテキスト不安** | コンテキストウィンドウが埋まるにつれ、エージェントがスコープを削って早々に切り上げる。 | 圧縮ではなくコンテキストの**リセット**。フェーズの境目ごとに `handoff.md` を書き、*新しい*エージェントがそれを引き継ぐ。会話履歴には何も依存しない。 |
| **自己評価の甘さ** | 自分の成果物を採点させると、凡庸な出来でも自信満々に褒める。 | 生成と評価は、プロンプトもツールも違い、コンテキストも共有しない別々のエージェントが担う。hook によって、この境界は努力目標ではなく構造上の制約になっている。 |
| **QA の判断が甘い** | 本物の問題を見つけても「大したことはない」と自分を納得させて承認してしまう。テストが表面的で、境界ケースを見落とす。 | 行動レベルのアンカー付きの6つの観点と閾値、20個の較正例(calibration examples)、明示的な迎合防止ルール。実際に試していない基準は `not_verified` であり、`pass` には絶対にならない。 |
| **表示だけの見かけ倒し** | どの画面も描画はされるが、実際には何も操作できない。 | **Product depth** を独立した採点観点にし、閾値を 4 にしている。メニューは開くが選んでも何も起きないコントロールは 2 点。 |
| **スコープ不足** | 1行のプロンプトから、機能が3つだけの薄いアプリができる。 | コードを書く前に planner がスコープを網羅した仕様を書く。スコープには野心的に、実装については意図的に何も書かない。 |
| **スプリントは通るのにプロダクトとしては失敗** | 10スプリントすべて pass したのに、アプリとしてまとまっていない。 | 誰とも交渉していない基準で `spec.md` 全体を採点する **final assessment**。これに pass するまで run は終わらない。 |
| **作り手と同じ先入観を持つ採点者** | 生成と評価は別エージェントでも、同じモデルファミリーが書いた diff を同じファミリーが読んでいる。 | Claude 以外のモデル(`codex` プラグイン)による各 diff の独立レビューを任意で追加できる。レビュー結果は、evaluator がコードで裏を取るべき判断材料として記録するだけで、合否のゲートには使わない。 |
| **QA が重すぎて回せない** | ラウンドのコストの大半をブラウザ検証が占めるので、なし崩しにスキップされ、スキップしたことも記録されない。 | ブラウザ検証は config のフラグで切り替え、**3つのモードとして記録**する。スキップしたラウンドは verdict にそう書かれる。検証を求められたのに実行できなかったラウンドは絶対に pass しない。 |

## インストール

```bash
git clone <this repo>
claude
```

続いて Claude Code の中で次を実行します。

```
/plugin marketplace add YukiTominaga/claude-harness
/plugin install crystal-harness@crystal-harness
```

未コミットのチェックアウトでローカル開発する場合は、代わりにローカルパスからマーケットプレイスを
追加します。

```
/plugin marketplace add /absolute/path/to/claude-harness
/plugin install crystal-harness@crystal-harness
```

追加したら Claude Code を再起動してください。インストールせずに使い捨てで試すなら、次のように起動します。

```bash
claude --plugin-dir /absolute/path/to/claude-harness/crystal-harness
```

インストールできたか確認します。インベントリに agent 3つ、MCP サーバー 1つ、hook 1つ、skill 9つ
が表示されれば正常です(6つのコマンドが、3つのリファレンス skill と合わせて skill として数えられます)。

```bash
claude plugin details crystal-harness
```

`python3`(権限を強制する hook と補助スクリプト用)と `node`/`npx`(Playwright MCP 用。
初回利用時に取得され、ブラウザ検証をオンにしたときだけ必要)が必要です。

任意: [`openai/codex-plugin-cc`](https://github.com/openai/codex-plugin-cc) を入れると、
各ラウンドの diff に Claude 以外のモデルによる独立レビューも付きます。

```
/plugin marketplace add openai/codex-plugin-cc
/plugin install codex@openai-codex
/codex:setup
```

ハーネスは codex プラグインの `codex-companion.mjs` を探し、準備ができているかを問い合わせて
検出します。インストール済みでも未認証ならレビューできないので「なし」とみなします。codex がなくても
何も壊れません。後述の「独立レビュー」を参照してください。

### アップデート

```bash
claude plugin marketplace update crystal-harness
claude plugin update crystal-harness@crystal-harness
claude plugin list --json | grep -A1 crystal-harness   # "enabled": true を確認
```

`plugin update` が新しいバージョンをインストールしたものの **disabled** のまま残した事例が、
一度だけ確認されています(Claude Code 2.1.226)。症状は、次のセッションで `/crystal-harness:*`
コマンドがすべて `Unknown command` になることです。`enabled` が false なら
`claude plugin enable crystal-harness` を実行してから再起動してください。

## クイックスタート

```
/crystal-harness:init
/crystal-harness:plan a pomodoro timer with session history
/crystal-harness:build
```

`/crystal-harness:init` は検出した config を表示して待ちます。`/crystal-harness:plan` は spec を
表示して待ちます。そのあと `/crystal-harness:build` がループ(スプリント、続いて final assessment)
を回し、あなたの判断が必要になったときだけ止まります。

いつでも使えるコマンド:

```
/crystal-harness:status                # run の現在地と、ここまでのコスト
/crystal-harness:qa [n|final]          # 現在の作業ツリーを単独で採点
/crystal-harness:resume                # クラッシュ、/clear、新しいセッションの後に再開
```

> プラグインのコマンドには名前空間が付きます。実際に打つのは `/init` ではなく
> `/crystal-harness:init` です。

## `.harness/` の成果物の約束事

エージェント間の受け渡しはすべてファイルで行います。どのエージェントも、他のエージェントの会話を
見たことを前提にしてはいけません。

```
.harness/
├── config.json          # ハーネスの設定
├── spec.md              # planner の出力: プロダクト仕様
├── state.json           # run の状態 + コスト台帳(ledger)
├── handoff.md           # コンテキストリセット用の引き継ぎファイル(毎回書き直す)
├── journal.md           # 追記のみの、人間向けログ
├── artifacts/           # Playwright の作業出力。browser モードのみ(gitignore 対象)
├── sprints/01/
│   ├── contract.md      # generator が提案し、evaluator が受諾する
│   ├── report.md        # generator の完了報告 + セルフチェック
│   ├── codex-review.md  # diff の独立レビュー(codex が入っている場合)
│   ├── qa.md            # evaluator の判定(人間向け)
│   ├── verdict.json     # evaluator の判定(機械向け)
│   └── screenshots/
└── final/01/            # run の最後の評価。ラウンドごとに1ディレクトリ
    ├── qa.md
    ├── verdict.json
    ├── report.md
    ├── codex-review.md
    └── screenshots/
```

完全な定義、2つの JSON Schema、`handoff.md` のテンプレートは
`crystal-harness:harness-protocol` skill にあります。

`handoff.md` は構造の要になるファイルです。事前のコンテキストをまったく持たない新しいエージェントが、
これだけで作業を続けられなければいけません。書く内容は次のとおりです。

- 現在のゴール
- 完了し、*かつ検証済み*のこと
- 作業が止まった正確な位置
- 壊れていると分かっているもの
- 蒸し返さない決定事項
- **試して却下したアプローチ**
- 重要なファイル
- 次にやることを**1つ**

`handoff.md` のフェーズが `state.json` と食い違っていれば致命的なエラーとして扱い、人間が解消するまで
`/crystal-harness:resume` は続行を拒否します。

### コスト台帳

`state.json` には追記専用の `ledger` があります。サブエージェントを呼ぶたびに1エントリ追加され、
エージェント、フェーズ、所要時間、Agent ツールが報告したトークン数が記録されます。

これがあるのは、この設計で繰り返し必要になる最も重要な判断が「*この部品はまだコストに見合っているか*」
であり、それは文章からは答えられないからです。`/crystal-harness:status` は台帳をエージェント別の表に
集計し、run 全体に占める evaluator の割合を示します。`harness.costPerMTokUsd` を設定すれば、
推定ドル額に換算されます。

台帳がなければ、後述の「何を外すか」の節はただの意見です。台帳があれば、「evaluator は直近
4スプリントで何も見つけておらず、run のコストの 38% を占めた」は事実になります。

### 担当範囲の強制

`hooks/hooks.json` は `PreToolUse` hook を1つ登録します。この hook がブロックするものは、
どれも気づかれないまま設計を壊すものです。

- `harness-generator` が `sprints/NN/` や `final/NN/` の下に `qa.md`、`verdict.json`、
  `screenshots/` を書くこと。generator が verdict を書けるなら、すべての pass が自作自演になる。
- `harness-evaluator` が `.harness/` の外に何かを書くこと。evaluator が採点対象を直せるなら、
  自分が判定するものの作者になってしまう。
- **どちらか一方でも** `codex-review.md` を書くこと。両方が禁止されている唯一のファイル。
  generator が書けるなら自分でセカンドオピニオンをでっち上げられるし、evaluator が書けるなら
  自分がこれから引用する証拠を編集できてしまう。

それ以外はすべて素通しします。ログ用やフォーマット用の hook はありません。どちらも特定の失敗を
防がないからです。何も防がない足場こそ、この設計全体が避けようとしているオーバーヘッドです。

境界での振る舞いとその理由:

- **fail closed(失敗時は拒否)にしている。** イベントを解析できない場合や `python3` がない場合、
  guard は exit 2 で終了し、説明付きで呼び出しをブロックする。検査できなかったものを通してしまう
  guard は、guard がないより悪い。
- **パスは `realpath` で解決し、大文字小文字を区別せずに比較する。** そのため
  `.harness/../src/App.tsx` も、`.harness/` 内に仕込んだシンボリックリンクも、大文字小文字を区別しない
  ファイルシステム上の `.HARNESS/sprints/01/VERDICT.JSON` もすり抜けられない。
- **Bash のカバー範囲は意図的に非対称。** generator は、シェルコマンドの中で verdict 系の成果物の名前を
  出すこと自体を禁止されている。一方、evaluator の Bash は監視*しない*。evaluator はプロジェクトの
  install、build、test、dev、`curl`、`sqlite3` を実行するので、リダイレクトを嗅ぎ回る仕組みを置くと、
  捕まえる違反より壊す run のほうが多くなる。この残った穴があるため、エージェントのプロンプトでも
  同じルールを明記している。

ポリシーは `scripts/guard_harness_artifacts.py` にあり、`hooks/hooks.json` から `python3` で直接
呼ばれます(python3 がある前提です)。

## 設定リファレンス

`.harness/config.json` は、あなたの確認を経て `/crystal-harness:init` が書き出します。

```jsonc
{
  "commands": {
    "install": "npm install",
    "dev": "npm run dev",
    "build": "npm run build",
    "test": "npm test",
    "backendDev": "uvicorn app.main:app --reload"   // バックエンドがなければ null
  },
  "urls": {
    "app": "http://localhost:5173",
    "api": "http://localhost:8000"                  // バックエンドがなければ null
  },
  "database": {                       // バックエンドがなければ null
    "kind": "sqlite",
    "file": "./app.db",               // evaluator がこれを直接読む
    "url": null
  },
  "harness": {
    "useEvaluator": true,
    "useSprints": false,              // true → 項目ごとに contract を作る(v1 モード)
    "contextReset": true,             // false → フェーズをまたいで同じエージェントを使い続ける
    "browserVerification": false,     // true → Playwright で UI を操作する
    "codexReview": "auto",            // "auto" | true | false
    "maxSprints": 12,
    "maxRevisionsPerSprint": 5,
    "maxAcceptanceCriteria": 20,      // スプリント contract あたりの上限。validate_contract.py が強制
    "maxFinalQaRounds": 5,
    "costPerMTokUsd": null            // 設定すると /crystal-harness:status に推定ドル額が出る
  }
}
```

既存のリポジトリでは、`/crystal-harness:init` が `package.json` の scripts、lockfile、
フレームワークの設定、`pyproject.toml`、ORM の設定から `commands`・`urls`・`database` を検出し、
それぞれの値をどこから取ったかを添えて表示します。デフォルト値が使われるのは、何もない新規ディレクトリ
のときだけです。**dev コマンドを勝手に作ることは絶対にありません。** 検出結果が曖昧なら、推測せずに
質問します。

`useSprints` のデフォルトが `false` なのは、この config に関係なく generator と evaluator が
`claude-opus-5-5` に固定されているからです(後述)。スプリント単位の分割は、長いセッションで一貫性を
失うモデルのための安全網でした。Opus 5.5 には不要です。

仕様が大きい、または密結合していて、評価付きの小さな単位で確認していくほうが「長い1回のビルド +
収束するまでの final QA の連続」より有利な場合は `true` にしてください。これを自動で判断する信号は
ないので、スコープが大きそうなら人間に聞きます。

`maxFinalQaRounds` のデフォルトが 3 ではなく 5 なのも同じ理由です。スプリントをオフにすると、
欠陥の検出が「スプリントごとの多数の小さなチェック」から「run の最後の少数の大きなチェック」に移るので、
収束するまでのラウンド数に余裕が必要になります。

`browserVerification` のデフォルトは `false` で、これが QA ラウンドを安くする変更です。Playwright で
アプリを操作するのは evaluator の作業の中で群を抜いて高コストです。しかも、そこで見つかるものの大半は
*見た目*の問題です。ビルドを「間違ったもの」にする欠陥は、API・データストア・プロジェクト自身の
テストスイートですでに見つかります。

オフにすると evaluator は `headless` モードで動き、それでも pass を返せます。その pass が何を
カバーし、何をカバーしないかは後述の「検証モード」を参照してください。価値がインターフェースにある
run と、出荷するつもりのものの final assessment では、オンにしてください。

`codexReview` のデフォルトは `"auto"` です。「独立レビュー」を参照してください。

`database` は見た目以上に重要です。evaluator はすべての書き込みをデータストアを直接読んで確認するので、
これがない run では、書き込みを伴う基準すべてが `persistenceVerified: false` になります。さらに
headless モードでは、バックエンドも実行可能なテストスイートもないプロジェクトは一度も pass できません。
何も実行されていないことになるからです。

`harness.*` のフラグはどれも個別にオフにできます。これは意図した設計です。「何を外すか」を参照して
ください。

### 各エージェントが使うモデル

`config.json` ではなく、エージェントのフロントマターで設定しています。新しいモデルが出たら、
最初に見直すべき箇所です。

| エージェント | モデル | Effort | 理由 |
| --- | --- | --- | --- |
| `harness-planner` | `claude-opus-5-5` | `high` | アイデアを仕様へと構造的に展開する |
| `harness-generator` | `claude-opus-5-5` | `xhigh` | 長時間の一貫性と難しい実装 |
| `harness-evaluator` | `claude-opus-5-5` | `high` | 基準との照合だけでなく、デザインと深さを判断する |

**コストを動かすレバーはモデルの格ではなく effort です。** 3つのエージェントはすべて Opus 5.5 で動きます。
generator を `xhigh` から `medium` に下げるほうが、どれかのエージェントを Sonnet 5 のような安いモデルに
替えるより、はるかにコストが変わります。安いモデルに手を伸ばす前に、自分の出力を見ながら effort を
振ってみてください。

## ループの仕組み

`useSprints: true`(デフォルトに対する、小さな単位で進める選択肢)のとき、スプリントごとに次を行います。

1. **Contract。** 新しい generator が、仕様の feature ordering から次のスプリントを切り出して
   `contract.md` を書く。内容は、スコープ、スコープ外、**固定するインターフェース**(evaluator が
   テストするのに必要なルート・テーブル・testid)、項目ごとに1つ以上の受け入れ基準。
   - 1スプリントの目安は 10〜15 基準で、上限は `maxAcceptanceCriteria`(デフォルト 20、
     `validate_contract.py` が強制)。
   - 各基準には、開始状態、操作、観測できる結果(ブラウザ上、API に対して、またはデータストア内)を書く。
   - 上限を超えたスコープは次のスプリントに回す。
2. **レビュー。** 新しい evaluator が5点を確認する。
   - すべての基準がテスト可能か
   - そのスプリントが仕様を前に進めるか
   - 基準が「あること」ではなく*深さ*をカバーしているか
   - generator に任せるべきものまで固定していないか
   - 基準を統合できるか

   言い回しの修正は evaluator が自分で書く amendment(`accepted-with-amendments`)で済ませる。
   contract を差し戻すのは4種類の指摘だけで、修正はその指摘が名指しした箇所だけを直す。最大2ラウンド
   で、それでも合意できなければエスカレーションする。
3. **実装。** 新しい generator が実装する。チェックポイントごとに commit し、プロジェクト自身の
   build / typecheck / test を実行して自分の失敗を直し、`report.md` に「完了したこと」「部分的なこと」
   「手を付けなかったこと」を書く。
4. **独立レビュー。** `codex` プラグインが使えれば、evaluator を起動する前に、Claude 以外のモデルが
   スプリントの diff をレビューし、結果を `codex-review.md` に書く。codex がない、または未認証なら、
   1行知らせてラウンドを続ける。
5. **コンテキストリセット。** `state.json` と `handoff.md` を書いてから、evaluator を
   コンテキストを共有しない新しいエージェントとして起動する。evaluator に渡すのはファイルパスだけで、
   generator が「動く」と主張している内容は伝えない。
6. **評価。** evaluator は `browserVerification` を見て検証モードを選ぶ。
   - `browser` モードでは、Playwright でアプリを操作する。クリック、入力、ドラッグ、リサイズ、
     タブ移動、空状態やエラー状態の誘発、コンソールとネットワークの確認まで行う。
   - どのモードでも、**UI の外ですべての書き込みを確認する**(`curl` とデータストアの直接読み取り)。
     プロジェクトのテストスイートを実行し、API の失敗パスを叩き、`codex-review.md` も含めてコードを
     読んで各失敗の原因を特定する。
   - `qa.md`、`verdict.json`、スクリーンショットを書く。
7. **分岐。** pass なら commit して次のスプリントへ。fail なら、新しい generator が
   **blocking issue だけ**を対象に修正する。
8. **無限ループせずに止まる。** 次のどれかに当てはまったら、run を止めてあなたに判断を仰ぐ。
   - 修正回数を使い切った
   - 同じ blocking issue が3回再発した
   - evaluator が2回 degraded で動いた
   - `maxSprints` に達した
9. **Final assessment。** feature ordering を消化したら、新しい evaluator が、自分で導出した
   `SPEC-n` 基準を使って `spec.md` に対してプロダクト全体を採点する。fail なら blocking issue に対する
   ビルドラウンドを回して再評価する。**これに pass するまで run は完了しない。**

**`useSprints: false`(デフォルト)のとき**は、ステップ 1〜2 と 7〜8 がなくなります。新しい generator
1体が `spec.md` を受け取り、長く一貫した1つのセッションでプロダクト全体を作ります。そのあと
final assessment のループ(ステップ 9)で、QA と修正のラウンドを完了するか `maxFinalQaRounds` に
達するまで回します。

これは机上の話ではありません。10項目の仕様に対する実際の run では、generator の72分の1セッションで
プロダクト全体を作り、final QA 3ラウンドでクリーンな pass に達しました。

- ラウンド1: 実際の状態不整合(state desync)のバグを見つけた
- ラウンド2: その修正が引き起こした小さなリグレッション2件を捕まえた
- ラウンド3: 3件すべての修正を確認し、blocking issue ゼロ、39/39 基準が pass

`useSprints: true` ならスプリントごとに見つかっていたはずの欠陥が、代わりに run 最後の収束の過程で
見つかります。`maxFinalQaRounds` のデフォルトを、スプリントモードの final assessment に必要な数より
大きい 5 にしているのはこのためです。

### ルーブリック

6つの観点を、それぞれ行動レベルのアンカー付きで 0〜5 点で採点します。

| 観点 | 閾値 | | Headless |
| --- | --- | --- | --- |
| **Product depth** | ≥ 4 | 機能が本物か、見かけ倒しか | 採点する |
| **Functionality** | ≥ 4 | 境界ケースやエラーパスも含めて端から端まで動くか | 採点する |
| **Code quality** | ≥ 3 | 責務の境界、重複、エラー処理、意味のあるテスト | 採点する |
| **Design quality** | ≥ 4 | 全体としてまとまり、独自の雰囲気と個性があるか | 免除 |
| **Originality** | ≥ 4 | ライブラリのデフォルトではなく、意図した判断があるか | 免除 |
| **Craft** | ≥ 3 | タイポグラフィ、余白、状態表示、コントラスト、レスポンシブ | 免除 |

**適用される閾値のうち1つでも下回ればスプリントや run は fail になり、閾値そのものが重み付けに
なっています。** depth・design・originality は 4、craft と code quality は 3 です。別途計算して保存する
重み付きスコアはありません。

headless モードで免除される3つは、描画されたインターフェースについての判断です。ブラウザがなければ
`null` と採点され、`null` は適用される閾値を決して満たしません。

実際に試していない基準は `not_verified` で、`pass` には絶対になりません。`not_verified` は pass の
根拠としても数えません。blocking issue にはすべて、再現手順、観測結果、期待結果、スクリーンショット、
**そして原因**を付けます。原因は失敗を観測した*後で*コードから特定し、観測する前に推測してはいけません。

較正例は `skills/qa-rubric/references/calibration-examples.md` にあります。観点ごとに3つ以上、
合計20個です。たとえば次のような例を含みます。

- 磨き上げられているのに低得点になる成果物
- 地味なのに高得点になる成果物
- テストはすべて通るのに depth が 2 のビルド
- 規律正しく見えることそのものが欠陥になっているコードベース

### 検証モード

どの verdict にも、それが作られたモードが記録されます。そして、モードによって `pass` が何を意味して
よいかが決まります。

| モード | いつ | 何を採点するか | pass できるか |
| --- | --- | --- | --- |
| `browser` | `browserVerification: true` で Playwright が応答した | 6観点すべて | できる |
| `headless` | `browserVerification: false` | product depth、functionality、code quality | できる |
| `degraded` | `browserVerification: true` なのに Playwright が応答**しなかった** | 届いた範囲だけ | **できない** |

下の2つの区別が、この機能の設計のすべてです。**headless は「誰も頼んでいない検証」、degraded は
「頼まれたのに実行できなかった検証」です。** run が、設定されたカバー範囲を黙って失うことはありません。
degraded が2ラウンド続くとループは止まります。headless のラウンドは何も壊れていないので、この数には
入りません。

`headless` モードの evaluator は Playwright に触れません。やることは次のとおりです。

- install、build、アプリの起動
- プロジェクトのテストスイートの実行
- そのラウンドが触れたすべてのエンドポイントを、失敗パスも含めて叩く
- 各書き込みを、データストア上とバックエンド再起動後の両方で確認する
- コードを読んで code quality を採点する

design・originality・craft は `null` と採点します。0 点ではなく、スタイルシートから推測した点数でも
ありません。これらの閾値は免除されます。本当にブラウザが必要な基準は `browserOnly: true` 付きの
`not_verified` になり、`/crystal-harness:status` がその件数を報告します。ブラウザをオンにして再実行
すべきかは、この件数で判断します。

ルーブリックの半分を免除して安全なのは、残り半分をきちんと稼いだときだけです。そのため headless の
pass には追加の条件があります。

- 実際に何かが実行されたこと(`apiVerified` または `testsVerified`)
- 少なくとも1つの基準が pass していること
- `not_verified` の基準が**すべて**ブラウザ専用のものであること。それ以外の抜けがあれば、browser
  モードと同じく pass をブロックする

`scripts/validate_verdict.py` が、6つの閾値そのものと合わせてこれをすべて強制します。オーケストレーター
は、却下された verdict を好意的に解釈しないよう指示されています。

headless で捕まえられないものをはっきり書いておきます。**何にも配線されていないコントロール**です。
処理は存在し、エンドポイントは動き、行も変わるのに、それを呼ぶはずのボタンが呼んでいない、という
ケースです。これがトレードオフであり、出荷するつもりのものの final assessment を
`browserVerification: true` で回すべき理由です。

このフラグで節約*できない*ものが1つあります。プラグインは `.mcp.json` で Playwright MCP を登録し続ける
ので、サーバーはセッションと一緒に起動します。プラグインの MCP ブロックには条件分岐がないためです。
節約になるのはラウンド側です。時間を食っているのはサーバーの起動ではなく、evaluator のブラウザとの
往復だからです。

### 独立レビュー

[`codex`](https://github.com/openai/codex-plugin-cc) プラグインがインストール済みで認証も済んでいれば、
オーケストレーターは各ラウンドで generator が終わってから evaluator を起動するまでの間に、そのラウンドの
diff のレビューを実行し、`codex-review.md` をラウンドのディレクトリに書き出します。

これがあるのは、evaluator が generator からいくら切り離されていても、Claude が書いた diff を Claude が
読んでいることに変わりはないからです。別ベンダーのモデルによるセカンドオピニオンは、CLI の呼び出し
1回分のコストで済み、その先入観を一切共有しません。

意図的に、合否の**ゲートにはしていません**。

- evaluator はこのファイルを Code quality の判断材料の1つとして読む。
- 指摘はすべて「コードで確認すべき主張」として扱い、確認できたものと却下したものを `qa.md` に記録する。
- 確認できなかった指摘が blocking issue になることはない。
- このファイルの内容で「機能が動く」ことを立証することはできない。読むことが増えるだけで、読むことは
  検証ではない。

verdict の決まり方は、codex があってもなくても同じです。

検出は実際に動くかどうかで行います。ハーネスはプラグインの `codex-companion.mjs` を探し、準備が
できているかを問い合わせます。インストール済みでもログインしていなければ「なし」とみなします。
`"auto"` なら、codex がないときは1行知らせてラウンドを続けます。それを知りたいなら
`codexReview: true` に、実行したくないなら `false` にしてください。所要時間は他の部品と同様に台帳に
記録されるので、好みではなく証拠に基づいて評価し、外すかどうかを決められます。

## 再開

run は `/clear`、クラッシュ、別のマシンへの移動を乗り越えられるように設計しています。

```
/crystal-harness:resume
```

`state.json` → `handoff.md` → `config.json` → `spec.md` → 現在のラウンドの成果物、の順に読みます。
次のような不整合があれば続行を拒否します。

- handoff がない
- handoff のフェーズが state と食い違っている
- `lastGoodCommit` が `HEAD` の祖先ではない
- `phase: "blocked"` である

問題がなければ、final assessment に pass 済みかどうかも含めた再構築のサマリーを表示し、あなたの選択を
待ちます。

`journal.md` は、状態の再構築には意図的に*使いません*。人間向けのログで、すでに覆った決定も含んでいる
からです。

## モデルの進化に合わせて何を外すか

ここにある部品はどれも「モデルが単独ではできないこと」についての前提を形にしたもので、その前提は
いずれ古くなります。元記事の v2 では、モデルが2時間以上一貫したセッションを保てるようになった時点で、
スプリントという仕組みが不要になりました。このプラグインの generator と evaluator はそのクラスのモデル
である `claude-opus-5-5` に固定しているので、デフォルト設定はすでにその「外す」判断を反映しています。
以下は、すでに外したもの、まだ外していないもの、それぞれの根拠です。やることリストではありません。

**印象ではなく台帳を使ってください。** `/crystal-harness:status` でトークン、所要時間、エージェント別の
割合が分かり、ラウンドごとのスコアを見れば、ラウンドを重ねることにまだ意味があるかが分かります。
将来新しいモデルが出たら、部品を1つずつ外し、次の run の final assessment を前回と比べてください。
以下の変更も、そうやって決めました。

**1. スプリント — デフォルトですでにオフ(`useSprints: false`)。**
スプリントは、モデルが一貫性を保てる範囲にセッションを区切るためのものです。Opus 5.5 にはその区切りは
要りません。これは推測ではなく、10項目の仕様に対する実際の run の結果です。

- 72分の1セッションでプロダクト全体を作り、final QA 3ラウンドでクリーンな pass に到達した
- 同じ仕様をスプリントモードで作るより安く、速かった(スプリントモードは1スプリントだけで $20.13、
  v2 の run は全10項目を pass まで持っていって $44.18)

仕様が大きい、または密結合していて、進めながらレビューする小さな単位のほうが「長い1回のビルド +
収束するまでの final QA の連続」より有利な場合は、`useSprints: true` にしてください。自動で判断する
信号はないので、スコープが大きそうなら人間に聞きます。Opus 5.5 より*新しい*モデルを generator 役として
評価するなら、ここで確かめたのと同じ方法で、これを最初に確認し直してください。

**2. ブラウザ検証 — デフォルトですでにオフ(`browserVerification: false`)。**
これはモデルの能力についての賭けではなく、コストについての判断です。また、この一覧の中で唯一、
「カバーが不要になったから」ではなく、意図的にカバー範囲を*削る*項目です。

ブラウザはハーネスの中で最も高価な道具であり、何にも配線されていないコントロールを捕まえられる唯一の
道具でもあります。ビルドを「間違って見える」ではなく「間違っている」ものにする欠陥は、API・
データストア・テストスイートですべて見つかります。ほとんどのラウンドで問題になるのは後者なので、
デフォルトはオフです。

*オンに戻すべき信号:* プロダクトの価値がインターフェースにある、ラウンドの失敗がエンドポイントより
画面に集中している、出荷直前である。本物のプロダクトの final assessment では、少なくとも1回は
インターフェースを見るべきです。

**3. モデルが単独でこなせるタスクでの evaluator — `useEvaluator: false`。**
デフォルトではまだオンです。同じ run の結果も、オンのままにすべきだと示しています。generator の
セルフチェックは最初の修正を正しいと判断しましたが、その修正が気づかないうちに新しいリグレッションを
2件生んでいたことを捕まえたのは evaluator だけでした。これこそ、この部品が捕まえるために存在する
失敗であり、古いモデルだけでなく Opus 5 でも起きました。

**evaluator がコストに見合うのは、タスクがモデルの単独で確実にこなせる範囲を超えているときだけです。**
同じ run では、少なくとも状態を持つ複数画面の UI については、その境界がまだ evaluator の不要な側に
移っていないことが分かりました。

*移ったと分かる信号:* 台帳で evaluator が大きな割合を占める一方で、verdict が blocking issue なしの
`pass` で何回も続き、evaluator が挙げる non-blocking issue が generator の report にすでに書かれている。

**4. planner。** 上の2つより長く必要な部品です。スコープ不足は、モデルの能力ではなく「プロンプトが何を
求めたか」の失敗だからです。フラグはありません。外すなら、`/crystal-harness:plan` を使うのをやめて
`spec.md` を自分で書いてください。

*外してよい信号:* spec をほとんど手直ししていない。1行のアイデアをそのまま渡された generator が、
planner が出すのと同じ機能一覧を作る。

**5. final assessment — 最後まで残してください。** generator が作成に一切関わっていない基準で採点する
唯一のチェックです。コストは、スプリントモードなら run ごとに evaluator 1回分です。スプリントをオフに
すると `maxFinalQaRounds` が許す分のラウンド数になります。上の実際の run では3ラウンド必要でした。

**以上すべてについての注意: n = 1 です。** 仕様1つ、run 1回、モデル1つの結果にすぎません。この
プラグインが出荷時に変えたデフォルトを自分のプロジェクトで信用する前に、この節を読み返すだけでなく、
同じ種類の比較を自分で回してください。

**6. 成果物のプロトコル — 残してください。** `handoff.md`、`state.json`、ファイルベースの約束事は、
モデルの弱点を補うためのものではありません。クラッシュ、`/clear`、新しいセッション、別のマシンを
run が乗り越えるための仕組みです。コンテキスト長が伸びても古くなりません。

**7. ルーブリック — 残して、較正し続けてください。** 古くなるのは仕組みではなく較正です。出力の品質の
底上げが進むにつれて、かつては妥当だった Originality の 3 は 2 になります。定期的に、自分の最近の出力と
突き合わせて `calibration-examples.md` を読み直し、アンカーを動かしてください。

正直にまとめると、モデルの限界を補う部品は、その限界がなくなるにつれて削除すべきです。*プロセス*を
形にした部品、つまり「記憶の単位としてのファイル」と「作者ではない採点者」は削除すべきではありません。

## 元記事との違いとその理由

- **Functionality の閾値を、design や originality と同じ 4 にしている。** 元記事は craft と
  functionality *より* design quality と originality を重視していた。その重み付けは純粋な
  フロントエンドデザインのループには合うが、フルスタックのビルドでは、動かないアプリは他の何でも採点
  できない。重み付けは代わりに、craft と code quality を 3 にすることで表現している。
- **観点は4つではなく6つ。** 元記事は、フロントエンドデザイン用(design quality、originality、craft、
  functionality)とフルスタック用(product depth、functionality、visual design、code quality)で、
  別々の4観点のルーブリックを使っていた。このハーネスはフルスタックのビルドを対象にしているので、
  両方の和集合を採用している。どちらを削っても、元記事が捕まえたと明言している失敗の種類を失うから。
- **修正の予算に上限がある。** 元記事のフロントエンドのループは 5〜15 回反復し、最良の結果は10回目に
  出た。このハーネスのデフォルトはスプリントあたり 5 回、final は 5 ラウンドで、アプローチを変えずに
  同じ issue が再発すれば早めにエスカレーションする。元記事の「後半の反復で化ける」可能性を多少捨てて、
  行き詰まったループで run を燃やさないことを選んでいる。元記事と同じ挙動にしたければ
  `maxRevisionsPerSprint` を上げてほしい。

## ディレクトリ構成

```
../.claude-plugin/marketplace.json   # リポジトリ直下のマーケットプレイス定義。"./crystal-harness" でここを指す
crystal-harness/
├── .claude-plugin/plugin.json
├── agents/{harness-planner, harness-generator, harness-evaluator}.md
├── commands/{init,plan,build,qa,resume,status}.md
├── skills/
│   ├── harness-protocol/SKILL.md        # .harness/ の約束事、2つの JSON Schema、handoff テンプレート、台帳
│   ├── sprint-contract/SKILL.md         # 固定するインターフェースと、テスト可能な受け入れ基準
│   └── qa-rubric/
│       ├── SKILL.md                     # 6観点、アンカー、閾値、verdict.json のスキーマ
│       └── references/calibration-examples.md
├── hooks/hooks.json
├── scripts/
│   ├── guard_harness_artifacts.py       # PreToolUse hook が実行する担当範囲のポリシー
│   ├── inject_harness_context.py        # ここに run があるとき SessionStart で通知する
│   ├── append_ledger.py                 # 台帳に1エントリを、タイムスタンプ付きでアトミックに書く
│   ├── validate_verdict.py              # verdict.json のスキーマ + モードごとに pass が意味してよいこと
│   ├── validate_contract.py             # contract.md の基準数の上限、スコープの大きさ、ID の整合性
│   ├── codex_review.py                  # codex プラグインを探し、diff をレビューし、codex-review.md を書く
│   ├── test_guard.py
│   ├── test_validate_verdict.py
│   ├── test_validate_contract.py
│   └── test_codex_review.py
├── .mcp.json                            # Playwright MCP
└── README.md
```

## ライセンス

MIT.

## テスト

```bash
python3 crystal-harness/scripts/test_guard.py
python3 crystal-harness/scripts/test_validate_verdict.py
python3 crystal-harness/scripts/test_validate_contract.py
python3 crystal-harness/scripts/test_codex_review.py
```

フレームワークも依存ライブラリも不要です。

**担当範囲の guard に 43 ケース**: 2つの拒否ポリシー、両エージェントを拒否する `codex-review.md` の行、
2つの抜け道(`..` によるディレクトリ遡りと `.harness/` 内に仕込んだシンボリックリンク)、大文字小文字の
同一視、Bash の経路、正当な書き込みすべて、2つの fail-closed の経路。

**verdict の validator に 33 ケース**: スキーマと、各検証モードで `pass` が意味してよいことについての
全ルール。headless で `null` にしなければならない3観点、headless の pass がその免除と引き換えに満たす
べき条件、閾値そのもの、degraded のラウンドは絶対に pass しないこと。

**codex レビューの補助スクリプトに 14 ケース**: 偽の companion を相手にするので Codex CLI は不要。
exit code の約束事を両方向から確認する。
- レビューとして数えるのは、応答に codex のブロックがあり、status がちょうど 0 で、実際のレビュー内容が
  あるときだけ。失敗・空・解析不能・バージョン不一致の応答は何も書かずに exit 1 する。
- 0 以外で終わった場合は、前のラウンドの残りファイルが今回のラウンドの証拠として読まれる前に必ず消す。

**contract の validator に 15 ケース**: デフォルト値と設定値それぞれについて、基準数の上限ちょうど・
超過・未満、セクションの欠落や空、ID の重複、スコープ 3〜7 の範囲、コードフェンス内の例を数えないこと、
contract に存在しない ID を参照する amendment や修正メモ。

プロンプトではなくこの4つをテストしているのは、この4つが*気づかれないまま*壊れるからです。

- contract の validator が拒否しなくなると、contract は再び上限を超えて膨らみ、run のすべての
  フェーズが遅く高くなる。
- guard が拒否しなくなっても、ハーネスは動き続け、すべての verdict が自作自演になる。
- verdict の validator が拒否しなくなると、何も測っていないラウンドが pass に見える。
- レビューの補助スクリプトが exit code で嘘をつくと、受けていないセカンドオピニオンや、別の diff に
  ついてのセカンドオピニオンをラウンドが記録してしまう。

どれも目に見える症状が出ません。一方、プロンプトが劣化すれば、その出力は誰かが読むので気づけます。
