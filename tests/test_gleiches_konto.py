"""Welche Journalzeilen eine Kontoansicht zeigt (21.10.2026).

Mit den Regeln `tf=D1,H4,H1` und `bild` bekam das Plankonto eine neue
Signatur, und die Ansicht zeigte 0 von 26 Trades. Das Konto ist der Name im
Zusatz, nicht die Konfiguration, die es gerade faehrt.
"""

from traidingbrain.api.portfolio import gleiches_konto

BASIS = "1000.0|['A', 'B', 'E', 'F', 'G']|1.0|M15|refused-v1|portfolio|cap5|crv0.01"
NEU = f"{BASIS}|tf=D1,H4,H1|bild|plan30x7r15f"


def test_neue_konfiguration_sieht_die_alten_trades_desselben_kontos() -> None:
    assert gleiches_konto(NEU, f"{BASIS}|plan30x7")
    assert gleiches_konto(NEU, f"{BASIS}|plan30x7r15f")
    assert gleiches_konto(NEU, NEU)


def test_anderes_konto_und_replay_bleiben_draussen() -> None:
    altes_konto = "1000.0|['A', 'B', 'E', 'F', 'G']|0.08|M15|refused-v1|portfolio|cap5"
    assert not gleiches_konto(NEU, altes_konto)
    assert not gleiches_konto(NEU, "")
    assert not gleiches_konto(NEU, None)
    assert not gleiches_konto(NEU, f"{BASIS}|demo30x7")


def test_konto_ohne_zusatz_vergleicht_wie_bisher_die_ganze_signatur() -> None:
    altes_konto = "1000.0|['A', 'B', 'E', 'F', 'G']|0.08|M15|refused-v1|portfolio|cap5"
    assert gleiches_konto(altes_konto, altes_konto)
    assert not gleiches_konto(altes_konto, f"{altes_konto}|plan30x7")
