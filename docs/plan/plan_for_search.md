# План Для Search / Link Extraction

## Призначення Файлу

Цей файл використовується для відкритих пунктів великого Stage Search.

Поточний стан: відкритих implementation steps для Stage Search немає.

Усі виконані пункти перенесені в `implemented_for_search.md`.

## Великий Stage Search

Статус: завершено.

Дата закриття: `2026-05-24`.

Stage Search / Link Extraction закритий, бо виконані початкові вимоги:

1. Логіку розширено на всі надані сайти, а не лише на 4 MVP-джерела.
2. Кожен сайт проаудитований і має documented extraction decision.
3. Для кожного implementable сайту створено source-specific connector.
4. Реалізовано уніфікований контракт `discover -> fetch_detail -> normalize`.
5. Створено standardized initial discovery table `discovered_grant_items`.
6. `raw_grant_snapshots` використовується для raw detail payload, а не як бізнес-таблиця пошуку.
7. Search stage збирає релевантні grant-like opportunities без active-only фільтра.
8. Incremental mode перечитує listing/API/search endpoint і додає тільки нові item-level grants.
9. Для кожного implementable джерела, крім `gurt`, у `grants` є мінімум 10 quality-approved records.
10. `gurt` закритий documented Cloudflare/human-check limitation без bypass.
11. `grantsense` закритий documented deferred/blocked reason.
12. `grantforward` реалізований через public search AJAX endpoint із documented login-only detail limitation.

## Закриті Джерела

Реалізовані джерела:

- `eu-funding`;
- `prostir`;
- `diia-business`;
- `chas-zmin`;
- `eufundingportal-eu`;
- `hromady`;
- `nipo`;
- `grant-market`;
- `fundsforngos`;
- `opportunitydesk`;
- `grantforward`.

Закриті як restricted/deferred:

- `gurt` - правильний grants URL блокується Cloudflare/human-check;
- `grantsense` - немає стабільного public direct opportunity feed/API.

## Поточний Plan State

Немає відкритих пунктів для Stage Search.

Цей файл не містить roadmap; він тільки фіксує, що для Stage Search не залишилось відкритих пунктів.
