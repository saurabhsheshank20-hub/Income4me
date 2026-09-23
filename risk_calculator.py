"""
risk_calculator.py
-------------------
Module 4: Risk Management & Position Size Calculator.

Pure Python, no pandas/streamlit dependency, so it's trivially unit-testable
and reusable outside the app (e.g. from a notebook).

Formulas (long trades only -- this screener's whole setup is a long-side
pullback-to-rising-support strategy, so shorts are out of scope):
    Max Rupees at Risk  = Capital * (Risk% / 100)
    Risk per Share      = Entry Price - Stop-Loss Price
    Shares (risk-based) = floor(Max Risk / Risk per Share)
    Trade Value         = Shares * Entry Price
    Required Margin     = Trade Value / Leverage
    Target (R multiple) = Entry + R * Risk per Share

Beyond the brief's literal formulas, this also cross-checks the risk-based
share count against what the account can actually afford under the given
leverage (capital * leverage / entry price). A tight stop-loss can imply a
share count whose trade value exceeds available margin -- silently returning
that number would suggest an unexecutable trade, so it's capped and flagged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class PositionSizeResult:
    valid: bool
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    max_risk_amount: float | None = None
    risk_per_share: float | None = None
    shares: int | None = None
    shares_before_margin_cap: int | None = None
    trade_value: float | None = None
    required_margin: float | None = None
    targets: dict[str, float] | None = None


def calculate_position(
    capital: float,
    risk_pct: float,
    entry_price: float,
    stop_loss_price: float,
    leverage: float,
    rr_targets: tuple[float, ...] = (1.5, 2.0),
) -> PositionSizeResult:
    """Compute position size and risk metrics for a long trade. See module docstring."""

    if capital is None or capital <= 0:
        return PositionSizeResult(valid=False, error="Capital must be greater than zero.")
    if risk_pct is None or not (0 < risk_pct <= 100):
        return PositionSizeResult(valid=False, error="Risk % must be between 0 and 100.")
    if entry_price is None or entry_price <= 0:
        return PositionSizeResult(valid=False, error="Entry price must be greater than zero.")
    if stop_loss_price is None or stop_loss_price <= 0:
        return PositionSizeResult(valid=False, error="Stop-loss price must be greater than zero.")
    if entry_price <= stop_loss_price:
        return PositionSizeResult(
            valid=False,
            error="Stop-loss must be below entry price for a long trade.",
        )
    if leverage is None or leverage < 1:
        return PositionSizeResult(valid=False, error="Leverage must be at least 1x.")

    max_risk_amount = capital * (risk_pct / 100.0)
    risk_per_share = entry_price - stop_loss_price
    shares_by_risk = math.floor(max_risk_amount / risk_per_share)

    if shares_by_risk < 1:
        return PositionSizeResult(
            valid=False,
            error=(
                "Calculated position size is 0 shares: the stop-loss is too wide "
                "for this risk budget. Tighten the stop, increase risk %, or add capital."
            ),
            max_risk_amount=round(max_risk_amount, 2),
            risk_per_share=round(risk_per_share, 2),
        )

    warnings: list[str] = []
    max_affordable_shares = math.floor((capital * leverage) / entry_price)
    shares = min(shares_by_risk, max_affordable_shares)

    if max_affordable_shares < 1:
        return PositionSizeResult(
            valid=False,
            error="Capital and leverage don't cover even 1 share at this entry price.",
            max_risk_amount=round(max_risk_amount, 2),
            risk_per_share=round(risk_per_share, 2),
        )

    if shares < shares_by_risk:
        warnings.append(
            f"Risk-based sizing called for {shares_by_risk} shares, but {capital:,.0f} "
            f"capital at {leverage:g}x leverage only supports {max_affordable_shares}. "
            f"Position capped at {shares} shares -- actual risk taken is lower than "
            f"your target {risk_pct:g}%."
        )

    trade_value = shares * entry_price
    required_margin = trade_value / leverage
    targets = {f"1:{r:g}": round(entry_price + r * risk_per_share, 2) for r in rr_targets}

    return PositionSizeResult(
        valid=True,
        warnings=warnings,
        max_risk_amount=round(max_risk_amount, 2),
        risk_per_share=round(risk_per_share, 2),
        shares=shares,
        shares_before_margin_cap=shares_by_risk,
        trade_value=round(trade_value, 2),
        required_margin=round(required_margin, 2),
        targets=targets,
    )
