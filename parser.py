"""
Парсер позиций товаров в поисковой выдаче Ozon.
Определяет, на какой позиции (1–100) стоит товар с указанным артикулом.

Использует nodriver — библиотеку для управления реальным Chrome,
которая не обнаруживается антибот-системами (Cloudflare и др.).
"""

import json
import asyncio
import random
import argparse
import sys
from datetime import datetime
from urllib.parse import quote_plus, urlparse

import nodriver

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# --- Настройки ---
OZON_SEARCH_URL = "https://www.ozon.ru/search/?text={query}&page={page}"
PRODUCTS_PER_PAGE = 36  # Ozon показывает примерно 36 товаров на странице
MAX_RESULTS = 100
# Количество страниц, необходимых для охвата MAX_RESULTS товаров (= 3)
MAX_PAGES = (MAX_RESULTS + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE


async def random_delay(min_sec: float = 1.5, max_sec: float = 3.5) -> None:
    """Делает случайную асинхронную паузу — имитирует живого пользователя."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


def build_result(
    query: str,
    sku: str,
    position: int | str,
    page: int | None,
    total_checked: int,
) -> dict:
    """
    Формирует итоговый словарь с результатом поиска.

    Аргументы:
        query         — поисковый запрос, который использовался
        sku           — искомый артикул товара
        position      — найденная позиция (1–100) или строка "not_found"
        page          — номер страницы, где найден товар (None если не найден)
        total_checked — сколько товаров просмотрено в процессе поиска

    Возвращает словарь, готовый к сериализации в JSON.
    """
    return {
        "query": query,
        "sku": sku,
        "position": position,
        "page": page,
        "total_checked": total_checked,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


def normalize_eval(value):
    """Приводит результат tab.evaluate к обычным Python-типам."""
    if isinstance(value, dict):
        if "type" in value and "value" in value:
            return normalize_eval(value["value"])
        return {k: normalize_eval(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_eval(item) for item in value]
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    inner = getattr(value, "value", None)
    if inner is not None:
        return normalize_eval(inner)
    deep = getattr(value, "deep_serialized_value", None)
    if deep is not None and getattr(deep, "value", None) is not None:
        return normalize_eval(deep.value)
    return value


async def dismiss_cookie_banner(tab) -> None:
    """Закрывает баннер согласия на cookies, если он отображается."""
    js_code = """
        (() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            const ok = buttons.find(
                b => b.textContent.trim().toUpperCase() === 'OK'
            );
            if (ok) {
                ok.click();
                return true;
            }
            return false;
        })()
    """
    await tab.evaluate(js_code, return_by_value=True)


def sku_from_product_href(href: str) -> str | None:
    """
    Извлекает артикул из URL карточки Ozon.

    Пример: /product/termos-1539914758/?at=xxx -> 1539914758
    """
    path = urlparse(href).path.rstrip("/")
    if "/product/" not in path:
        return None
    slug = path.split("/product/", 1)[-1].split("/")[0]
    candidate = slug.rsplit("-", 1)[-1]
    return candidate if candidate.isdigit() else None


async def wait_for_products(tab, timeout_sec: float = 20.0) -> bool:
    """Ждёт появления ссылок на товары в выдаче."""
    deadline = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        count = normalize_eval(
            await tab.evaluate(
                'document.querySelectorAll(\'a[href*="/product/"]\').length',
                return_by_value=True,
            )
        )
        if isinstance(count, int) and count > 0:
            return True
        await asyncio.sleep(0.5)
    return False


async def extract_skus_from_tab(tab) -> list[str]:
    """
    Извлекает артикулы товаров с текущей страницы поиска.

    SKU извлекается прямо в JavaScript — так надёжнее, чем парсить
    href на стороне Python после nodriver.
    """
    js_code = """
        (() => {
            const seen = new Set();
            const skus = [];
            for (const link of document.querySelectorAll('a[href*="/product/"]')) {
                const href = link.getAttribute('href') || '';
                const match = href.match(/\\/product\\/[^/?]+-(\\d+)/);
                if (!match) continue;
                const sku = match[1];
                if (!seen.has(sku)) {
                    seen.add(sku);
                    skus.push(sku);
                }
            }
            return skus;
        })()
    """
    skus = normalize_eval(await tab.evaluate(js_code, return_by_value=True))

    if not isinstance(skus, list):
        return []

    return [str(sku) for sku in skus if str(sku).isdigit()]


async def find_sku_position(
    query: str,
    sku: str,
    headless: bool = False,
    debug_screenshot: bool = False,
) -> dict:
    """
    Основная функция: ищет товар по артикулу в поисковой выдаче Ozon.

    Алгоритм:
        1. Запускает реальный Chrome через nodriver
        2. Перебирает страницы выдачи (до 3 страниц = 100 товаров)
        3. На каждой странице прокручивает вниз для загрузки всех карточек
        4. Сравнивает каждый найденный артикул с искомым
        5. Возвращает позицию при первом совпадении

    Аргументы:
        query             — поисковый запрос (например, "термос")
        sku               — артикул товара на Ozon (например, "540109988")
        headless          — nodriver по умолчанию работает с видимым окном,
                            True включает фоновый режим (менее стабилен)
        debug_screenshot  — сохранять скриншот каждой страницы для отладки

    Возвращает словарь с результатом (см. функцию build_result).
    """
    sku = str(sku).strip()
    total_checked = 0
    found_position = None
    found_page = None

    # nodriver запускает реальный Chrome установленный на компьютере.
    # headless=False (по умолчанию) — окно видно, это помогает обойти
    # Cloudflare, который проверяет поведение браузера визуально.
    browser = await nodriver.start(
        headless=headless,
        lang="ru-RU",
        browser_args=[
            "--disable-blink-features=AutomationControlled",
        ],
    )

    try:
        for page_num in range(1, MAX_PAGES + 1):
            if total_checked >= MAX_RESULTS:
                break

            url = OZON_SEARCH_URL.format(
                query=quote_plus(query),
                page=page_num,
            )

            print(f"  → Загружаем страницу {page_num}: {url}")

            tab = await browser.get(url)

            await dismiss_cookie_banner(tab)
            if not await wait_for_products(tab):
                print(
                    f"  ✗ Товары не найдены на странице {page_num}, "
                    "останавливаемся"
                )
                if debug_screenshot:
                    screenshot_path = f"debug_page_{page_num}.png"
                    await tab.save_screenshot(screenshot_path)
                    print(f"  Скриншот: {screenshot_path}")
                break

            # Прокручиваем страницу для подгрузки lazy-loaded карточек
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
                print(
                    f"  ✗ Товары не найдены на странице {page_num}, "
                    "останавливаемся"
                )
                break

            count = len(page_skus)
            print(f"  ✓ Найдено {count} товаров на странице {page_num}")

            for product_sku in page_skus:
                if total_checked >= MAX_RESULTS:
                    break
                total_checked += 1
                if product_sku == sku:
                    found_position = total_checked
                    found_page = page_num
                    print(
                        f"  ★ Артикул {sku} найден на позиции "
                        f"{found_position} (страница {page_num})"
                    )
                    break

            if found_position is not None:
                break

            await random_delay()

    finally:
        # Закрываем браузер в любом случае — даже при ошибке
        browser.stop()

    if found_position is not None:
        return build_result(
            query, sku, found_position, found_page, total_checked
        )
    return build_result(query, sku, "not_found", None, total_checked)


def main() -> None:
    """Точка входа: разбирает аргументы командной строки и запускает поиск."""
    parser = argparse.ArgumentParser(
        description="Определяет позицию товара в поисковой выдаче Ozon"
    )
    parser.add_argument(
        "query",
        help='Поисковый запрос, например: "термос"',
    )
    parser.add_argument(
        "sku",
        help="Артикул товара на Ozon, например: 540109988",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Запустить браузер в фоне без окна. "
            "По умолчанию окно видно — так лучше обходится защита Ozon"
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Сохранять скриншот каждой страницы для отладки",
    )
    parser.add_argument(
        "--output",
        help="Сохранить результат в JSON-файл, например: result.json",
    )
    args = parser.parse_args()

    print(f'\nИщем на Ozon: "{args.query}", артикул: {args.sku}\n')

    # nodriver работает асинхронно — запускаем через asyncio
    result = nodriver.loop().run_until_complete(
        find_sku_position(
            query=args.query,
            sku=args.sku,
            headless=args.headless,
            debug_screenshot=args.debug,
        )
    )

    output = json.dumps(result, ensure_ascii=False, indent=2)
    print("\nРезультат:\n")
    print(output)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\nСохранено в {args.output}")


if __name__ == "__main__":
    main()
