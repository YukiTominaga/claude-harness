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
| **テストが自分で自分を保証する** | evaluator はプロジェクトのテストスイートを頼りにするが、それを書いたのは generator。落ちるテストを消したり skip したりしても、スイートは赤くならない。 | evaluator が動く前に、そのラウンドがテストに何をしたかをスクリプトが報告する。スイートが弱められていたら、以前の pass をスイートを根拠に持ち越すことはできず、verdict の validator がそれを強制する。 |
| **上限のない run** | 「次で終わりそうだ」と見えるたびにラウンドが続く。 | 台帳をもとに確認する、任意のトークン上限とコスト上限。達したらループが止まって人間に聞き、人間が上限を上げるまで hook がハーネスのエージェントの起動を拒否する。 |
| **同じ欠陥がまた出る** | evaluator は毎ラウンド、それまでのラウンドを何も知らない状態で始まる。一度見逃した種類の欠陥は、また見逃しうる。 | verdict より長く残る issue の記録と、そこから作る**プロジェクトルール**。ルールは、diff から読めるトリガーの付いた具体的な確認で、人間が承認したものだけが有効になる。ラウンドの diff がトリガーに当たると evaluator に渡され、verdict が1つでも漏らすと validator が却下する。 |
| **当て推量の修正** | 「直した」はずの blocking issue が戻ってきて、次の試みは前回の小型版になる。 | 任意で、戻ってきた issue を、コードに触る前に**診断**する。証拠の収集、互いを見ずに立てる3つの競合仮説、それぞれへの反証、決着をつける実験の順に進む。 |

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

インストールできたか確認します。インベントリに agent 4つ、MCP サーバー 1つ、hook 3つ、skill 12個
が表示されれば正常です(7つのコマンドが、5つのリファレンス skill と合わせて skill として数えられます)。
このほかに `evaluate` と `diagnose` の2つの workflow があります。

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

**0.16.0 で、generator の報告ファイルの名前を `report.md` から `build-notes.md` に変えました。**
builder の報告も `reports/<name>.md` から `reports/builder-<name>.md` に変わっています。古い
バージョンで始めた run も、アップデート後にそのまま続けられます。ラウンドの報告を読む側は
`build-notes.md` を読み、それが無いときだけ旧名の `report.md` を読みます。両方あるときは旧名を
無視します。詳しくは「[`build-notes.md`(旧 `report.md`)](#build-notesmd旧-reportmd)」を参照してください。

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
/crystal-harness:rules                 # 戻ってきた欠陥を、承認済みのプロジェクトルールにする
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
├── state.json           # run の状態
├── ledger.jsonl         # コスト台帳。hook がエージェントの transcript から追記する
├── issues.jsonl         # 検証を通ったすべての verdict が挙げた issue の記録
├── rules.json           # 人間が承認したプロジェクトルール
├── handoff.md           # コンテキストリセット用の引き継ぎファイル(毎回書き直す)
├── journal.md           # 追記のみの、人間向けログ
├── artifacts/           # Playwright の作業出力。browser モードのみ(gitignore 対象)
├── captures/            # 書けなかったファイルを差し戻したエージェントの最終応答
├── sprints/01/
│   ├── contract.md      # generator が提案し、evaluator が受諾する
│   ├── build-notes.md   # generator の完了報告(完了 / 部分的 / 未着手) + セルフチェック
│   ├── codex-review.md  # diff の独立レビュー(codex が入っている場合)
│   ├── test-changes.json # そのラウンドがテストに何をしたか(スクリプトが出力)
│   ├── rules-to-check.json # このラウンドの diff が当たったプロジェクトルール
│   ├── diagnosis/       # 診断 workflow のときだけ: 証拠、仮説、診断
│   ├── lenses/          # 並列評価のときだけ: 観点ごとの verdict
│   ├── qa.md            # ラウンドの判定(人間向け)
│   ├── verdict.json     # ラウンドの判定(機械向け)
│   └── screenshots/
└── final/01/            # run の最後の評価。ラウンドごとに1ディレクトリ
    ├── qa.md
    ├── verdict.json
    ├── build-notes.md
    ├── codex-review.md
    ├── test-changes.json
    ├── lenses/
    └── screenshots/
```

完全な定義、2つの JSON Schema、`handoff.md` のテンプレートは
`crystal-harness:harness-protocol` skill にあります。

### `build-notes.md`(旧 `report.md`)

0.15.1 までは、generator に `report.md` を書かせていました。ところが Claude Code の `Write`
ツールは、サブエージェントが書こうとするファイルの basename が
`/^(REPORT|SUMMARY|FINDINGS|ANALYSIS).*\.md$/i` に合うと、「Subagents should return findings as
text, not write report files」というメッセージで拒否します。このチェックはツール入力の検証の段階で
働き、権限ルールや `PreToolUse` hook より先に効くので、allow ルールでも hook でも権限モードでも
外せません(Claude Code 2.1.332 で確認)。そのため generator は自分の報告を一度も書けませんでした。
プロンプトにあった回り道(同じ内容を Bash の heredoc で書く)は、auto mode の分類器に
「Undermining Oversight」として止められ、ループが止まりました。

- **名前。** `build-notes.md` は、先頭だけでなくどこにも4語のどれも含みません。規則が「先頭が」から
  「含む」に広がっても当たりません。中身(ビルドした側の申告であって判定ではない)を表し、
  `handoff.md`・`journal.md`・`qa.md` とも紛れません。builder の報告は `reports/builder-<name>.md`
  なので、builder の名前が `report-ui` や `summary` でも自分の報告を書けます。
- **古い run。** プラグインのアップデートは run の途中で入りうるので、ラウンドのディレクトリに旧名の
  `report.md` が残っていることがあります。evaluator、`commands/build.md`
  (`scripts/returned_files.py notes-path` 経由)、`team_build.py` は `build-notes.md` を読み、
  それが無いときだけ旧名を読みます。両方あるときは旧名を無視します。builder の旧名
  `reports/<name>.md` も同じ扱いです。guard は新旧どちらの名前も同じように守ります。evaluator は
  読むだけで、書けるのは generator だけです。
- **それでも `Write` が拒否されたとき。** 拒否を回り込めという指示は、どのプロンプトにももうありません
  (Bash でも、別の名前でも)。プラグインの外の規則で `Write` を拒否されたエージェントは、最終応答の
  末尾に `Write rejected:` の行と、`<!-- crystal-harness:begin <name> -->` と
  `<!-- crystal-harness:end <name> -->` で囲んだファイルの本文を置いて止まります。`SubagentStop`
  hook がその最終応答をそのまま `.harness/captures/` に保存し、オーケストレーターは
  `returned_files.py place` を実行します。`place` は、そのエージェントの役割が持つファイルに限って、
  各ブロックを1バイトも変えずに書き、出所を journal に残します。それ以外の場合は何も書かず、run は
  止まって人間に判断を仰ぎます。オーケストレーターが本文を書き写すことはありません。報告は generator
  の証言であり、オーケストレーターが写したものはオーケストレーター自身の言葉になってしまうからです。
  この機械的な経路には人の了承を挟みません。何も判断していないからです。人間には journal と
  ラウンドの報告で知らせます。
- `scripts/test_subagent_filenames.py` が、`agents/`・`skills/`・`commands/`・`workflows/` に出てくる
  `.md` の名前(プレースホルダ入りのものも含む)をすべて集め、Claude Code が拒否する名前があれば
  落ちます。同じ間違いが気づかれないまま出荷されることはもうありません。

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

`.harness/ledger.jsonl` は、各エージェントにかかったコストを記録する追記専用のファイルです。
エージェント、フェーズ、スプリント、ラウンド、所要時間のほか、トークン数を input・cache write・
cache read・output の4区分で持ちます。

これを書くのはモデルではありません。エージェント(サブエージェント、workflow のエージェント、
agent team の teammate)が終わるたびに `SubagentStop` hook が `scripts/ledger.py` を実行し、
**そのエージェントの transcript にある全 API リクエスト**の usage を合計します。

以前は Agent ツールが返す `subagent_tokens` を記録していましたが、意図的にやめました。この値は
エージェントの実行全体ではなく、*最後の1リクエスト*の大きさだと分かったからです。Claude Code
2.1.329 での実測では、3リクエストで 64,685 トークンを処理したエージェントが 21,689 と報告しました。
長時間の generator セッションでは差が桁違いになり、以前の台帳はどの run もその分だけ過小に
記録していました。

hook は少しだけ待つ必要もあります。Claude Code がエージェントの最後の応答を transcript に書くのは、
`SubagentStop` の発火から約 100 ミリ秒後です。そのため hook は、1リクエスト足りない transcript を
合計してしまわないよう、最後のメッセージが現れるまで待ってから集計します。

これがあるのは、この設計で繰り返し必要になる最も重要な判断が「*この部品はまだコストに見合っているか*」
であり、それは文章からは答えられないからです。`/crystal-harness:status` は `ledger.py report` の出力
(エージェント別とラウンド別の表、run 全体に占める evaluator の割合)をそのまま表示します。
`harness.costPerMTokUsd` を設定すれば推定ドル額も出ます。料金は4区分それぞれで指定します。長い
セッションのトークンの大半は cache read で、新規の input よりはるかに安いからです。

台帳がなければ、後述の「何を外すか」の節はただの意見です。台帳があれば、「evaluator は直近
4スプリントで何も見つけておらず、run のコストの 38% を占めた」は事実になります。

台帳に含まれないものが2つあります。オーケストレーターのセッション自身の使用量と、codex レビューの
トークンです(所要時間は記録しますが、コストはこちらに報告されません)。transcript を読めなかった
場合は `tokens: null` で記録し、レポートが該当する呼び出しの件数を表示します。欠けた値を推定で
埋めることはありません。

### 担当範囲の強制

`hooks/hooks.json` は `PreToolUse` hook を1つ登録します。この hook がブロックするものは、
どれも気づかれないまま設計を壊すものです。

- `harness-generator` が `sprints/NN/` や `final/NN/` の下に `qa.md`、`verdict.json`、
  `screenshots/` を書くこと。generator が verdict を書けるなら、すべての pass が自作自演になる。
- `harness-evaluator` が `.harness/` の外に何かを書くこと。evaluator が採点対象を直せるなら、
  自分が判定するものの作者になってしまう。
- **どちらか一方でも** `codex-review.md` や `test-changes.json` を書くこと。両方が禁止されている
  ファイル。どちらも generator の diff についての証拠で、evaluator が起動する前に用意される。
  generator が書けるなら、セカンドオピニオンや「自分が消したテストの報告」を自作できてしまう。
  evaluator が書けるなら、自分がこれから引用する証拠を編集できてしまう。
- `harness-generator` がラウンドの `lenses/` の下に何かを書くこと。並列評価では、そこにある
  ファイルが verdict そのものだから。
- **どちらか一方でも** `rules.json`、`issues.jsonl`、ラウンドの `rules-to-check.json` を書くこと。
  ルールを編集できる generator は、自分を捕まえるはずのルールを消せてしまう。
- generator 以外が generator の報告(`build-notes.md`、または古い run の旧名 `report.md`。どちらも
  同じ扱い)を書くこと、および builder が自分の `reports/builder-<name>.md` 以外の報告を書くこと。
  報告は generator の証言で、evaluator は読むだけで書き換えない。
- **どのエージェントであれ** `.harness/captures/` を書くこと。オーケストレーターが差し戻された
  ファイルを置くときの元になる最終応答なので、偽造できれば別のエージェントの言葉をでっち上げられる。
- `harness-investigator` がラウンドの `diagnosis/` 以外に書くこと。調査役の仕事は診断であり、
  自分で書き換えたツリーに対する診断は、別のツリーの診断になってしまう。

同じ hook が、オーケストレーターのファイル(`state.json`、`handoff.md`、`journal.md`、
`config.json`、`spec.md`)と `ledger.jsonl` への両者の書き込みも止めます。台帳を編集できる
エージェントは、自分を安く見せられるからです。

それ以外はすべて素通しします。フォーマット用の hook も、汎用のログ用 hook もありません。どちらも
特定の失敗を防がないからです。何も防がない足場こそ、この設計全体が避けようとしているオーバーヘッドです。
残り2つの hook は、それぞれ1つの失敗に対応しています。`SessionStart` は、ここに run がすでにある
ことを知らせます。`SubagentStop` は上のコスト台帳を記録します。モデルが覚えていて書くはずの
エントリは、いずれ書かれなくなるからです。`SubagentStop` はもう1つ、ファイルを差し戻したエージェントの
最終応答を保存します。差し戻されたファイルを、オーケストレーターが写したものからではなく、
エージェントが書いたものから置くためです。

境界での振る舞いとその理由:

- **エージェントは `agent_type` の最後の区切りで見分ける。** Claude Code は、プラグインの
  エージェントを素の名前ではなく `crystal-harness:harness-generator` という形で hook に渡す。
  0.10.0 より前の guard は、届いた値をそのまま素の名前と比較していたため何にも一致せず、すべての
  書き込みを許可していた。インストールされたすべてのコピーで起きていたが、症状は何も出ず、素の名前を
  使っていた guard 自身のテストも通っていた。現在のテストは、名前空間付きの形を最初に確認する。
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
    "teamBuild": false,               // true → 最初のビルドを builder の teammate に分担させる
    "maxBuilders": 3,                 // チームビルドのときだけ: builder の数の上限
    "diagnoseRecurringIssues": false, // true → 戻ってきた blocking issue を診断する
    "parallelEvaluation": false,      // true → 観点ごとに evaluator を立て、スクリプトで統合する
    "reproduceBlockingIssues": true,  // 並列評価のときだけ: blocking issue を1件ずつ再現させる
    "maxSprints": 12,
    "maxRevisionsPerSprint": 5,
    "maxAcceptanceCriteria": 20,      // スプリント contract あたりの上限。validate_contract.py が強制
    "maxFinalQaRounds": 5,
    "maxRunTokens": null,             // エージェントがこのトークン数を使ったら止まって聞く
    "maxRunCostUsd": null,            // …またはこの金額に達したら(costPerMTokUsd が必要)
    "costPerMTokUsd": null            // {input, output, cacheWrite, cacheRead} を USD/MTok で指定
                                      // → /crystal-harness:status に推定ドル額が出る
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
| `harness-investigator` | `claude-opus-5-5` | `high` | generator が一度見誤った原因を突き止める |

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
   build / typecheck / test を実行して自分の失敗を直し、`build-notes.md` に「完了したこと」「部分的なこと」
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

### そのラウンドがテストに何をしたか

evaluator はプロジェクトのテストスイートを2つの場面で頼りにします。スイートが落ちれば、それは
決定的な証拠です。そして再チェックのラウンドでは、スイートが通っていることを根拠に、前回 pass した
基準を検証し直さずに*持ち越し*ます。ところが、そのスイートを書くのは generator です。つまり
generator には、正しくないまま通す手段があります。落ちるテストを消す、skip する、テストコマンドを
必ず成功する別のものに差し替える、のいずれかです。どれもスイートを赤くしません。

そこで evaluator が動く前に、`scripts/test_changes.py` がラウンドの diff を読み、ラウンドの
ディレクトリに `test-changes.json` を書きます。内容は、追加・変更・削除されたテストファイル、
削除されたテストケース、追加された skip や `.only` の印、`package.json` の `scripts.test` の変更、
そして `weakened` というフラグです。evaluator はスイートを頼る前にこれを読み、理由の示されていない
削除を blocking issue として扱います。

誰の判断にも依存しない部分もあります。レポートが `weakened` のとき、
`validate_verdict.py --test-changes` は、以前のラウンドから pass を持ち越した verdict を却下します。
そのラウンドは全体を検証し直すことになります。この判定は意図的に厳しめです。正当なリファクタリングでも
反応することがありますが、誤検知のコストは「1ラウンド分の全件検証」で済むのに対し、見逃しのコストは
「誰も稼いでいない pass」だからです。

codex レビューと同じく、このファイルはどちらのエージェントも書けません。guard が両方を止めます。

### プロジェクトルール

コンテキストリセットとは、evaluator が毎ラウンド、以前のラウンドを何も知らない状態で始まるという
ことです。それが狙いですが、同時に、一度見逃した種類の欠陥はまた見逃しうるということでもあります。
プロジェクトルールは、リセットを越えて残る記憶です。データとして持ち、コードで適用します。

- 検証を通った verdict が出るたびに、`scripts/rules.py record` がその issue を
  `.harness/issues.jsonl` に追記する。verdict のファイルは次のラウンドで上書きされるが、この記録は残る。
- `/crystal-harness:rules` が記録を読み、**戻ってきたもの**(2ラウンド以上に現れた issue、2つ以上の
  別々の issue の原因とされたソースファイル)を拾う。価値のある候補にはルールの下書きを作り、
  あなたが承認したものだけを保存する。1回だけ起きたことは逸話にすぎず、逸話から作ったルールは
  チェックリストを雑音で埋める。
- ルールは、具体的な確認内容(`check`)と、**diff から読めるトリガー**(パスの glob と、追加行に
  含まれるキーワード)の組。トリガーのないルールは拒否される。評価の前に `rules.py match` が、
  このラウンドの diff が当たったルール(たいていはゼロ件)を `rules-to-check.json` に書く。
  ラウンドが尋ねられるのは、自分の diff が触れた範囲のことだけになる。
- evaluator は、挙げられた確認をプロダクト上で1つずつ行い、ルールの ID を verdict に列挙する。
  1つでも漏らした verdict は `validate_verdict.py --rules` が却下する。成り立たなかったルールは
  blocking issue になる。

ルールはプロジェクトごとで、`.harness/` の中に置きます。あるコードベースの失敗から学んだルールは、
別のコードベースでは雑音だからです。ルール、記録、ラウンドに渡された一覧のどれも、エージェントは
編集できません。

### 再発した issue の診断

デフォルトはオフ(`diagnoseRecurringIssues: false`)です。ループはもともと、2回目の修正に入る
generator に「パッチは失敗した、アプローチを変えよ」と伝え、3回目で人間のために止まります。
この機能はその間に入ります。blocking issue が一度戻ってきたら、コードにもう一度触る前に、
プラグインの `diagnose` workflow が原因を突き止めます。

パッチが失敗するのは、たいてい原因を当て推量したからです。そして最初にもっともらしく見えた説明が、
全員の頭に残り続けます。そこで8体の `harness-investigator` を、意図的に互いから切り離します。

1. **証拠** — 1体が issue を再現し、見えたものを説明抜きで記録する。最後の段階まで、アプリを
   動かしてよいのはこの1体だけ。
2. **仮説** — 3体が、*種類*の異なる原因について最も強い主張を組み立てる。データが違う(`state`)、
   制御の流れが違う(`wiring`)、報告のほうが違う(`premise`)の3つで、互いの成果は見ない。
   各自、これまでの修正がなぜ失敗したはずかを説明し、自分の仮説を沈めうる実験を1つ挙げる。
3. **反証** — さらに3体が、仮説を1つずつ崩しにかかる。
4. **診断** — 1体が、生き残った仮説の実験を実行し、根本原因、修正が変えなければならないこと、
   直ったと分かる方法を書く。確信度は、決して切り上げないよう指示されている。

調査役は読んで動かすだけです。guard が書き込みをラウンドの `diagnosis/` に限ります。修正は
あくまで generator の仕事で、generator には診断だけが渡されます。ハーネスの中で最も高価な
単一の手順ですが、動くのは、すでに修正1回分のコストを使った issue に対してだけです。

### 引き継いだ欠陥と不安定なテスト

小さなルールが2つあります。どちらも、失敗の出どころを見誤らないためのものです。

`/crystal-harness:init` は、run が始まった時点のコミットを記録します。原因がそのコミットから
変わっていない欠陥には `preExisting` の印が付きます。リグレッションではなく、引き継いだものという
意味です。この印は割引ではありません。issue が blocking になる条件は変わらず、final assessment では
仕様がその振る舞いを約束している限り blocking です。変わるのは、欠陥の読み方と直し方であって、
数えるかどうかではありません。

ときどき落ちるテストには原因があります。generator は、sleep、リトライ、タイムアウトの延長で
テストを通すことを禁じられています。evaluator はスイートを1回だけ実行し、2回目で通るスイートは
落ちているものとして扱います。テスト変更レポートは、ラウンドがテストに追加した sleep とリトライを
すべて列挙するので、evaluator は1つずつ確認できます。

### チームビルド

デフォルトはオフ(`teamBuild: false`)です。オンにすると、ラウンドの最初のビルドを、最大
`maxBuilders` 体の generator が同時に進めます。それぞれが `builder-<名前>` という名前の agent team の
teammate です。1つの作業ツリーに generator が2体いると衝突します(ハーネスが普段1体ずつ動かすのは
そのためです)。そこでチームビルドは**分担表(split plan)**がある場合に限って行い、その取り決めのうち
スクリプトで検査できる部分は、頼むのではなく検査します。

1. generator 1体が単独で `split.json` を書く。builder ごとの担当範囲(`scope`)と担当パス(`owns`)、
   そして builder 間の**固定インターフェース**(ルートとペイロードの形、テーブル名、終了コードなど)を
   定める。こうしておけば、誰も他人のコードができるのを待たずに済む。作業に分け目がなければ builder
   1体の分担表を書き、ビルドは通常どおり generator 1体で進む。
2. `scripts/team_build.py validate` が、2体の担当パスが重なっている分担表、判定できないワイルドカードを
   使った分担表、複数の builder がいるのにインターフェースを何も固定していない分担表を却下する。
3. builder が動く。担当範囲の guard が、各 builder を自分の担当パスに留める。それ以外への書き込みは
   拒否され、builder は担当者に依頼するよう促される。自分を縛る分担表を builder が書き換えることは
   できない。
4. builder は `team_build.py commit` を通してコミットする。このスクリプトは、ロックを取ったうえで、
   コミットする builder の担当パスだけをステージする。`git add`、`commit`、`stash`、`reset`、
   `checkout` とその仲間は builder には拒否される。どれも作業ツリー全体に作用し、他の builder が
   編集している最中だから。
5. builder が止まったら、`team_build.py check` が、分担表で許されていないもの(未コミットの作業、
   誰の担当でもないのに変更されたパス、欠けているレポート)を、直せる builder 宛てに列挙する。
   続いて `team_build.py report` が、builder 自身のレポート(`reports/builder-<name>.md`)を、
   evaluator が読む `build-notes.md` にまとめる。

QA で fail した後の修正は分担しません。対象は少数の blocking issue なので、今までどおり generator
1体に任せます。builder はラウンドをまたいで使い回さないので、ハーネスのコンテキストリセットの原則は
保たれます。

これを安全にするために、1つ塞いだ穴があります。hook に届くのは、teammate が起動された元の
エージェント種別ではなく、リードが付けた**名前**です。guard は種別で役割を見分けるので、任意の名前で
起動された generator は guard から見えません。そこで、誰にどんな名前を付けてよいかを2つ目の hook が
決めています。`harness-generator` に付けてよい名前は、有効な分担表にある builder `x` に対する
`builder-<x>` だけで、`harness-evaluator` には名前を付けられません。この hook は `teamBuild` がオフでも、
agent teams を有効にしている人すべてに関係します。

チームビルドには agent teams(`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`)が必要です。実験的機能で、
対話セッションでしか動きません。有効でない場合、ビルドは1行でそう伝えて generator 1体で進みます。

### 並列評価

デフォルトはオフ(`parallelEvaluation: false`)です。オンにすると、1体の evaluator がすべてを見る
代わりに、**観点(lens)**ごとに `harness-evaluator` を1体ずつ立ててラウンドを採点します。

| 観点 | やること | 採点する観点 |
| --- | --- | --- |
| `tests` | ビルドし、スイートを実行し、`test-changes.json` を確認する | なし |
| `api` | API を叩き、データストアを読む。ブラウザなしのときは受け入れ基準も担当する | product depth、functionality |
| `screen` | Playwright で画面を操作する。`browserVerification: true` のときだけ存在し、そのとき受け入れ基準を担当する | product depth、functionality、design、originality、craft |
| `code` | diff と `codex-review.md` を読む | code quality |

実行するのはプラグインの `evaluate` workflow です。`code` を、`tests` → `api` → `screen` の列と
並行して走らせます。アプリを動かす観点を意図的に直列にしているのは、ポートとデータストアを共有する
からです。別の観点がレコードを作った直後に「空の状態」の確認が失敗しても、それは偽の失敗です。
したがってこのモードで得られるのは、所要時間の短縮よりも、観点ごとの集中と「もう一度見る目」です。
ラウンドあたりのエージェント数は増えます。

結果をモデルが統合することはありません。各観点はラウンドの `lenses/` の下に自分の verdict ファイルを
書き、`scripts/merge_verdicts.py` が、部分より厳しくなる方向にしか働かない規則で、ラウンドの
`verdict.json` と `qa.md` を作ります。

- 2つの観点が同じ観点を採点したら、**低いほう**の点を採る
- すべての観点の blocking issue をすべて残す
- **すべての**観点が自分の担当分を pass したときだけ、ラウンドは pass
- 観点のファイルが欠けている、形式が壊れている、内容が自己矛盾している、別のラウンドや別のコミットの
  ものである、のいずれかなら**verdict は出ない**。スクリプトは exit 2 で終わり、何も書かない

最後の規則は、ブラウザが応答しなかったときの `degraded` モードと同じ考え方です。設定された範囲より
少ししか測れなかったラウンドを、verdict として読ませてはいけません。

`reproduceBlockingIssues: true` のとき、workflow は続けて、blocking issue を1件ずつ新しい evaluator に
渡します。渡すのは再現手順と期待される振る舞いだけで、観点側のメモも原因も渡しません。同じ失敗が
見えたかどうかが、issue に記録されます。これは注記であって、ふるいではありません。誰も再現できなかった
issue も blocking のまま残り、ラウンドは fail のままです。変わるのは停止ルールです。generator も
再現できなければ、独立した2者が再現に失敗したことになるので、ループは2回目の修正に進まず人間に聞きます。

デフォルトがオフなのは、ここにある他のデフォルトと同じ理由です。1体の evaluator が見逃すものを各観点が
どれだけ見つけるのか、まだ測れていません。観点と再現はそれぞれ台帳の1エントリになるので、同じ仕様に
対してオンで1回、オフで1回走らせれば、コストに見合うかを比べられます。

### 予算上限

`maxRunTokens` と `maxRunCostUsd` は、run がエージェントに使ってよい量の上限です。数えるのは台帳です。
オーケストレーターはエージェントを起動する前に毎回確認し(`ledger.py budget`)、上限に達したら止まって
人間に聞きます。文章だけで書かれた停止ルールは飛ばされるので、`PreToolUse` hook がこれを保証に
変えています。上限に達すると、ハーネスのエージェントと `evaluate` workflow の起動を拒否し、人間が
`config.json` の上限を書き換えるまで解除されません。

コスト上限には料金が必要です。`costPerMTokUsd` なしで `maxRunCostUsd` を設定すると、「強制できない
上限」として報告し、run を止めます。設定したのに黙って何もしない上限は、上限がないより悪いからです。
この hook 自体は、失敗時に通す(fail open)設計です。コスト管理であって担当範囲の境界ではないので、
hook 側のエラーで作業が止まることはありません。

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

**診断 — オフです。おそらく、これらの中で最後までデフォルトにならない機能です。**

*オンにしてよい信号:* 同じ issue で3回 fail して `blocked` で終わる run があり、2回目と3回目の
修正が1回目の変形だった。

*コストに見合っていない信号:* 診断の確信度が `low` で返ってくる。または、evaluator がすでに
verdict に書いていた原因を、診断がそのまま挙げている。

**チームビルド — これもまだオンにしていません。理由は同じです。**

*オンにしてよい信号:* プロダクトに本当の分け目があり、1回のビルドが run の中で最も時間のかかる
部分になっている。

*オフに戻す信号:* 台帳で builder の合計が、同程度の仕様を generator 1体で作ったときを大きく上回る。
または、evaluator の最初のラウンドが、分担表が引いた境界で欠陥を見つけ続ける。

**並列評価 — まだオンにしていません。証拠で決めてください。** 並列評価とチームビルドは、ここにある
部品の中で、外されるのを待つのではなく後から足したものなので、オフの状態で出荷しています。

*オンにしてよい信号:* 1体の evaluator のラウンドが、特定の領域(API、テスト、コード)の欠陥を
見逃し続け、後のラウンドや人間がそれを見つけている。

*オフに戻す信号:* 台帳では各観点の合計が1体の evaluator の何倍ものコストになっているのに、統合された
verdict が、同じビルドに対して1体の evaluator が返すものと変わらない。

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
├── agents/{harness-planner, harness-generator, harness-evaluator, harness-investigator}.md
├── commands/{init,plan,build,qa,resume,status,rules}.md
├── skills/
│   ├── harness-protocol/SKILL.md        # .harness/ の約束事、2つの JSON Schema、handoff テンプレート、台帳
│   ├── evaluation-lenses/SKILL.md       # 4つの観点、観点ごとの verdict ファイル、issue の再現
│   ├── team-build/SKILL.md              # 分担表と、builder の teammate が従うルール
│   ├── sprint-contract/SKILL.md         # 固定するインターフェースと、テスト可能な受け入れ基準
│   └── qa-rubric/
│       ├── SKILL.md                     # 6観点、アンカー、閾値、verdict.json のスキーマ
│       └── references/calibration-examples.md
├── workflows/
│   ├── evaluate.js                      # 並列評価: 観点ごとに evaluator 1体、続いて issue の再現
│   └── diagnose.js                      # 再発した issue: 証拠、3つの仮説、反証、診断
├── hooks/hooks.json
├── scripts/
│   ├── guard_harness_artifacts.py       # PreToolUse hook が実行する担当範囲のポリシー
│   ├── inject_harness_context.py        # ここに run があるとき SessionStart で通知する
│   ├── ledger.py                        # コスト台帳: SubagentStop hook、codex 分の追記、集計、予算ゲート
│   ├── test_changes.py                  # ラウンドがテストに何をしたか: 削除、skip、コマンドの差し替え
│   ├── merge_verdicts.py                # 観点ごとの verdict → 1つの verdict.json + qa.md。無理なら何も出さない
│   ├── team_build.py                    # 分担表: 検査、有効化、builder ごとのコミット、後始末の検査、名前のゲート
│   ├── returned_files.py                # 差し戻されたファイル: SubagentStop での保存、place、notes-path
│   ├── rules.py                         # issue の記録、ルールの候補、承認済みルール、diff が当たるルールの判定
│   ├── validate_verdict.py              # verdict.json のスキーマ + モードごとに pass が意味してよいこと
│   ├── validate_contract.py             # contract.md の基準数の上限、スコープの大きさ、ID の整合性
│   ├── codex_review.py                  # codex プラグインを探し、diff をレビューし、codex-review.md を書く
│   ├── test_guard.py
│   ├── test_validate_verdict.py
│   ├── test_validate_contract.py
│   ├── test_codex_review.py
│   ├── test_ledger.py
│   ├── test_test_changes.py
│   ├── test_merge_verdicts.py
│   ├── test_team_build.py
│   ├── test_rules.py
│   ├── test_returned_files.py
│   └── test_subagent_filenames.py
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
python3 crystal-harness/scripts/test_ledger.py
python3 crystal-harness/scripts/test_test_changes.py
python3 crystal-harness/scripts/test_merge_verdicts.py
python3 crystal-harness/scripts/test_team_build.py
python3 crystal-harness/scripts/test_rules.py
python3 crystal-harness/scripts/test_returned_files.py
python3 crystal-harness/scripts/test_subagent_filenames.py
```

フレームワークも依存ライブラリも不要です。

**担当範囲の guard に 133 ケース**: Claude Code が実際に送ってくる名前空間付きの `agent_type`、
2つの拒否ポリシー、両エージェントを拒否する `codex-review.md` と `test-changes.json` の行、
観点ごとのファイル、コスト台帳、自分の担当パスに留められ作業ツリー全体に効く git コマンドを
禁じられた builder、自分の調査結果だけを書ける調査役、プロジェクトルール、
`build-notes.md` と旧名 `report.md` の両方で守られる generator の報告、`reports/builder-<name>.md`
だけを書ける builder の報告、どのエージェントも書けない captures、
2つの抜け道(`..` によるディレクトリ遡りと `.harness/` 内に仕込んだシンボリックリンク)、大文字小文字の
同一視、Bash の経路、正当な書き込みすべて、2つの fail-closed の経路。

**verdict の validator に 61 ケース**: スキーマ、弱められたテストスイートは持ち越しの pass を
すべて無効にするという規則、当たったプロジェクトルールをすべて報告するという規則、そして各検証モードで `pass` が意味してよいことについての
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

**テスト変更レポートに 24 ケース**: スイートを薄くする方法のそれぞれ(ファイルの削除、ケースの削除、
skip、`.only`、`xfail`、テストコマンドの差し替えや削除、テストのツリー外へのリネーム)と、警告を
出してはいけない正当な変更のそれぞれ。

**verdict の統合に 47 ケース**: 2つの点のうち低いほうが残ること、すべての issue が残ること、1つの
観点の fail がラウンドを fail にすること、再現結果は issue に注記されるだけで issue を消さないこと。
加えて、観点の欠落から別コミットを採点したファイルまで、統合そのものを拒否する20通りあまり。

**チームビルドに 60 ケース**: 2体の担当パスが重なりうるすべての形、分担表で使えないパスの書き方、
1体の builder のファイルだけを取り込み他の builder のファイルには触れないコミット、`check` が報告する
残り物とその宛先、`report` が書く報告(`build-notes.md` であって旧名ではない)、新しい名前が無いとき
だけ読む builder の旧名の報告、どのエージェントにどの名前を許すかを決めるゲート。

**差し戻されたファイルに 35 ケース**: 差し戻すファイルを持つエージェントの最終応答だけをそのまま保存し、
どんな不正な入力でも exit 0 で終わる hook。各ブロックを1バイトも変えずに書く `place`(非 ASCII、
行末の空白、コードフェンス、目印に似た行を含む本文)と、その journal への記録。何も書かずに拒否する
場合として、generator からの verdict、evaluator からの generator の報告、終わりの目印がないブロック、
同じファイルの二重、空、入れ子、どれか決められない複数の capture、ラウンドではないディレクトリ。
旧名 `report.md` より `build-notes.md` を優先する `notes-path`。

**エージェントに書かせるファイル名に 29 ケース**: `agents/`・`skills/`・`commands/`・`workflows/` に
出てくるすべての `.md` の名前を、プレースホルダを展開したうえで、Claude Code がサブエージェントの
`Write` に適用する規則と照らし合わせる。旧名 `report.md` に触れる箇所はすべて legacy と明記されて
いること、スクリプト間で名前が一致していること、拒否された書き込みを Bash で回り込めと指示する
プロンプトが残っていないことも確かめる。

**プロジェクトルールに 29 ケース**: 同じラウンドを2回記録しても記録が倍にならないこと、何をもって
「戻ってきた」とするか、トリガーのないルールや何にでも当たるトリガーの拒否、そして判定の処理。
`.harness/rules.json` に書かれたルール自身のキーワードが、追加した瞬間にそのルールを発火させない
ことも含む。

**コスト台帳に 73 ケース**: 最後の1リクエストではなく全リクエストを合計すること、hook の開始後に
transcript へ届いた最後の応答も数えること、ストリームで複数行に
分かれた応答を1回だけ数えること、複数回停止したエージェントのスナップショットを加算せず置き換えること、
hook がどんな不正な入力でも exit 0 で終わり、読めない transcript をゼロではなく `null` として記録
すること、区分ごとの料金計算、0.10.0 より前の `state.json` のエントリをトークン合計に入れないこと、
予算上限とそれを強制する hook。

プロンプトではなくこの11個をテストしているのは、この11個が*気づかれないまま*壊れるからです
(最後の1つは例外的にプロンプトを検査しますが、それはプロンプトのこの性質が同じように気づかれないまま
壊れるからです)。

- エージェントに Claude Code が拒否するファイルを書かせると、拒否は run の途中で起き、ループが止まる。
- `place` が甘くなると、あるエージェントの言葉が別のエージェントのファイルに入り込む。

- contract の validator が拒否しなくなると、contract は再び上限を超えて膨らみ、run のすべての
  フェーズが遅く高くなる。
- guard が拒否しなくなっても、ハーネスは動き続け、すべての verdict が自作自演になる。
- verdict の validator が拒否しなくなると、何も測っていないラウンドが pass に見える。
- レビューの補助スクリプトが exit code で嘘をつくと、受けていないセカンドオピニオンや、別の diff に
  ついてのセカンドオピニオンをラウンドが記録してしまう。
- 台帳が記録をやめたり二重に数えたりしても、表はもっともらしく見え、「何を外すか」の判断がすべて
  その表に基づいて下される。
- テスト変更レポートが消されたテストに気づかなくなると、スイートは再び自分で自分を保証するようになる。
- 統合が甘くなると、主張より少ししか測っていないラウンドが pass に見える。
- ルールの判定がルールを発火させなくなると、そのルールが尋ねるはずだった問いを、evaluator は
  二度と尋ねられない。
- 分担表の validator が重なったパスを受け入れるようになっても、ビルドは完了する。ただし、ある
  builder の成果が別の builder の成果で置き換えられている。

どれも目に見える症状が出ません。一方、プロンプトが劣化すれば、その出力は誰かが読むので気づけます。
