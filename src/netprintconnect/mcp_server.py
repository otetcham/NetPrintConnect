import asyncio
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from .networkprint_client import upload_to_networkprint
from .seven_client import upload_to_seven

mcp = FastMCP("netprintconnect-server")

@mcp.tool()
async def upload_document_for_print(
    file_path: str,
    target: str = "all",
    paper_size: str = "A4",
    color_mode: str | None = None,
    pin: str | None = None,
    save_qr: bool = True,
    user_id: str | None = None,
    password: str | None = None
) -> str:
    """
    指定したPDF・画像等のファイルをコンビニ印刷（ネットワークプリント / ネットプリント）にヘッドレスでアップロードし、
    店舗マルチコピー機で入力する予約番号・ユーザー番号を発行します。

    :param file_path: アップロードするファイルの絶対パスまたは相対パス (PDF, JPG, PNG等)
    :param target: 対象サービス ('all': 両方, 'seven': セブン-イレブン, 'networkprint': ファミマ/ローソン等)
    :param paper_size: 用紙サイズ ('A4', 'B5', 'B4', 'A3') デフォルトは'A4'
    :param color_mode: カラー設定 ('color': カラー, 'mono': 白黒)
    :param pin: 暗証番号 (数字4桁、セブン-イレブン対応)
    :param save_qr: QRコード画像をファイルと同じディレクトリに保存するかどうか
    :param user_id: 会員ID/メールアドレス (未指定時はゲスト利用)
    :param password: 会員パスワード
    """
    import os
    path = Path(file_path).resolve()
    if not path.exists():
        return f"エラー: 指定されたファイルが見つかりません: {file_path}"

    results = []
    errors = []

    if target in ["all", "networkprint"]:
        try:
            np_user = user_id or os.environ.get("NETWORKPRINT_USER")
            np_pass = password or os.environ.get("NETWORKPRINT_PASSWORD")
            res_np = await upload_to_networkprint(path, save_qr=save_qr, paper_size=paper_size, color_mode=color_mode, user_id=np_user, password=np_pass)
            results.append(
                f"【{res_np.service_name}】\n"
                f"・ユーザー番号: {res_np.print_code}\n"
                f"・用紙サイズ: {paper_size}\n"
                f"・概算料金: {res_np.estimated_cost or '要確認'}\n"
                f"・有効期限: {res_np.expires_at}\n"
                f"・案内: {res_np.details}\n" +
                (f"・QRコード画像: {res_np.qr_code_path}\n" if res_np.qr_code_path else "")
            )
        except Exception as e:
            errors.append(f"ネットワークプリント (ファミマ/ローソン) アップロード失敗: {e}")

    if target in ["all", "seven"]:
        try:
            seven_user = user_id or os.environ.get("SEVEN_USER")
            seven_pass = password or os.environ.get("SEVEN_PASSWORD")
            res_seven = await upload_to_seven(path, save_qr=save_qr, paper_size=paper_size, color_mode=color_mode, pin=pin, user_id=seven_user, password=seven_pass)
            results.append(
                f"【{res_seven.service_name}】\n"
                f"・プリント予約番号: {res_seven.print_code}\n"
                f"・用紙サイズ: {paper_size}\n"
                f"・ページ数: {res_seven.page_count or '1'}\n"
                f"・概算料金: {res_seven.estimated_cost or '要確認'}\n"
                f"・有効期限: {res_seven.expires_at}\n" +
                (f"・暗証番号: {pin}\n" if pin else "") +
                f"・案内: {res_seven.details}\n" +
                (f"・QRコード画像: {res_seven.qr_code_path}\n" if res_seven.qr_code_path else "")
            )
        except Exception as e:
            errors.append(f"セブン-イレブン ネットプリント アップロード失敗: {e}")

    output_lines = []
    if results:
        output_lines.append("アップロードが完了し、印刷用番号が発行されました：\n")
        output_lines.extend(results)
    if errors:
        output_lines.append("\n一部エラーが発生しました：")
        output_lines.extend(errors)

    return "\n".join(output_lines)

def run_mcp_server():
    mcp.run()

if __name__ == "__main__":
    run_mcp_server()
