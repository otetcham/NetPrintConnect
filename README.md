# NetPrintConnect

AIエージェントおよびCLI向けのコンビニプリント（ネットワークプリント / ネットプリント）ヘッドレス連携ツール。

会員登録不要のゲスト登録機能を用いて、PDFや画像ファイルをヘッドレスブラウザから自動アップロードし、マルチコピー機用の予約番号・ユーザー番号およびQRコードを発行します。

---

## 対応サービス

| サービス名 | 対象コンビニ | 発行内容 |
|---|---|---|
| **ネットワークプリント (networkprint.ne.jp)** | ファミリーマート、ローソン、ポプラ、ミニストップ | 10桁ユーザー番号 / 有効期限 / QRコード |
| **かんたんnetprint (printing.ne.jp)** | セブン-イレブン | 8桁プリント予約番号 / 有効期限 / QRコード |

---

## セットアップ

### 依存パッケージのインストール
`uv` を用いて環境構築を行います。
```bash
uv sync
uv run playwright install chromium
```

---

## CLIでの使用方法

### 1. 基本コマンド
```bash
# 全コンビニ向けにアップロード (デフォルト: A4)
uv run python -m netprintconnect.cli upload document.pdf

# 複数ファイルを一括アップロード
uv run python -m netprintconnect.cli upload file1.pdf file2.jpg

# 用紙サイズ（A4, B5, B4, A3）の指定
uv run python -m netprintconnect.cli upload document.pdf --paper B4

# 白黒モード・暗証番号（4桁数字）の指定（セブン-イレブン）
uv run python -m netprintconnect.cli upload secret.pdf --target seven --color mono --pin 1234
```

### 2. オプション一覧
- `-t, --target [all|seven|networkprint]`: アップロード先コンビニ（デフォルト: `all`）
- `-p, --paper [A4|B5|B4|A3]`: 用紙サイズ指定（デフォルト: `A4`）
- `-c, --color [color|mono]`: カラーモード指定
- `--pin [4桁数字]`: 印刷用暗証番号（セブン-イレブン対応）
- `--no-qr`: QRコード画像のローカル保存を無効化
- `--json-output`: スクリプト連携用JSON出力

### 3. JSON出力モード
`--json-output` オプションを指定すると、標準出力に構造化JSONのみを出力します。
```bash
uv run python -m netprintconnect.cli upload document.pdf --json-output
```

### 4. 一時ファイルのクリーンアップ
生成されたQRコード画像（`*_qr.png`）等を一括削除します。
```bash
uv run python -m netprintconnect.cli clean
```

---

## MCP (Model Context Protocol) サーバー

Claude Desktop や Cursor 等のAIエージェントツールとして組み込んで使用できます。

### 設定例 (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "netprintconnect": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/NetPrintConnect",
        "run",
        "python",
        "-m",
        "netprintconnect.mcp_server"
      ]
    }
  }
}
```

※以下のコマンドを実行すると、使用中の環境に合わせた設定JSONを出力できます。
```bash
uv run python -m netprintconnect.cli setup-claude
```

### 提供ツール
- `upload_document_for_print(file_path: str, target: str = "all", paper_size: str = "A4", color_mode: str | None = None, pin: str | None = None, save_qr: bool = True)`
  - 会話の中で「このPDFをセブンでB4・白黒で印刷できるように登録して」と指示された際にAIが自律呼び出しを行い、予約番号・概算料金・案内情報を返します。
