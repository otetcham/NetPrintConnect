import asyncio
import json
import sys
from pathlib import Path
import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import PrintJobResult
from .networkprint_client import upload_to_networkprint
from .seven_client import upload_to_seven

console = Console()

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """ネットワークプリント & ネットプリント ヘッドレスアップロードツール"""
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())

@cli.command("upload")
@click.argument("file_paths", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--target", "-t",
    type=click.Choice(["all", "seven", "networkprint"], case_sensitive=False),
    default="all",
    show_default=True,
    help="アップロード対象 (all: 両方, seven: セブン-イレブン, networkprint: ファミマ/ローソン等)"
)
@click.option(
    "--paper", "-p",
    type=click.Choice(["A4", "B5", "B4", "A3"], case_sensitive=False),
    default="A4",
    show_default=True,
    help="用紙サイズ (A4, B5, B4, A3)"
)
@click.option(
    "--color", "-c",
    type=click.Choice(["color", "mono"], case_sensitive=False),
    default=None,
    help="カラーモード (color: カラー, mono: 白黒)"
)
@click.option(
    "--pin",
    type=str,
    default=None,
    help="暗証番号 (4桁数字、セブン-イレブンのみ対応)"
)
@click.option("--no-qr", is_flag=True, default=False, help="QRコード画像の保存をスキップ")
@click.option("--json-output", is_flag=True, default=False, help="結果をJSON形式で標準出力に出力（AI・スクリプト連携用）")
def upload_command(file_paths: tuple[Path, ...], target: str, paper: str, color: str | None, pin: str | None, no_qr: bool, json_output: bool):
    """指定したファイル（単一または複数）をコンビニプリントにアップロードし、予約番号を発行します。"""
    asyncio.run(_run_upload_all(file_paths, target, paper_size=paper, color_mode=color, pin=pin, save_qr=not no_qr, json_output=json_output))

async def _run_upload_all(file_paths: tuple[Path, ...], target: str, paper_size: str, color_mode: str | None, pin: str | None, save_qr: bool, json_output: bool):
    all_results: list[PrintJobResult] = []
    all_errors: list[dict] = []

    for file_path in file_paths:
        if not json_output:
            console.print(f"[bold cyan]📁 ファイル:[/bold cyan] {file_path.resolve()}")
            console.print(f"[bold cyan]対象サービス:[/bold cyan] {target} | [bold cyan]サイズ:[/bold cyan] {paper_size}" + 
                          (f" | [bold cyan]カラー:[/bold cyan] {color_mode}" if color_mode else "") +
                          (f" | [bold cyan]暗証番号:[/bold cyan] {pin}" if pin else "") + "\n")

        tasks = []
        if target in ["all", "networkprint"]:
            if pin:
                console.print("[dim yellow]※ ネットワークプリント (ファミマ/ローソン) はゲスト暗証番号非対応のため、PINはセブン-イレブンにのみ適用されます。[/dim yellow]")
            tasks.append(("networkprint", upload_to_networkprint(file_path, save_qr=save_qr, paper_size=paper_size, color_mode=color_mode)))
        if target in ["all", "seven"]:
            tasks.append(("seven", upload_to_seven(file_path, save_qr=save_qr, paper_size=paper_size, color_mode=color_mode, pin=pin)))

        for svc_name, task in tasks:
            with console.status(f"[bold green]{svc_name} にアップロード処理中...[/bold green]", spinner="dots") if not json_output else nullcontext():
                try:
                    res = await task
                    all_results.append(res)
                except Exception as e:
                    all_errors.append({"file": file_path.name, "service": svc_name, "error": str(e)})
                    if not json_output:
                        console.print(f"[bold red]× {svc_name} エラー:[/bold red] {e}")

    if json_output:
        output_data = {
            "success": len(all_results) > 0,
            "results": [
                {
                    "service": r.service,
                    "service_name": r.service_name,
                    "file_name": r.file_name,
                    "print_code": r.print_code,
                    "expires_at": r.expires_at,
                    "page_count": r.page_count,
                    "color_mode": r.color_mode,
                    "qr_code_path": r.qr_code_path,
                    "details": r.details
                }
                for r in all_results
            ],
            "errors": all_errors
        }
        print(json.dumps(output_data, ensure_ascii=False, indent=2))
        return

    # リッチ表示
    if all_results:
        table = Table(title="🖨️ コンビニプリント 予約番号一覧", show_header=True, header_style="bold magenta")
        table.add_column("ファイル名", style="bold")
        table.add_column("対象コンビニ", style="cyan")
        table.add_column("予約コード / ユーザー番号", style="bold yellow")
        table.add_column("ページ数", style="blue")
        table.add_column("概算料金", style="magenta")
        table.add_column("有効期限", style="green")
        table.add_column("QRコード", style="dim")

        for r in all_results:
            table.add_row(
                r.file_name,
                r.service_name,
                r.print_code,
                r.page_count or "ー",
                r.estimated_cost or "ー",
                r.expires_at or "ー",
                Path(r.qr_code_path).name if r.qr_code_path else "なし"
            )
        console.print(table)
        console.print()

        for r in all_results:
            panel_content = (
                f"[bold]{r.file_name}[/bold] ({r.service_name})\n"
                f"予約番号: [bold yellow]{r.print_code}[/bold yellow]\n"
                f"有効期限: {r.expires_at}\n"
                f"概算料金: [bold magenta]{r.estimated_cost or '要確認'}[/bold magenta]\n"
                f"ページ数: {r.page_count or '未取得'} | カラー設定: {r.color_mode}\n"
                f"操作案内: {r.details}"
            )
            if r.qr_code_path:
                panel_content += f"\nQRコード画像: {r.qr_code_path}"
            console.print(Panel(panel_content, border_style="green"))

            # ターミナルへQRコードを直接ASCII描画
            try:
                import qrcode
                import io
                qr = qrcode.QRCode(border=1)
                qr.add_data(r.print_code)
                qr.make(fit=True)
                f = io.StringIO()
                qr.print_ascii(out=f, invert=True)
                console.print(f"[bold cyan]ターミナル用QRコード ({r.service_name}):[/bold cyan]")
                print(f.getvalue())
            except Exception:
                pass

class nullcontext:
    def __enter__(self):
        return None
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

@cli.command("clean")
@click.option("--dir", "-d", "target_dir", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".", help="クリーンアップ対象ディレクトリ")
def clean_command(target_dir: Path):
    """生成されたQRコード画像や一時ファイルを一括削除します。"""
    count = 0
    for pattern in ["*_qr.png", "debug_*.png"]:
        for file in target_dir.glob(pattern):
            try:
                file.unlink()
                count += 1
            except Exception:
                pass
    console.print(f"[bold green]{count} 個の一時ファイルをクリーンアップしました。[/bold green]")

@cli.command("setup-claude")
def setup_claude_command():
    """Claude Desktop 用の MCP 設定スニペットを表示します。"""
    import sys
    cfg = {
        "mcpServers": {
            "netprintconnect": {
                "command": sys.executable,
                "args": ["-m", "netprintconnect.mcp_server"]
            }
        }
    }
    console.print("[bold cyan]以下のJSONを claude_desktop_config.json の \"mcpServers\" に追加してください:[/bold cyan]\n")
    print(json.dumps(cfg, indent=2))

@cli.command("server")
def server_command():
    """MCP (Model Context Protocol) サーバーとして起動します。"""
    from .mcp_server import run_mcp_server
    run_mcp_server()

def main():
    cli()

if __name__ == "__main__":
    main()
