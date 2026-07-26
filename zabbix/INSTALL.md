# Installationsanleitung – check_graylog_zabbix.py für Zabbix

Kurze, eigenständige Anleitung für den produktiven Rollout. Hintergrund,
die Entscheidung für den nativen Ansatz (statt eines einfachen Wrappers um
das Icinga2-Skript), alle 15 Modi im Detail und die Ergebnisse des
Live-Tests stehen in [`documentation-de.html`](documentation-de.html) — hier nur
die reinen Schritte.

Was die gemessenen Werte inhaltlich bedeuten (Journal, Cluster-Health,
Inputs, ...) und warum sie wichtig sind, erklärt
[`../GRAYLOG-CONCEPTS.html`](../GRAYLOG-CONCEPTS.html) ausführlich, auch
ohne Graylog-Vorwissen.

## Voraussetzungen

- Zabbix-**Agent**-Host mit Python 3 und dem Paket `requests` (`apt install python3-requests`)
- Netzwerkzugriff vom Agent-Host auf die Graylog-API (Standardport 9000)
- Admin-Zugang zu Graylog, einmalig für das Anlegen des Monitoring-Users
- Zugriff auf das Zabbix-Frontend (Hosts/Items/Trigger anlegen)

## 1. Reader-Benutzer in Graylog anlegen

Identisch zur Icinga2-Variante — siehe
[`../icinga/INSTALL.md`](../icinga/INSTALL.md), Schritte 1–3 (Benutzer
anlegen, ggf. Metrics-Permissions für `metric`/`list-metrics-lld`
nachrüsten, Token erzeugen). Beide Varianten können sogar denselben
Graylog-Benutzer/Token nutzen, wenn praktisch.

## 2. Skript auf den Zabbix-Agent-Host kopieren

Wichtig: auf den **Agent**, nicht den Server — der Agent führt die
UserParameter-Kommandos aus.

```bash
cp scripts/check_graylog_zabbix.py /usr/lib/zabbix/externalscripts/
chmod +x /usr/lib/zabbix/externalscripts/check_graylog_zabbix.py
```

## 3. UserParameter-Datei einspielen

```bash
cp userparameter_graylog.conf /etc/zabbix/zabbix_agent2.d/
```

In **jeder Zeile** dieser Datei `--url` und `--token` an eure echte
Graylog-Instanz anpassen (Suchen&Ersetzen reicht, alle Zeilen nutzen
dieselben zwei Werte).

```bash
systemctl restart zabbix-agent2
```

## 4. Agent-seitig testen, bevor Zabbix konfiguriert wird

```bash
zabbix_agent2 -t graylog.journal.utilization
```

Erwartete Ausgabe: `graylog.journal.utilization    [s|<Zahl>]` — das `s`
steht für *success*. Ein `e` (error) bedeutet, dass Pfad, Token oder
Netzwerk nicht stimmen; die Fehlermeldung steht direkt dahinter.

## 5. Host in Zabbix anlegen

Web-UI: *Data collection → Hosts → Create host*. Agent-Interface auf die
IP/den Hostnamen des Agent-Hosts aus Schritt 2 zeigen lassen.

## 6. Items anlegen

Pro gewünschtem Wert ein Item, Typ **Zabbix agent**, Key exakt wie in der
UserParameter-Datei. Beispiele:

| Item-Key | Werttyp |
|---|---|
| `graylog.journal.utilization` | Numeric (float) |
| `graylog.journal.uncommitted` | Numeric (unsigned) |
| `graylog.cluster.status` | Character |
| `graylog.lbstatus` | Character |
| `graylog.throughput` | Numeric (unsigned) |
| `graylog.metric[jvm.memory.heap.usage,value]` | Numeric (float) |

## 7. Trigger anlegen

Beispiele, Schwellenwerte nach eigenem Bedarf anpassen:

```
last(/<host>/graylog.journal.utilization)>80    -> Warning
last(/<host>/graylog.journal.utilization)>95    -> High
last(/<host>/graylog.cluster.status)<>"green"   -> Warning
last(/<host>/graylog.inputs.failed)>0           -> Average
last(/<host>/graylog.nodes.total)<<erwartete Anzahl>  -> High
```

## 8. Prüfen

Nach einem Poll-Intervall (Item-`delay`, Default hier 30s vorgeschlagen):
*Monitoring → Latest data* für die Werte, *Monitoring → Problems* für
ausgelöste Trigger.

## Vor dem Produktivbetrieb noch anpassen

- Die vorgeschlagenen Schwellenwerte (80 %/95 % Journal) sind gegen eine
  leere Testinstanz entstanden, nicht gegen euer reales
  Nachrichtenaufkommen validiert.
- `nodes-unhealthy` erkennt einen **komplett fehlenden** Node nicht
  zuverlässig (der taucht in der Antwort schlicht nicht mehr auf) —
  zusätzlich `nodes-total` gegen die bekannte Node-Anzahl prüfen.
- TLS/selbstsignierte Zertifikate: `--insecure` als zusätzliches Argument
  in der UserParameter-Zeile ergänzen.
- Nur getestet mit `metric`-Beispiel `jvm.memory.heap.usage` — für weitere
  Metriken erst `--mode list-metrics-lld --metric-name <suchbegriff>`
  laufen lassen, um den exakten Namen zu finden.

## Bei Problemen

Das Skript manuell mit denselben Parametern ausführen, die der Agent nutzen
würde — zeigt Fehler direkt:

```bash
python3 /usr/lib/zabbix/externalscripts/check_graylog_zabbix.py \
  --url http://<graylog>:9000/api --token <token> --mode journal-utilization
```

Für Details zu allen 15 Modi, die Entscheidung für den nativen Ansatz statt
eines einfachen Wrappers, und die vollständigen Live-Test-Ergebnisse
(inklusive eines tatsächlich ausgelösten Test-Triggers): siehe
[`documentation-de.html`](documentation-de.html).
