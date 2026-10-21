---
typ: produkt-teil
projekt: TradingBrain
bereich: betrieb
status: entwurf
aktualisiert: 2026-10-18
tags: [betrieb, mini-pc, uptime]
---

# 24-7 Betrieb & Mini-PC

Das Zielsystem soll später auf einem kleinen lokalen Rechner dauerhaft laufen. Vor einer Hardwareentscheidung werden reale CPU-, RAM-, Speicher-, Netzwerk- und Datenraten des finalen Systems gemessen.

## Mindestanforderungen an den Betrieb

- automatischer Start mit kontrollierter Zustandsprüfung
- getrennte Dienste für Händler, Dashboard, Datenerfassung und Überwachung
- persistente Logs, Zeit-Synchronisation und regelmäßige Backups
- USV oder definierter Umgang mit Stromausfall
- zweiter Netzwerkpfad oder fail-closed Verhalten bei Verbindungsverlust
- Temperatur-, Speicher-, Prozess- und Datenfrische-Monitoring
- sichere Remote-Wartung ohne offene Geheimnisse
- Reconciliation nach jedem Neustart, bevor neue Orders erlaubt werden

Hardware wird erst ausgewählt, wenn Lastprofil, Ausfallsicherheitsziel und Anzahl gleichzeitig beobachteter Märkte feststehen.

