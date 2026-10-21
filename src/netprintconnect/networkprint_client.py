import re
from pathlib import Path
from playwright.async_api import Browser, async_playwright
from .models import PrintJobResult

async def upload_to_networkprint(
    file_path: str | Path,
    browser: Browser | None = None,
    save_qr: bool = True,
    paper_size: str = "A4",
    color_mode: str | None = None
) -> PrintJobResult:
    """
    ファミリーマート・ローソン・ポプラグループ・ミニストップ系
    SHARP ネットワークプリント（会員登録なし / Lite）へアップロード
    :param paper_size: 用紙サイズ (A4, B5, B4, A3 等)
    :param color_mode: カラーモード (白黒/カラーはコンビニマルチコピー機側でも選択可能)
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    # ファイルサイズ上限チェック (10MB)
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 10.0:
        raise ValueError(f"ファイルサイズが上限（10MB）を超えています: {size_mb:.2f}MB")

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
        # 1. 登録開始ページへアクセス
        await page.goto("https://networkprint.ne.jp/Lite/start?lang=jajp", timeout=60000, wait_until="domcontentloaded")
        
        # 2. 利用規約への同意
        agreement = page.locator("#agreement")
        await agreement.wait_for(state="attached", timeout=15000)
        await agreement.check(force=True)
        await page.wait_for_timeout(300)

        # 3. ファイルのアップロード
        file_inputs = await page.locator("input[type='file']").all()
        if not file_inputs:
            raise RuntimeError("NetworkPrint file input element was not found.")
        
        await file_inputs[0].set_input_files(str(path))

        # 4. アップロード後の画面遷移待ち（Lite/image または Lite/document または Lite/preview）
        await page.wait_for_url(re.compile(r"/Lite/(image|doc|start|preview)"), timeout=40000)
        await page.wait_for_timeout(1000)

        # 文書登録画面（/Lite/document）の場合、用紙サイズ選択（Vuetifyコンボボックス）で指定サイズ（デフォルトA4）を選択
        if "document" in page.url or await page.locator("text=文書プリントの登録").count() > 0:
            combobox = page.locator(".selectPaperSize .v-field").first
            if await combobox.count() > 0 and await combobox.is_visible():
                await combobox.click()
                await page.wait_for_timeout(600)
                target_size = paper_size.upper()
                option = page.locator(".v-overlay-container .v-list-item, [role='option']").filter(has_text=target_size).first
                if await option.count() > 0 and await option.is_visible():
                    await option.click()
                    await page.wait_for_timeout(600)

        # 確認画面（画像なら「そのまま登録」、文書なら「#registerButton」）をクリック
        register_btn = page.locator("#registerButton, input[value='ファイルを登録'], button:has-text('ファイルを登録'), button:has-text('そのまま登録'), a:has-text('そのまま登録')").first
        if await register_btn.count() > 0 and await register_btn.is_visible():
            await register_btn.click()
        
        # 登録完了画面（/Lite/preview）への遷移待ち
        await page.wait_for_url("**/Lite/preview**", wait_until="commit", timeout=40000)
        await page.wait_for_timeout(2000)

        # 5. ユーザー番号・有効期限・QRコードの抽出
        body_text = await page.locator("body").inner_text()
        
        # ユーザー番号抽出（英数字10桁）
        # 「ユーザー番号」の次の行に表示される
        user_code = None
        code_match = re.search(r"ユーザー番号\s*\n+([A-Z0-9]{10})", body_text)
        if code_match:
            user_code = code_match.group(1).strip()
        else:
            # 汎用パターン
            m = re.search(r"\b([A-Z0-9]{10})\b", body_text)
            if m:
                user_code = m.group(1).strip()

        if not user_code:
            raise RuntimeError("Failed to retrieve user number from NetworkPrint preview page.")

        # 有効期限の抽出 (例: 2026-10-29 13時頃まで)
        expires_at = None
        exp_match = re.search(r"(\d{4}-\d{2}-\d{2}\s*\d{1,2}時[^\n]*)", body_text)
        if exp_match:
            expires_at = exp_match.group(1).strip()

        # QRコードの取得（任意）
        qr_path = None
        if save_qr:
            try:
                qr_btn = page.get_by_text("QRコードを表示").first
                if await qr_btn.count() > 0 and await qr_btn.is_visible():
                    await qr_btn.click()
                    await page.wait_for_timeout(1000)

                    # 本物のQRコードは blob: URL または 150px 以上の正方形画像
                    # （モーダルの閉じる×アイコンなどの誤取得を防ぐ）
                    target_img = None
                    blob_imgs = await page.locator("img[src^='blob:']").all()
                    for img in blob_imgs:
                        if await img.is_visible():
                            box = await img.bounding_box()
                            if box and box["width"] >= 100 and box["height"] >= 100:
                                target_img = img
                                break

                    if not target_img:
                        # フォールバック: 画面上の大きな可視画像を探索
                        all_imgs = await page.locator("img").all()
                        for img in all_imgs:
                            if await img.is_visible():
                                box = await img.bounding_box()
                                if box and box["width"] >= 150 and box["height"] >= 150:
                                    target_img = img
                                    break

                    if target_img:
                        dest = path.parent / f"{path.stem}_{user_code}_qr.png"
                        await target_img.screenshot(path=str(dest))
                        qr_path = str(dest)
            except Exception:
                pass

        await page.close()

        from .pricing import estimate_cost
        cost = estimate_cost("networkprint", paper_size or "A4", color_mode, None)

        return PrintJobResult(
            service="networkprint",
            service_name="ネットワークプリント (ファミマ/ローソン/ポプラ/ミニストップ)",
            file_name=path.name,
            print_code=user_code,
            expires_at=expires_at,
            page_count=None,
            color_mode=color_mode or "店舗選択",
            estimated_cost=cost,
            qr_code_path=qr_path,
            details="マルチコピー機で「ネットワークプリント」を選択し、ユーザー番号を入力してください。"
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
