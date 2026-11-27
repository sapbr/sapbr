# SAPBR Technologies: Brazil Tax Reform Calculator

Interactive calculator for Brazil's Tax Reform (CBS, IBS and the Selective Tax, IS) built on the Receita Federal's official open-source calculators. It compares today's ICMS, PIS and COFINS with the reform, product by product, under the regular regime or the Simples Nacional. Available in English (US) and Portuguese (BR); add `?lang=en` or `?lang=pt` to the URL.

Live: https://leandropia.github.io/sapbr/

## Official data, updated daily

A GitHub Actions workflow (`.github/workflows/publicar-calculadora.yml`) runs on every push and once a day. It downloads the official repositories, builds the official SQLite database from their Flyway scripts and exports `data.json` with `scripts/build_data.py`:

- [ReceitaFederal/calculadora-rtc-regime-regular](https://github.com/ReceitaFederal/calculadora-rtc-regime-regular): cClassTrib, CST, reduction percentages, tax treatment formulas, NCM links, Selective Tax NCMs and reference rates.
- [ReceitaFederal/calculadora-rtc-simples-nacional](https://github.com/ReceitaFederal/calculadora-rtc-simples-nacional): Simples Nacional rules (activities, annexes, revenue types and assessment regimes), stored in the same database.

When the Receita Federal publishes a new database version, the calculator picks it up on the next run.

## Scope

Regular regime: base = value − ICMS − PIS − COFINS + IS; effective rate from the official formula `aliquota*(1-percentualReducao)`; tax rounded half to even. Simples Nacional: gross revenue × revenue-type factor × effective PGDAS-D rate of the activity's annex. Single-phase fuel taxation, government purchases and special regimes are out of scope. Illustrative simulation; not tax advice.

Published by [SAPBR Technologies](https://sapbr.com).
