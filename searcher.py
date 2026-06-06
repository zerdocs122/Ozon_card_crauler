import asyncio
import random
from datetime import datetime
from urllib.parse import quote_plus

import nodriver

from config import OZON_SEARCH_URL, MAX_RESULTS, MAX_PAGES
from browser import random_delay, dismiss_cookie_banner, wait_for_products
from extractor import extract_skus_from_tab

SCROLL_STEPS = 5
SCROLL_MIN_PX = 300
SCROLL_MAX_PX = 500
SCROLL_STEP_DELAY_MIN = 0.3
SCROLL_STEP_DELAY_MAX = 0.7
POST_SCROLL_DELAY_MIN = 0.5
POST_SCROLL_DELAY_MAX = 1.0

MSG_LOADING_PAGE = "  → Загружаем страницу {page_num}: {url}"
MSG_NO_PRODUCTS = "  ✗ Товары не найдены на странице {page_num}, останавливаемся"
MSG_SCREENSHOT = "  Скриншот: {path}"
MSG_FOUND_COUNT = "  ✓ Найдено {count} товаров на странице {page_num}"
MSG_SKU_FOUND = "  ★ Артикул {sku} найден на позиции {position} (страница {page_num})"


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
    found_position = None
    found_page = None

    for page_num in range(1, MAX_PAGES + 1):
        if total_checked >= MAX_RESULTS:
            break

        url = OZON_SEARCH_URL.format(query=quote_plus(query), page=page_num)
        print(MSG_LOADING_PAGE.format(page_num=page_num, url=url))

        tab = await browser.get(url)

        await dismiss_cookie_banner(tab)
        if not await wait_for_products(tab):
            print(MSG_NO_PRODUCTS.format(page_num=page_num))
            if debug_screenshot:
                screenshot_path = f"debug_page_{page_num}.png"
                await tab.save_screenshot(screenshot_path)
                print(MSG_SCREENSHOT.format(path=screenshot_path))
            break

        for _ in range(SCROLL_STEPS):
            await tab.scroll_down(random.randint(SCROLL_MIN_PX, SCROLL_MAX_PX))
            await asyncio.sleep(random.uniform(SCROLL_STEP_DELAY_MIN, SCROLL_STEP_DELAY_MAX))

        await random_delay(POST_SCROLL_DELAY_MIN, POST_SCROLL_DELAY_MAX)

        if debug_screenshot:
            screenshot_path = f"debug_page_{page_num}.png"
            await tab.save_screenshot(screenshot_path)
            print(MSG_SCREENSHOT.format(path=screenshot_path))

        page_skus = await extract_skus_from_tab(tab)

        if not page_skus:
            print(MSG_NO_PRODUCTS.format(page_num=page_num))
            break

        print(MSG_FOUND_COUNT.format(count=len(page_skus), page_num=page_num))

        for product_sku in page_skus:
            if total_checked >= MAX_RESULTS:
                break
            total_checked += 1
            if product_sku == sku and found_position is None:
                found_position = total_checked
                found_page = page_num
                print(MSG_SKU_FOUND.format(sku=sku, position=found_position, page_num=page_num))

        await random_delay()

    return found_position, found_page, total_checked


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
