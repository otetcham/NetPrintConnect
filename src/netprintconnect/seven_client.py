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
    pin: str | None = None,
    user_id: str | None = None,
    password: str | None = None
) -> PrintJobResult:
    """
    セブン-イレブン ネットプリントへアップロード（会員ログインまたはゲスト/かんたんnetprint）
    :param paper_size: 用紙サイズ ('A4', 'B5', 'B4', 'A3', 'フォト用紙 L', 'はがき' 等)
    :param color_mode: カラーモード ('color': カラー, 'mono': 白黒)
    :param pin: 暗証番号（数字4桁）
    :param user_id: 会員ユーザーID / メールアドレス
    :param password: 会員パスワード
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

        # ==================== 会員ログインモード ====================
        if user_id and password:
            await page.goto("https://www.printing.ne.jp/usr/web/NPCM0010.seam", timeout=60000, wait_until="domcontentloaded")
            await page.locator("input[name='NPCM0010:userIdOrMailads-txt']").fill(user_id)
            await page.locator("input[name='NPCM0010:password-pwd']").fill(password)
            await page.locator("input[name='NPCM0010:login-btn']").click()
            await page.wait_for_timeout(2000)

            # 認証エラー判定
            body_text = await page.locator("body").inner_text()
            if "NPCM0010.seam" in page.url or "ログインできません" in body_text or "正しくありません" in body_text:
                error_elem = page.locator(".errorMessage, .errors, [class*='error']")
                err_detail = "ユーザーIDまたはパスワードをご確認ください。"
                if await error_elem.count() > 0:
                    err_detail = (await error_elem.first.inner_text()).strip()
                raise RuntimeError(f"ネットプリント(セブン)のログインに失敗しました: {err_detail}")

            # ログイン後、普通紙プリント登録画面へ遷移
            # メニューリンクから「普通紙プリント登録」をクリック
            reg_link = page.locator("a:has-text('普通紙プリント'), a:has-text('文書プリント')").first
            if await reg_link.count() > 0:
                await reg_link.click()
                await page.wait_for_timeout(1000)

            file_input = page.locator("input[type='file']").first
            if await file_input.count() > 0:
                await file_input.set_input_files(str(path))
                await page.wait_for_timeout(1000)

            # 登録ボタン
            sub_btn = page.locator("input[type='submit'][value*='登録'], button:has-text('登録')").first
            if await sub_btn.count() > 0:
                await sub_btn.click()
                await page.wait_for_timeout(2000)

            # 予約番号の抽出
            page_t = await page.locator("body").inner_text()
            code = None
            code_m = re.search(r"プリント予約番号[：:]\s*([A-Z0-9]{8})", page_t)
            if code_m:
                code = code_m.group(1).strip()
            else:
                m = re.search(r"\b([A-Z0-9]{8})\b", page_t)
                if m:
                    code = m.group(1).strip()

            from .pricing import estimate_cost
            cost = estimate_cost("seven", paper_size or "A4", color_mode, None)

            return PrintJobResult(
                service="seven",
                service_name="ネットプリント (セブン-イレブン・会員)",
                file_name=path.name,
                print_code=code or "会員マイページ登録済",
                expires_at="最長7日間 (会員有効期限)",
                page_count=None,
                color_mode=color_mode or "店舗選択",
                estimated_cost=cost,
                qr_code_path=None,
                details="セブン-イレブンのマルチコピー機で「ネットプリント」を選び、予約番号を入力してください。"
            )

        # ==================== ゲストモード (かんたんnetprint) ====================
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
                close_modal_btn = page.locator("button:has-text('閉じる')").first
                if await close_modal_btn.count() > 0 and await close_modal_btn.is_visible():
                    await close_modal_btn.click()
                    await page.wait_for_timeout(500)

                # 「コンビニでプリントする」ボタンを押すと別タブ（/web/qr）が開く
                show_qr_btn = page.locator("button:has-text('コンビニでプリントする')").first
                if await show_qr_btn.count() > 0 and await show_qr_btn.is_visible():
                    async with context.expect_page(timeout=10000) as new_page_info:
                        await show_qr_btn.click()
                    qr_page = await new_page_info.value
                    await qr_page.wait_for_load_state("domcontentloaded")
                    await qr_page.wait_for_timeout(1000)

                    # QRコード画像 (blob: URL または 100px以上の正方形画像)
                    target_img = None
                    blob_imgs = await qr_page.locator("img[src^='blob:']").all()
                    for img in blob_imgs:
                        if await img.is_visible():
                            box = await img.bounding_box()
                            if box and box["width"] >= 100 and box["height"] >= 100:
                                target_img = img
                                break

                    if not target_img:
                        for img in await qr_page.locator("img").all():
                            if await img.is_visible():
                                box = await img.bounding_box()
                                if box and box["width"] >= 150 and box["height"] >= 150:
                                    target_img = img
                                    break

                    if target_img:
                        dest = path.parent / f"{path.stem}_{code}_qr.png"
                        await target_img.screenshot(path=str(dest))
                        qr_path = str(dest)

                    await qr_page.close()
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
