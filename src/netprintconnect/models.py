from dataclasses import dataclass
from typing import Optional

@dataclass
class PrintJobResult:
    service: str                # "networkprint" (Lawson/FamilyMart) or "seven" (Seven-Eleven)
    service_name: str           # 人間向けの名称
    file_name: str              # ファイル名
    print_code: str             # 予約番号 / ユーザー番号
    expires_at: Optional[str]   # 有効期限
    page_count: Optional[str] = None    # ページ数 / 枚数
    color_mode: Optional[str] = None    # カラーモード
    estimated_cost: Optional[str] = None # 概算料金
    qr_code_path: Optional[str] = None  # QRコード画像が保存されたパス（任意）
    details: Optional[str] = None       # 追加補足情報
