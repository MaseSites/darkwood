# Mitgelieferte Fremdbibliotheken

Genau eine, und sie steht hier und nicht an einem CDN. Eine Seite, die ihren
Chart erst zeichnen kann, wenn ein fremder Host antwortet, ist in dem Moment
kaputt, in dem dieser Host nicht antwortet — und bei einem Handelsbildschirm
ist genau dieser Moment der, in dem man ihn braucht.

## lightweight-charts

| | |
|---|---|
| Was | TradingView Lightweight Charts™, die Chart-Engine von TradingView selbst |
| Version | **5.2.1** |
| Lizenz | **Apache-2.0** (`lightweight-charts.LICENSE`, unverändert mitgeliefert) |
| Herkunft | `https://registry.npmjs.org/lightweight-charts/-/lightweight-charts-5.2.1.tgz` |
| Paket, sha256 | `64310292298df4dd527494865e5d91d447f8bb397b68de3912c2a6465025ee5e` |
| Paket, npm-integrity | `sha512-IVwoK1RLFiLPubaKIjNbtjWLnpPMqiABSrTay6whmNa8L1+19292VtHJ+BWyPUuLCwF0tcQlhEWd1CLB2a1nsQ==` — gegen die Registry geprüft, stimmt |
| Datei | `package/dist/lightweight-charts.standalone.production.mjs` |
| Datei, sha256 | `1bb1ee79f9d4dd17261b53d930f7a8995748276f80e7ba0e24412b5068062f5f` |
| Grösse | 197.827 Bytes |
| Geholt am | 13.10.2026 |
| Quellcode | `https://github.com/tradingview/lightweight-charts` |

Nachprüfen, ohne mir zu glauben:

```bash
curl -sS -o lwc.tgz https://registry.npmjs.org/lightweight-charts/-/lightweight-charts-5.2.1.tgz
sha256sum lwc.tgz   # 64310292298df4dd527494865e5d91d447f8bb397b68de3912c2a6465025ee5e
tar -xzf lwc.tgz package/dist/lightweight-charts.standalone.production.mjs
sha256sum package/dist/lightweight-charts.standalone.production.mjs
# 1bb1ee79f9d4dd17261b53d930f7a8995748276f80e7ba0e24412b5068062f5f
```

### Warum diese und keine andere

Der Wunsch war „verbinde dich mit TradingView". Die ehrlichste Umsetzung ist
nicht ein API-Schlüssel und eine Abhängigkeit von einem fremden Dienst zur
Laufzeit, sondern **dieselbe Engine**, offen lizenziert, lokal
mitgeliefert: kein Konto, keine Anmeldung, keine Zählung von Aufrufen, keine
Datenweitergabe, und die Kurse bleiben die, die dieses Projekt selbst
erhoben hat.

### Was sie NICHT anfasst

`static/chart.js` bleibt handgeschrieben und bleibt es absichtlich. Dieser
Chart gehört zu einem **Vorschlag**, und sein Kopf dokumentiert eine
Integritätseigenschaft:

> THE CHART STOPS AT THE DECISION. A chart running to the present shows the
> reader what happened next, and then there is nothing left to judge.

Eine Bibliothek, die bis zur Gegenwart zeichnet und schwenken lässt, würde
genau diese Eigenschaft stillschweigend aufheben. Für einen **laufenden**
Trade gilt das Gegenteil — dort muss man sehen, wo der Kurs jetzt steht —
und nur dort kommt diese Bibliothek zum Einsatz
(`static/position-chart.js`).
