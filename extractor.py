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


async def extract_skus_from_tab(tab) -> list[str]:
    """Извлекает артикулы товаров с текущей страницы поиска."""
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
