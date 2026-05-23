# Початкові джерела грантів

Цей документ містить тільки інформацію про джерела грантів і рекомендований спосіб отримання даних з них.

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
| Grant Market | `https://grant.market/` | Sitemap + HTML | Публічний API не підтверджено. Потрібна окрема перевірка структури сторінок. |
| Chas Zmin | `https://chaszmin.com.ua/` | WordPress REST API або RSS | Реалізовано у Step 4.1 через WP REST primary і RSS fallback. |
| GrantSense | `https://grantsense.com.ua/` | Sitemap/list + HTML | Публічний API не підтверджено. |
| EUFundingPortal.eu | `https://eufundingportal.eu/` | WordPress REST API або RSS | Реалізовано у Step 4.1 як aggregator source. Це не офіційний EU Funding & Tenders Portal і має duplicate risk із official EU source. |
| fundsforNGOs | `https://www2.fundsforngos.org/` | WordPress REST API | Потенційно корисне міжнародне джерело. Потрібна перевірка доступу, rate limits і якості категоризації. |
| Opportunity Desk | `https://www.opportunitydesk.org/` | WordPress REST API або RSS | Потенційно корисне міжнародне джерело. Потрібна фільтрація, бо там не тільки grants. |
| GrantForward | `https://www.grantforward.com/` | Restricted HTML / possible paid access | Може потребувати акаунт або підписку. Не варто брати в MVP без окремої перевірки доступу. |
| NIPO | `https://nipo.gov.ua/` | WordPress REST API або RSS | Може бути корисним для українських digest/opportunity pages. Потрібна перевірка конкретних категорій. |
| Hromady | `https://hromady.org/` | WordPress REST API або RSS | Реалізовано у Step 4.1 через WP REST primary і RSS fallback для громад і локального розвитку. |
