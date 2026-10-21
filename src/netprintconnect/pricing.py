"""料金計算ロジック"""

def estimate_cost(service: str, paper_size: str, color_mode: str | None, page_count_str: str | None) -> str:
    """
    コンビニ印刷の概算料金を算出
    """
    # ページ数パース (デフォルト1)
    pages = 1
    if page_count_str:
        import re
        m = re.search(r"(\d+)", page_count_str)
        if m:
            pages = int(m.group(1))

    is_mono = (color_mode or "").lower() in ["mono", "monochrome", "black", "bw", "白黒"]
    paper = (paper_size or "A4").upper()

    if service == "seven":
        # セブン-イレブン ネットプリント
        # 普通紙 白黒: 20円/枚 (全サイズ)
        # 普通紙 カラー: A4/B5/B4 60円/枚, A3 100円/枚
        # はがき: 白黒20円, カラー60円
        # L判写真: 40円, 2L判: 100円
        if "フォト" in paper or "写真" in paper or "L" in paper:
            unit = 40 if "2L" not in paper else 100
            return f"約{unit * pages}円 (写真用紙 {pages}枚)"
        if is_mono:
            return f"約{20 * pages}円 (白黒 {pages}枚 × 20円)"
        else:
            unit = 100 if paper == "A3" else 60
            return f"約{unit * pages}円 (カラー {pages}枚 × {unit}円)"
    else:
        # ネットワークプリント (ファミマ/ローソン等)
        # 普通紙 白黒: 20円/枚 (全サイズ)
        # 普通紙 カラー: A4/B5/B4 60円/枚, A3 100円/枚
        # L判写真: 30円, 2L判: 80円
        if "L" in paper and "フォト" in paper:
            unit = 30 if "2L" not in paper else 80
            return f"約{unit * pages}円 (写真用紙 {pages}枚)"
        if is_mono:
            return f"約{20 * pages}円 (白黒 {pages}枚 × 20円)"
        else:
            unit = 100 if paper == "A3" else 60
            return f"約{unit * pages}円 (カラー {pages}枚 × {unit}円)"
