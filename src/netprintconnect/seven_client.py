import re
from pathlib import Path
from playwright.async_api import Browser, async_playwright
from .models import PrintJobResult

async def upload_to_seven(
    file_path: str | Path,
    browser: Browser | None = None,
    save_qr: bool = True,
    paper_size: str | None = None,
    color_mode: str | None = None,
    pin: str | None = None
) -> PrintJobResult:
    """
    セブン-イレブン かんたんnetprint（会員登録不要）へアップロード
    :param paper_size: 用紙サイズ ('A4', 'B5', 'B4', 'A3', 'フォト用紙 L', 'はがき' 等)
    :param color_mode: カラーモード ('color': カラー, 'mono': 白黒)
    :param pin: 暗証番号（数字4桁）
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    # ファイルサイズ上限チェック (10MB)
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 10.0:
        raise ValueError(f"ファイルサイズが上限（10MB）を超えています: {size_mb:.2f}MB")

    # 暗証番号バリデーション
    if pin is not None and not re.match(r"^\d{4}$", str(pin).strip()):
        raise ValueError("暗証番号 (PIN) は半角数字4桁で指定してください。")

    own_playwright = None
    own_browser = None
    context = None
    
    if browser is None:
        own_playwright = await async_playwright().start()
        own_browser = await own_playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        active_browser = own_browser
    else:
        active_browser = browser

    try:
        context = await active_browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            locale="ja-JP"
        )
        page = await context.new_page()
        # 1. かんたんnetprint Webページへアクセス
        await page.goto("https://lite.printing.ne.jp/web", timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(500)

        # 2. 利用規約チェックボックスにチェック
        checkbox = page.locator("input[type='checkbox']").first
        await checkbox.wait_for(state="attached", timeout=10000)
        await checkbox.check(force=True)
        await page.wait_for_timeout(300)

        # 3. ファイル選択
        file_input = page.locator("input[type='file']").first
        await file_input.set_input_files(str(path))
        await page.wait_for_timeout(1000)

        ext = path.suffix.lower()
        target_size = paper_size.upper() if paper_size else None

        # 用紙サイズ指定
        if target_size:
            size_label = page.locator(f"label:has-text('{target_size}'), span:has-text('{target_size}')").first
            if await size_label.count() > 0 and await size_label.is_visible():
                await size_label.click()
                await page.wait_for_timeout(300)
        elif ext in [".jpg", ".jpeg", ".png"]:
            try:
                from PIL import Image
                with Image.open(path) as img:
                    w, h = img.size
                    ratio = max(w, h) / min(w, h)
                    if ratio < 1.25 or ratio > 1.55:
                        a4_label = page.locator("label:has-text('普通紙　A4'), span:has-text('普通紙　A4')").first
                        if await a4_label.count() > 0 and await a4_label.is_visible():
                            await a4_label.click()
                            await page.wait_for_timeout(300)
            except Exception:
                pass

        # カラーモード指定 ('color' または 'mono')
        if color_mode:
            c_label_text = "白黒" if color_mode.lower() in ["mono", "monochrome", "black", "bw"] else "カラー"
            c_label = page.locator(f"label:has-text('{c_label_text}'), span:has-text('{c_label_text}')").first
            if await c_label.count() > 0 and await c_label.is_visible():
                await c_label.click()
                await page.wait_for_timeout(300)

        # 暗証番号指定（4桁数字）
        if pin and re.match(r"^\d{4}$", str(pin)):
            pin_radio = page.locator("label:has-text('設定する')").first
            if await pin_radio.count() > 0 and await pin_radio.is_visible():
                await pin_radio.click()
                await page.wait_for_timeout(300)
                pin_input = page.locator("input[type='password'], input[maxlength='4']").first
                if await pin_input.count() > 0 and await pin_input.is_visible():
                    await pin_input.fill(str(pin))
                    await page.wait_for_timeout(300)

        # 4. 「登録する」ボタンをクリック
        register_btn = page.locator("button:has-text('登録する')").first
        await register_btn.wait_for(state="visible", timeout=10000)
        await register_btn.click()

        # 5. 結果画面 (/web/result) への遷移待ち
        await page.wait_for_url("**/web/result**", wait_until="commit", timeout=60000)

        # 6. 発行完了（ポーリング待機）
        code = None
        expires_at = None
        page_count = None

        for _ in range(30):
            await page.wait_for_timeout(1000)
            text = await page.locator("body").inner_text()
            
            # プリント予約番号：XXXXXXXX
            code_match = re.search(r"プリント予約番号[：:]\s*([A-Z0-9]{8})", text)
            if code_match:
                code = code_match.group(1).strip()
                
                exp_match = re.search(r"有効期限[：:]\s*([0-9/\s:]+)", text)
                if exp_match:
                    expires_at = exp_match.group(1).strip()

                page_match = re.search(r"(\d+枚)", text)
                if page_match:
                    page_count = page_match.group(1).strip()
                break

            if "受付中" not in text and "エラー" in text:
                raise RuntimeError(f"Netprint returned an error during processing: {text[:200]}")

        if not code:
            raise RuntimeError("Timed out waiting for Netprint reservation code.")

        # QRコードの取得（任意）
        qr_path = None
        if save_qr:
            try:
                # アップロード完了ポップアップ（モーダル）が表示されている場合、閉じるボタンをクリック
                close_modal_btn = page.locator("button:has-text('閉じる'), .ReactModalPortal button").first
                if await close_modal_btn.count() > 0 and await close_modal_btn.is_visible():
                    await close_modal_btn.click()
                    await page.wait_for_timeout(500)

                # 「コンビニでプリントする」ボタンを押すとQRコードが表示される
                show_qr_btn = page.locator("button:has-text('コンビニでプリントする')").first
                if await show_qr_btn.count() > 0 and await show_qr_btn.is_visible():
                    await show_qr_btn.click(force=True, timeout=5000)
                    await page.wait_for_timeout(800)
                    qr_canvas_or_img = page.locator("canvas, img[alt*='QR'], img[src*='data:image']").first
                    if await qr_canvas_or_img.count() > 0 and await qr_canvas_or_img.is_visible():
                        dest = path.parent / f"{path.stem}_{code}_qr.png"
                        await qr_canvas_or_img.screenshot(path=str(dest))
                        qr_path = str(dest)
            except Exception:
                # QRコード取得に失敗しても予約番号自体は保持して正常終了する
                pass

        await page.close()

        from .pricing import estimate_cost
        cost = estimate_cost("seven", paper_size or "A4", color_mode, page_count)

        return PrintJobResult(
            service="seven",
            service_name="ネットプリント (セブン-イレブン)",
            file_name=path.name,
            print_code=code,
            expires_at=expires_at,
            page_count=page_count,
            color_mode=color_mode or "店舗選択",
            estimated_cost=cost,
            qr_code_path=qr_path,
            details="セブン-イレブンのマルチコピー機で「プリント」→「ネットプリント」を選び、8桁の予約番号を入力してください。"
        )

    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass
        if own_browser:
            await own_browser.close()
        if own_playwright:
            await own_playwright.stop()
