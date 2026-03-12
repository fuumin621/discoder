# discoder

[English](README_en.md)

AIコーディングエージェント（Claude Code等）をスマホからDiscord経由で操作するツール。

## 特徴

- Discordスレッド = セッション。スマホからコーディング指示が出せる
- ターミナル↔Discord間でセッションの双方向引き継ぎ
- ストリーミング応答（途中経過がリアルタイム表示、ツール実行状況も表示）
- 返信候補ボタン（応答ごとに次のアクション候補をボタンで提示）
- ポート開放不要（Discord Gateway、外向き接続のみ）
- tmuxで常駐させるだけのシンプル運用

## セットアップ

### 1. Discord Bot作成

#### 1-1. アプリケーション作成

1. [Discord Developer Portal](https://discord.com/developers/applications) を開く
2. 右上の「New Application」→ 名前を入力（例: `discoder`）→「Create」

#### 1-2. Botトークン取得

1. 左メニュー「Bot」を開く
2. 「Reset Token」→ 表示されたトークンをコピーして控えておく（後で使う）
3. 下にスクロールし「MESSAGE CONTENT INTENT」を **ON** にして「Save Changes」

#### 1-3. 招待URLの生成

1. 左メニュー「OAuth2」→「URL Generator」を開く
2. **SCOPES** で以下にチェック:
   - `bot`
   - `applications.commands`
3. 下に表示される **BOTの権限** で以下にチェック:
   - `メッセージを送信` (Send Messages)
   - `公開スレッドを作成` (Create Public Threads)
   - `Threadsでメッセージを送る` (Send Messages in Threads)
   - `メッセージ履歴を読む` (Read Message History)
4. ページ最下部に生成されたURLをコピー

#### 1-4. サーバーに招待

1. コピーしたURLをブラウザで開く
2. 「サーバーに追加」のドロップダウンから招待先のサーバーを選択
3. 「はい」→「認証」で完了

> **Tips:** Botを追加するにはそのサーバーの「サーバー管理」権限が必要です。自分専用のサーバーがなければ、Discordアプリの左下「+」→「オリジナルの作成」で無料で作れます。

### 2. インストール・起動

```bash
pip install discoder
discoder init     # 1-2で控えたBotトークンを入力
discoder start    # Bot起動（tmux内で実行推奨）
```

開発版を使いたい場合:

```bash
git clone https://github.com/fuumin621/discoder.git
cd discoder
pip install -e .
```

## 使い方

### Discordコマンド

| コマンド | 場所 | 説明 |
|---|---|---|
| `/new <prompt>` | チャンネル | 新規セッション作成（`--dir /path` でディレクトリ指定可） |
| `/resume [session_id]` | チャンネル | セッション引き継ぎ（ID省略で直近セッション） |
| `/sessions` | どこでも | アクティブセッション一覧 |
| `/handoff` | スレッド | ターミナル引き継ぎ用のセッションIDとコマンドを表示 |
| `/compact` | スレッド | コンテキスト圧縮 |
| `/model` | スレッド | モデル切替（opus / sonnet / haiku） |
| `/cost` | スレッド | セッションコスト表示 |
| `/stop` | スレッド | 実行中のタスクを中断 |
| `/clear` | どこでも | 全セッション情報をクリア |

スレッド内は返信するだけで会話が継続します。

### セッション引き継ぎ

#### ターミナル → Discord（スマホで続きをやりたい時）

スマホでDiscordを開いて `/resume` するだけ。直近のターミナルセッションが引き継がれます。

#### Discord → ターミナル（PCに戻った時）

PCに戻ったらターミナルで `claude --continue` を実行するだけ。直近のセッション（＝Discordで使っていたセッション）が再開されます。

```bash
cd /your/project && claude --continue
```

別のセッションを間に挟んだ場合など、特定セッションを再開したい時はスレッド内で `/handoff` → 表示されたコマンドをターミナルで実行。

### CLIコマンド

| コマンド | 説明 |
|---|---|
| `discoder init` | Botトークンの初期設定 |
| `discoder start` | Discord Bot起動（常駐） |

## 注意事項

- **`--dangerously-skip-permissions` が常に有効です。** Claude Codeの全ツール（ファイル編集、任意コマンド実行等）が確認なしで実行されます。Discordサーバーへのアクセス権 ≒ マシンの操作権限となるため、**信頼できるメンバーだけのサーバーで使ってください**
- **タイムアウトは15分です。** それを超えるとセッションが中断されます。長時間かかる処理（推論実行等）はtmux経由で実行するようプロンプトで指示してください
- **画像・ファイルの添付には対応していません。** テキストメッセージのみ処理されます
- **メッセージはキューイングされます。** 応答中に次のメッセージを送った場合、前の処理が完了してから順番に実行されます

## 動作要件

- Python 3.10+
- Claude Code CLI（`claude` コマンドがPATHに通っていて、API認証済みであること）
