"""The learning layer: labels, splits and the numeric filter.

Section 2 of the masterplan separates two kinds of learning, and this package is
the second one -- a trainable numeric model that scores whether a signal from
the existing strategy is worth taking. The first kind, an experience store that
Claude reads before deciding, lives in `history/` and `score/`.

Nothing here decides anything on its own. The filter's output is one more input
to the risk layer, which can refuse it, and `risk/` never asks this package
anything. Section 14 is explicit that the risk rules run independently of both
Claude and the trained model, and that neither may change its own limits.
"""
