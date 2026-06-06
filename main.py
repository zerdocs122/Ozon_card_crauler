import json
import argparse
import sys

import nodriver

from searcher import find_sku_position

MSG_SEARCHING = "\nИщем на Ozon: \"{query}\", артикул: {sku}\n"
MSG_RESULT = "\nРезультат:\n"
MSG_SAVED = "\nСохранено в {path}"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Определяет позицию товара в поисковой выдаче Ozon"
    )
    parser.add_argument(
        "query",
        help="Поисковый запрос, например: \"термос\"",
    )
    parser.add_argument(
        "sku",
        help="Артикул товара на Ozon, например: 540109988",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        dest="show_browser",
        help="Показать окно браузера (по умолчанию работает в фоне без окна)",
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

    print(MSG_SEARCHING.format(query=args.query, sku=args.sku))

    result = nodriver.loop().run_until_complete(
        find_sku_position(
            query=args.query,
            sku=args.sku,
            headless=not args.show_browser,
            debug_screenshot=args.debug,
        )
    )

    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(MSG_RESULT)
    print(output)

    if args.output:
        try:
            with open(args.output, "r", encoding="utf-8") as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = [history]
        except (FileNotFoundError, json.JSONDecodeError):
            history = []
        history.append(result)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        print(MSG_SAVED.format(path=args.output))


if __name__ == "__main__":
    main()
