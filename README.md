# graylog-checks

Monitoring checks for [Graylog](https://www.graylog.org/), for two different
monitoring systems — each a standalone, native implementation, not a wrapper
around the other. Both were developed and verified live against a real
Graylog instance (7.1.3) set up via Docker Compose, not just assembled from
documentation.

## Structure

```
graylog-checks/
├── GRAYLOG-CONCEPTS.html   # What the measured values actually mean (journal, cluster health, ...),
│                           # written for readers with no prior Graylog knowledge -- applies to both variants
├── openapi.json            # Graylog REST API specification (OpenAPI 3.1, Graylog 7.1.3), used to
│                           # verify endpoints/field names without a running instance
├── original-chatgpt-proposal.txt  # Original proposal (ChatGPT); see the icinga documentation for the evaluation
├── icinga/                 # Icinga2 variant
│   ├── INSTALL.md
│   ├── documentation-de.html       # Deutsch
│   ├── documentation.html          # English
│   ├── documentation-fr.html       # Français
│   ├── documentation-es.html       # Español
│   ├── commands.conf.example
│   ├── services-graylog.conf.example
│   └── plugins/check_graylog.py
└── zabbix/                 # Zabbix variant
    ├── INSTALL.md
    ├── documentation-de.html       # Deutsch
    ├── documentation.html          # English
    ├── documentation-fr.html       # Français
    ├── documentation-es.html       # Español
    ├── userparameter_graylog.conf
    └── scripts/check_graylog_zabbix.py
```

## Documentation

The detailed documentation for each variant — how it works, every mode in
detail, authentication, configuration, results of the live verification
against a real Graylog instance, and known open points — lives as an HTML
page in the corresponding subfolder, in four languages. Each language
version is a complete, independently readable translation of the same page
(not a shortened excerpt), with a language switcher at the top of the
sidebar:

| | Icinga2 | Zabbix |
|---|---|---|
| 🇩🇪 Deutsch | [icinga/documentation-de.html](icinga/documentation-de.html) | [zabbix/documentation-de.html](zabbix/documentation-de.html) |
| 🇬🇧 English | [icinga/documentation.html](icinga/documentation.html) | [zabbix/documentation.html](zabbix/documentation.html) |
| 🇫🇷 Français | [icinga/documentation-fr.html](icinga/documentation-fr.html) | [zabbix/documentation-fr.html](zabbix/documentation-fr.html) |
| 🇪🇸 Español | [icinga/documentation-es.html](icinga/documentation-es.html) | [zabbix/documentation-es.html](zabbix/documentation-es.html) |

Additionally, shared across both variants:

- [`GRAYLOG-CONCEPTS.html`](GRAYLOG-CONCEPTS.html) — what journal, cluster
  health, inputs, throughput, nodes, and the internal metrics actually mean
  and why they're worth monitoring, written for readers with no prior
  Graylog experience. Linked from both variants and every language version.

## Why two separate scripts instead of one shared implementation?

Icinga2/Nagios plugins evaluate themselves (exit code + text). Zabbix
strictly separates that: an item only delivers a raw value, and Zabbix
itself evaluates thresholds via trigger expressions. A wrapper that simply
reused the unmodified Icinga2 script for Zabbix would have been quick to
build, but wouldn't be idiomatic Zabbix — Raphael deliberately chose a
native implementation for each instead. The details and trade-offs are
covered in the "Goal & Decision" section of the Zabbix documentation (see
table above).

Both variants share the same API logic (authentication, endpoints, JSON
field names), already verified live against a real Graylog instance — only
the output form differs.

## Quick Start

For installation in your own environment, go straight to the relevant
subfolder:

- Icinga2: [`icinga/INSTALL.md`](icinga/INSTALL.md)
- Zabbix: [`zabbix/INSTALL.md`](zabbix/INSTALL.md)

Both guides are independently readable but cross-reference each other for
the shared Graylog-side setup (Reader user, API token) to avoid maintaining
that text twice.
