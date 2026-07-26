# Installationsanleitung – check_graylog.py für Icinga2

Kurze, eigenständige Anleitung für den produktiven Rollout. Hintergrund, Details
zu allen acht Modi und die Ergebnisse des Live-Tests stehen in
[`documentation-de.html`](documentation-de.html) — hier nur die reinen Schritte.

## Voraussetzungen

- Icinga2-Host mit Python 3 und dem Paket `requests` (`apt install python3-requests`)
- Netzwerkzugriff vom Icinga2-Host auf die Graylog-API (Standardport 9000)
- Admin-Zugang zu Graylog, einmalig für das Anlegen des Monitoring-Users

## 1. Reader-Benutzer in Graylog anlegen

Web-UI: *System → Users → Create User*, Rolle **Reader** zuweisen.

Oder per API:

```bash
curl -u admin:<adminpw> -H "X-Requested-By: cli" -H "Content-Type: application/json" \
  -X POST "http://<graylog>:9000/api/users" \
  -d '{"username":"icinga-monitoring","password":"<starkes-passwort>",
       "first_name":"Icinga","last_name":"Monitoring","email":"icinga@example.org",
       "roles":["Reader"],"permissions":[]}'
```

## 2. Nur falls die Modi `metric`/`list-metrics` genutzt werden sollen

Reader allein reicht dafür **nicht** — Graylog liefert sonst `403 Not authorized`.
Zusätzliche Permissions auf den Benutzer setzen (User-ID vorher per
`GET /api/users/<username>` ermitteln, Feld `id`):

```bash
curl -u admin:<adminpw> -H "X-Requested-By: cli" -H "Content-Type: application/json" \
  -X PUT "http://<graylog>:9000/api/users/<user-id>" \
  -d '{"permissions": ["metrics:read","metrics:allkeys","metrics:readall","metrics:readhistory"]}'
```

## 3. API-Token für den Benutzer erzeugen

```bash
curl -u admin:<adminpw> -H "X-Requested-By: cli" -H "Content-Type: application/json" \
  -X POST "http://<graylog>:9000/api/users/<user-id>/tokens/icinga-check"
```

Die Antwort enthält das Token im Feld `token` — das ist der Wert für
`graylog_token` in Icinga2, **nicht** das Benutzerpasswort.

## 4. Plugin auf den Icinga2-Host kopieren

```bash
cp plugins/check_graylog.py /usr/lib/nagios/plugins/check_graylog.py
chmod +x /usr/lib/nagios/plugins/check_graylog.py
```

## 5. Icinga2-Konfiguration einspielen

```bash
cp commands.conf.example /etc/icinga2/conf.d/graylog-commands.conf
cp services-graylog.conf.example /etc/icinga2/conf.d/graylog-services.conf
```

In der Services-Datei bzw. im `Host`-Objekt der Graylog-Instanz setzen:

```
vars.graylog_url   = "http://<graylog>:9000/api"
vars.graylog_token = "<token aus Schritt 3>"
```

Bei HTTPS mit selbstsigniertem Zertifikat zusätzlich:

```
vars.graylog_insecure = true
```

## 6. Validieren und laden

```bash
icinga2 daemon -C
systemctl reload icinga2
```

## 7. Prüfen

```bash
icinga2 object list --type Service --name '<hostname>!graylog-*'
```

Oder im Icinga-Web-Frontend nach einem Check-Intervall die Services unter
dem entsprechenden Host ansehen.

## Vor dem Produktivbetrieb noch anpassen

- **`journal`-Schwellenwerte**: Default 80&nbsp;%/95&nbsp;% Auslastung — beim
  Live-Test gegen eine leere Instanz getestet (0&nbsp;%), sagt nichts über
  reales Nachrichtenaufkommen aus. Ggf. `graylog_warning`/`graylog_critical`
  anpassen.
- **`nodes`-Modus**: `graylog_expected_nodes` auf die tatsächliche Anzahl
  Graylog-Nodes im Cluster setzen, sonst wird ein ausgefallener Node nicht
  zuverlässig erkannt (nur mit einem einzelnen Node getestet).
- **`metric`/`list-metrics`**: Nur mit einem Beispiel (`jvm.memory.heap.usage`)
  verifiziert. Für weitere Metriken erst `--mode list-metrics --filter <suchbegriff>`
  laufen lassen, um den exakten Namen zu finden, dann einzeln testen.

## Bei Problemen

Das Skript manuell mit denselben Parametern ausführen, die Icinga2 nutzen
würde — zeigt Fehler direkt und ausführlicher als die Icinga-UI:

```bash
python3 /usr/lib/nagios/plugins/check_graylog.py \
  --url http://<graylog>:9000/api --token <token> --mode journal
echo "Exit-Code: $?"
```

Für Details zu allen acht Modi, den beim Live-Test gefundenen und behobenen
Bugs, und der Testumgebung selbst: siehe [`documentation-de.html`](documentation-de.html).
