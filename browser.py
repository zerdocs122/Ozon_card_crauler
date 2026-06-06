import asyncio
import random

from extractor import normalize_eval


async def random_delay(min_sec: float = 1.5, max_sec: float = 3.5) -> None:
    """Случайная пауза для имитации живого пользователя."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


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


async def wait_for_products(tab, timeout_sec: float = 20.0) -> bool:
    """Ждёт появления ссылок на товары в выдаче."""
    deadline = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        count = normalize_eval(
            await tab.evaluate(
                "document.querySelectorAll('a[href*=\"/product/\"]').length",
                return_by_value=True,
            )
        )
        if isinstance(count, int) and count > 0:
            return True
        await asyncio.sleep(0.5)
    return False
