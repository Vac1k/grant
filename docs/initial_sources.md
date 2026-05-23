# Початкові джерела грантів

Цей документ містить тільки інформацію про джерела грантів і рекомендований спосіб отримання даних з них.

## Статус По Наданих URL

Ця таблиця відповідає саме на питання: чи додано connector для кожного URL із початкового списку.

| Наданий URL | Source slug | Connector status | Фактична стратегія | Коментар |
|---|---|---|---|---|
| `https://www.prostir.ua/category/grants/` | `prostir` | Реалізовано | RSS discovery + HTML detail pages | Connector працює не через scraping category page напряму, а через RSS/category feed і detail HTML. |
| `https://gurt.org.ua/news/grants/` | `gurt` | Реалізовано локально, але не production-validated | HTML list + HTML detail pages | Connector існує, але live validation блокується Cloudflare/human-check. Bypass не робимо. |
| `https://grant.market/` | `grant-market` | Реалізовано | Sitemap `/opp/` + HTML detail pages | Connector читає `https://grant.market/sitemap.xml` і бере тільки direct opportunity URLs із `/opp/`. |
| `https://chaszmin.com.ua/` | `chas-zmin` | Реалізовано | WordPress REST + RSS fallback | Використовується WP REST search за grant-like terms. |
| `https://www.grantsense.com.ua/grants2025` | `grantsense` | Deferred | Не додано connector | Перевірка показала Next.js error shell / службові або категорійні сторінки без стабільного direct opportunity feed. |
| `https://eufundingportal.eu/` | `eufundingportal-eu` | Реалізовано | WordPress REST + RSS fallback | Aggregator source; має duplicate risk із official EU Funding source, тому потребує manual review. |
| `https://business.diia.gov.ua/finance/programs/finance` | `diia-business` | Реалізовано | Public frontend API | Connector не scrape-ить цей HTML URL напряму, а використовує структурований frontend API `https://api.business.diia.gov.ua/api/front/finance`. |
| `https://www.fundsforngos.org` | `fundsforngos` | Реалізовано через equivalent working host | WordPress REST + RSS fallback | Робочий WP REST endpoint знаходиться на `https://www2.fundsforngos.org/`; цей host використано в seed/connector. |
| `https://opportunitydesk.org` | `opportunitydesk` | Реалізовано | WordPress REST + category filter + digest filter | Використовується category `Awards and Grants`; digest/list posts відкидаються. |
| `https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/home` | `eu-funding` | Реалізовано | Official/API-style EU search endpoint | HTML portal не scrape-иться; connector використовує EU search API endpoint. |
| `https://www.grantforward.com/search` | `grantforward` | Deferred / restricted | Не додано connector | Search page доступна, але WP REST/RSS/sitemap повертають `404`, HTML не має direct result links без JS/search flow, є login/subscription mechanics. |
| `https://www.fundsforngos.org/` | `fundsforngos` | Реалізовано через equivalent working host | WordPress REST + RSS fallback | Дубль попереднього fundsforNGOs URL; production connector налаштований на `https://www2.fundsforngos.org/`. |
| `https://nipo.gov.ua/dajdzhest-1-kvartal-2025/` | `nipo` | Частково реалізовано на рівні домену | WordPress REST + RSS fallback | Connector є для `nipo.gov.ua`, але конкретна digest-сторінка не є окремим source. Для Step 9 додано розширені search terms (`SME Fund`, `премія`, `відбір`, `фінансування`, `відшкодування`), бо джерело має високий news/digest noise. NIPO results позначаються `needs_manual_review`. |
| `https://hromady.org/41049-2/` | `hromady` | Частково реалізовано на рівні домену | WordPress REST + RSS fallback | Connector є для `hromady.org`, але конкретна сторінка `41049-2` не є окремим source. |

Підсумок:

- робочі connectors: `prostir`, `grant-market`, `chas-zmin`, `eufundingportal-eu`, `diia-business`, `fundsforngos`, `opportunitydesk`, `eu-funding`, `nipo`, `hromady`;
- connector є, але production validation заблокована: `gurt`;
- не додано як робочі connectors після перевірки: `grantsense`, `grantforward`;
- `fundsforngos.org` і `www.fundsforngos.org` об'єднані в один source `fundsforngos`, але технічно використовується working host `www2.fundsforngos.org`.

## MVP-джерела

| Джерело | URL | Найкращий поточний доступ | Коментар |
|---|---|---|---|
| EU Funding & Tenders Portal | `https://ec.europa.eu/info/funding-tenders/opportunities/portal/` | API | Найбільш структуроване джерело. Поточний connector використовує `https://api.tech.ec.europa.eu/search-api/prod/rest/search` з `apiKey=SEDIA`. HTML scraping для цього джерела не потрібен. |
| Prostir | `https://www.prostir.ua/category/grants/` | RSS + HTML detail pages | RSS підходить для пошуку нових записів. HTML detail pages потрібні для повного тексту, дедлайнів, умов участі, документів і сум фінансування. |
| Diia Business | `https://www.business.diia.gov.ua/finance/programs` | Public frontend API | Краще використовувати `https://api.business.diia.gov.ua/api/front/finance`, бо це структурованіше за HTML/sitemap. Sitemap і HTML можна залишати тільки як fallback. |
| GURT | `https://gurt.org.ua/news/grants/` | HTML list + HTML detail pages, але live access блокується Cloudflare | Це правильний grants URL для ГУРТ. Connector уже існує як MVP source `gurt`, але production validation блокується Cloudflare/human-check. |

## Додаткові джерела для перевірки

| Джерело | URL | Потенційний доступ | Коментар |
|---|---|---|---|
| Grant Market | `https://grant.market/` | Sitemap + HTML | Реалізовано у Step 4.2. Connector читає `https://grant.market/sitemap.xml`, бере тільки `/opp/` URL-и і парсить HTML detail pages. |
| Chas Zmin | `https://chaszmin.com.ua/` | WordPress REST API або RSS | Реалізовано у Step 4.1 через WP REST primary і RSS fallback. |
| GrantSense | `https://grantsense.com.ua/` | Deferred | У Step 4.2 не додано як робочий connector. Sitemap доступний, але перевірені сторінки повертають Next.js error shell або службові/категорійні/blog-сторінки без стабільного списку прямих грантових можливостей. |
| EUFundingPortal.eu | `https://eufundingportal.eu/` | WordPress REST API або RSS | Реалізовано у Step 4.1 як aggregator source. Це не офіційний EU Funding & Tenders Portal і має duplicate risk із official EU source. |
| fundsforNGOs | `https://www2.fundsforngos.org/` | WordPress REST API | Реалізовано у Step 4.2 через WP REST search. Джерело широке і міжнародне, тому normalized grants позначаються як `needs_manual_review`. |
| Opportunity Desk | `https://www.opportunitydesk.org/` | WordPress REST API або RSS | Реалізовано у Step 4.3 через WP REST search з category filter `Awards and Grants`. Джерело широке, тому digest/list posts відкидаються, а normalized grants позначаються як `needs_manual_review`. |
| GrantForward | `https://www.grantforward.com/` | Deferred / restricted HTML | У Step 4.3 не додано як робочий connector. Search page доступна, але WP REST/RSS/sitemap повертають `404`, HTML не містить direct result links без JS/search flow, а сайт має login/subscription mechanics. |
| NIPO | `https://nipo.gov.ua/` | WordPress REST API або RSS | Реалізовано у Step 4.2 через WP REST search. У Step 9 розширено search terms, щоб добрати достатньо прямих grant-like records для quality gate. Джерело може містити дайджести або новини, тому normalized grants позначаються як `needs_manual_review`. |
| Hromady | `https://hromady.org/` | WordPress REST API або RSS | Реалізовано у Step 4.1 через WP REST primary і RSS fallback для громад і локального розвитку. |
