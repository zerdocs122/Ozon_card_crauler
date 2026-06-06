import asyncio
import random
from datetime import datetime
from urllib.parse import quote_plus

import nodriver

from config import OZON_SEARCH_URL, MAX_RESULTS, MAX_PAGES
from browser import random_delay, dismiss_cookie_banner, wait_for_products
from extractor import extract_skus_from_tab


def build_result(
    query: str,
    sku: str,
    position: int | str,
    page: int | None,
    total_checked: int,
) -> dict:
    return {
        "query": query,
        "sku": sku,
        "position": position,
        "page": page,
        "total_checked": total_checked,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


async def _search_pages(
    browser,
    sku: str,
    query: str,
    debug_screenshot: bool,
) -> tuple[int | None, int | None, int]:
    """Перебирает страницы выдачи и ищет артикул.

    Возвращает (position, page, total_checked).
    """
    total_checked = 0

    for page_num in range(1, MAX_PAGES + 1):
        if total_checked >= MAX_RESULTS:
            break

        url = OZON_SEARCH_URL.format(query=quote_plus(query), page=page_num)
        print(f"  → Загружаем страницу {page_num}: {url}")

        tab = await browser.get(url)

        await dismiss_cookie_banner(tab)
        if not await wait_for_products(tab):
            print(f"  ✗ Товары не найдены на странице {page_num}, останавливаемся")
            if debug_screenshot:
                screenshot_path = f"debug_page_{page_num}.png"
                await tab.save_screenshot(screenshot_path)
                print(f"  Скриншот: {screenshot_path}")
            break

        for _ in range(5):
            await tab.scroll_down(random.randint(300, 500))
            await asyncio.sleep(random.uniform(0.3, 0.7))

        await random_delay(0.5, 1.0)

        if debug_screenshot:
            screenshot_path = f"debug_page_{page_num}.png"
            await tab.save_screenshot(screenshot_path)
            print(f"  Скриншот: {screenshot_path}")

        page_skus = await extract_skus_from_tab(tab)

        if not page_skus:
            print(f"  ✗ Товары не найдены на странице {page_num}, останавливаемся")
            break

        print(f"  ✓ Найдено {len(page_skus)} товаров на странице {page_num}")

        for product_sku in page_skus:
            if total_checked >= MAX_RESULTS:
                break
            total_checked += 1
            if product_sku == sku:
                print(f"  ★ Артикул {sku} найден на позиции {total_checked} (страница {page_num})")
                return total_checked, page_num, total_checked

        await random_delay()

    return None, None, total_checked


async def find_sku_position(
    query: str,
    sku: str,
    headless: bool = True,
    debug_screenshot: bool = False,
) -> dict:
    sku = str(sku).strip()

    browser = await nodriver.start(
        headless=headless,
        lang="ru-RU",
        browser_args=["--disable-blink-features=AutomationControlled"],
    )

    try:
        found_position, found_page, total_checked = await _search_pages(
            browser, sku, query, debug_screenshot
        )
    finally:
        browser.stop()

    if found_position is not None:
        return build_result(query, sku, found_position, found_page, total_checked)
    return build_result(query, sku, "not_found", None, total_checked)
